"""One locked transaction for command, frozen effects, evidence and retry receipt."""

from contextlib import nullcontext
from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from ..accounting.journal import stored_lines, save_lines, validate_lines
from ..errors import LedgerError
from ..numbers import decimal_text, decimal_value
from . import trades, cash_events, investment_charges
from ..accounting import cash
from ..position import ledger as position
from ..persistence.references import scopes


class Service:
    def __init__(self, store):
        self.store = store

    def normalize(self, conn, kind, payload):
        try:
            day = date.fromisoformat(payload["effective_date"])
        except (ValueError, TypeError, KeyError):
            raise LedgerError(
                "VALIDATION_ERROR", "Enter a date in YYYY-MM-DD format."
            ) from None
        if day.isoformat() != payload["effective_date"]:
            raise LedgerError("VALIDATION_ERROR", "Date must use YYYY-MM-DD format.")
        memo = payload.get("memo")
        if memo is not None and (not isinstance(memo, str) or len(memo) > 2000):
            raise LedgerError("VALIDATION_ERROR", "Memo is too long.")
        if kind == "INVESTMENT_CHARGE":
            data, roles, ledger = investment_charges.normalize(
                conn, self.store.catalog, payload
            )
            return {
                "transaction_type": kind,
                "effective_date": day.isoformat(),
                "memo": memo,
                "accounts": roles,
                "data": data,
                "charge_ledger_account": ledger,
            }
        if kind in cash_events.TABLES:
            data, roles = cash_events.normalize(conn, self.store.catalog, kind, payload)
            return {
                "transaction_type": kind,
                "effective_date": day.isoformat(),
                "memo": memo,
                "accounts": roles,
                "data": data,
            }
        if kind == "TRADE":
            data, roles, product = trades.normalize(
                conn, self.store.catalog, payload, day.isoformat()
            )
            event = {
                "transaction_type": kind,
                "effective_date": day.isoformat(),
                "memo": memo,
                "accounts": roles,
                "data": data,
            }
            position.prepare_position(conn, event, self.store.catalog)
            return event
        if kind != "CASH_TRANSFER":
            raise LedgerError("VALIDATION_ERROR", "Transaction type is not supported.")
        currency = payload.get("currency")
        if currency not in self.store.catalog.currencies:
            raise LedgerError("REFERENCE_NOT_FOUND", "Currency not found.")
        amount = decimal_text(payload.get("amount"), positive=True)
        roles = {}
        for field, role in [
            ("source_account_id", "SOURCE"),
            ("destination_account_id", "DESTINATION"),
        ]:
            value = payload.get(field)
            if value is None:
                continue
            if (
                not isinstance(value, str)
                or not value.isascii()
                or not value.isdigit()
                or len(value) > 18
            ):
                raise LedgerError(
                    "VALIDATION_ERROR", "Financial Account ID must be a valid string."
                )
            account = int(value)
            if not conn.execute(
                "SELECT 1 FROM financial_accounts WHERE financial_account_id=?",
                (account,),
            ).fetchone():
                raise LedgerError("REFERENCE_NOT_FOUND", "Financial Account not found.")
            roles[role] = account
        if not roles or (len(roles) == 2 and len(set(roles.values())) == 1):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Select a Source Account or Destination Account; internal transfers require different accounts.",
            )
        return {
            "transaction_type": kind,
            "effective_date": day.isoformat(),
            "memo": memo,
            "accounts": roles,
            "data": {"currency": currency, "amount": amount},
        }

    def rates(self, conn, event, *, frozen=False):
        functional = conn.execute(
            "SELECT functional_currency FROM accounting_config"
        ).fetchone()[0]
        currencies = (
            [event["currency"]]
            if event["transaction_type"] == "TRADE"
            else [] if len(event["accounts"]) == 2 else [event["data"].get("currency")]
        )
        if event["transaction_type"] in cash_events.TABLES:
            currencies = cash_events.required_rates(event, functional)
        result = {functional: Decimal(1)}
        evidence = []
        for currency in currencies:
            if currency == functional:
                continue
            sql = "SELECT o.* FROM book_fx_observations o "
            args = []
            if frozen:
                sql += "JOIN book_fx_evidence e USING(observation_id) WHERE e.transaction_id=? AND "
                args.append(event["transaction_id"])
            else:
                sql += "WHERE "
            sql += "o.base_currency=? AND o.quote_currency=? AND o.effective_date=? ORDER BY revision DESC LIMIT 1"
            args.extend([currency, functional, event["effective_date"]])
            row = conn.execute(sql, args).fetchone()
            if row is None:
                raise LedgerError(
                    "INTEGRITY_ERROR" if frozen else "VALIDATION_ERROR",
                    f"Missing Book FX for {currency}→{functional} on {event['effective_date']}.",
                    "MISSING_BOOK_FX",
                )
            result[currency] = Decimal(row["rate"])
            evidence.append(row["observation_id"])
        return result, evidence

    def events(self, conn, as_of=None):
        rows = conn.execute(
            "SELECT * FROM transactions"
            + (" WHERE effective_date<=?" if as_of else "")
            + " ORDER BY effective_date,transaction_id",
            (as_of,) if as_of else (),
        )
        result = []
        for row in rows:
            event = dict(row)
            event["accounts"] = {
                r["account_role"]: r["financial_account_id"]
                for r in conn.execute(
                    "SELECT * FROM transaction_accounts WHERE transaction_id=?",
                    (row["transaction_id"],),
                )
            }
            if row["transaction_type"] == "REVERSAL":
                target = conn.execute(
                    "SELECT object_transaction_id FROM transaction_relationships WHERE subject_transaction_id=? AND relationship_type='REVERSES'",
                    (row["transaction_id"],),
                ).fetchone()
                if target is None:
                    raise LedgerError(
                        "INTEGRITY_ERROR", "Reversal relationship is missing."
                    )
                event["data"] = {"target_transaction_id": str(target[0])}
                result.append(event)
                continue
            if row["transaction_type"] == "INVESTMENT_CHARGE":
                event["data"], event["charge_ledger_account"] = investment_charges.load(
                    conn, row["transaction_id"]
                )
                result.append(event)
                continue
            if row["transaction_type"] in cash_events.TABLES:
                event["data"] = cash_events.load(
                    conn, row["transaction_type"], row["transaction_id"]
                )
                result.append(event)
                continue
            if row["transaction_type"] == "TRADE":
                event["data"] = trades.load(conn, row["transaction_id"])
                scope = conn.execute(
                    "SELECT financial_account_id FROM position_scopes WHERE position_scope_id=?",
                    (event["data"]["position_scope_id"],),
                ).fetchone()
                if scope is None or event["accounts"] != {"ACCOUNT": scope[0]}:
                    raise LedgerError(
                        "INTEGRITY_ERROR",
                        "Stored Trade Position Scope and Financial Account do not match.",
                    )
                position.prepare_position(conn, event, self.store.catalog)
                result.append(event)
                continue
            data = conn.execute(
                "SELECT currency,amount FROM cash_transfers WHERE transaction_id=?",
                (row["transaction_id"],),
            ).fetchone()
            if row["transaction_type"] != "CASH_TRANSFER" or data is None:
                raise LedgerError(
                    "INTEGRITY_ERROR", "Transaction subtype is missing or inconsistent."
                )
            event["data"] = dict(data)
            result.append(event)
        return result

    def replay(
        self, conn, *, candidate=None, candidates=None, as_of=None, exclude=None
    ):
        events = self.events(conn, as_of)
        reversed_ids = {
            int(e["data"]["target_transaction_id"])
            for e in events
            if e["transaction_type"] == "REVERSAL"
        }
        events = [
            e
            for e in events
            if e["transaction_type"] != "REVERSAL"
            and e["transaction_id"] not in reversed_ids | (exclude or set())
        ]
        new_events = (
            candidates
            if candidates is not None
            else ([candidate] if candidate is not None else [])
        )
        new_ids = {e["transaction_id"] for e in new_events}
        changing = bool(new_events) or bool(exclude)
        if new_events:
            events.extend(new_events)
            events.sort(key=lambda e: (e["effective_date"], e["transaction_id"]))
        functional = conn.execute(
            "SELECT functional_currency FROM accounting_config"
        ).fetchone()[0]
        state = position.State()
        state.as_of = as_of
        new_lines, new_evidence = {}, {}
        affected = []
        for event in events:
            is_new = event["transaction_id"] in new_ids
            try:
                rates, evidence = self.rates(conn, event, frozen=not is_new)
                lines = (
                    investment_charges.build(event, state, rates)
                    if event["transaction_type"] == "INVESTMENT_CHARGE"
                    else (
                        trades.build(event, state, rates)
                        if event["transaction_type"] == "TRADE"
                        else (
                            cash_events.build(event, state, rates, functional)
                            if event["transaction_type"] in cash_events.TABLES
                            else cash.build(event, state, rates)
                        )
                    )
                )
                validate_lines(lines)
                if not is_new and (
                    Counter(lines)
                    != Counter(stored_lines(conn, event["transaction_id"]))
                    or (
                        event["transaction_type"] == "TRADE"
                        and not position.matches(
                            conn, event, state.effects[event["transaction_id"]]
                        )
                    )
                ):
                    if changing:
                        affected.append(str(event["transaction_id"]))
                    else:
                        raise LedgerError(
                            "INTEGRITY_ERROR",
                            "Frozen journal lines do not match historical replay.",
                            related_transaction_ids=[str(event["transaction_id"])],
                        )
                cash.apply(state, lines)
            except LedgerError as exc:
                if is_new or not changing:
                    raise
                raise LedgerError(
                    "REVERSAL_DEPENDENCY" if exclude else "VALIDATION_ERROR",
                    "This operation would invalidate later transactions.",
                    None if exclude else "BACKDATED_EFFECT_CHANGE",
                    related_transaction_ids=[str(event["transaction_id"])],
                ) from exc
            if is_new:
                (
                    new_lines[event["transaction_id"]],
                    new_evidence[event["transaction_id"]],
                ) = (lines, evidence)
        if affected:
            raise LedgerError(
                "REVERSAL_DEPENDENCY" if exclude else "VALIDATION_ERROR",
                "This operation would change frozen amounts or Cost Basis Lots of later transactions.",
                None if exclude else "BACKDATED_EFFECT_CHANGE",
                related_transaction_ids=affected,
            )
        if candidates is not None:
            return state, new_lines, new_evidence
        return (
            state,
            new_lines.get(candidate["transaction_id"]) if candidate else None,
            new_evidence.get(candidate["transaction_id"], []) if candidate else [],
        )

    def submit(self, kind, payload, request_key, *, preview=False, connection=None):
        result = self.submit_many(
            [
                {
                    "client_event_id": "event",
                    "transaction_type": kind,
                    "payload": payload,
                }
            ],
            [],
            request_key,
            preview=preview,
            connection=connection,
        )
        if preview:
            return result["events"][0]
        return {
            "transaction_id": result["events"][0]["transaction_id"],
            "replayed": result["replayed"],
        }

    def submit_many(
        self, events, relationships, request_key, *, preview=False, connection=None
    ):
        if (
            not isinstance(request_key, str)
            or not request_key.strip()
            or len(request_key) > 200
        ):
            raise LedgerError("VALIDATION_ERROR", "A valid request ID is required.")
        if (
            not isinstance(events, list)
            or not 1 <= len(events) <= 1000
            or not isinstance(relationships, list)
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "A request requires 1 to 1000 events and a relationship list.",
            )
        fingerprint = sha256(
            json.dumps(
                [events, relationships],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        with localcontext() as context:
            context.prec = 80
            with (
                self.store.transaction()
                if connection is None
                else nullcontext(connection)
            ) as conn:
                conn.execute("SAVEPOINT investment_request")
                try:
                    result = self._submit_many(
                        conn, events, relationships, request_key, fingerprint, preview
                    )
                    if preview:
                        conn.execute("ROLLBACK TO investment_request")
                    conn.execute("RELEASE investment_request")
                    return result
                except BaseException:
                    conn.execute("ROLLBACK TO investment_request")
                    conn.execute("RELEASE investment_request")
                    raise

    def _submit_many(
        self, conn, inputs, relationships, request_key, fingerprint, preview
    ):
        from .relationships import add_relationships

        receipt = conn.execute(
            "SELECT * FROM command_receipts WHERE request_key=?", (request_key,)
        ).fetchone()
        if receipt:
            if receipt["payload_hash"] != fingerprint:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "This request ID has already been used for different content.",
                    "IDEMPOTENCY_CONFLICT",
                )
            items = [
                {
                    "client_event_id": r["client_event_id"],
                    "transaction_id": str(r["transaction_id"]),
                }
                for r in conn.execute(
                    "SELECT * FROM command_receipt_transactions WHERE request_key=? ORDER BY ordinal",
                    (request_key,),
                )
            ]
            if preview:
                for item in items:
                    item.update(
                        journal=serialize_lines(
                            stored_lines(conn, int(item["transaction_id"]))
                        ),
                        allocations=position.detail(conn, int(item["transaction_id"]))[
                            "allocations"
                        ],
                        effective_date=conn.execute(
                            "SELECT effective_date FROM transactions WHERE transaction_id=?",
                            (item["transaction_id"],),
                        ).fetchone()[0],
                    )
            return {"events": items, "replayed": True}
        seq = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='transactions'"
        ).fetchone()
        next_id = (seq[0] if seq else 0) + 1
        candidates, client_ids = [], {}
        positions = {
            r["observable_id"]: r["position_id"]
            for r in conn.execute("SELECT * FROM positions")
        }
        pseq = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='positions'"
        ).fetchone()
        next_position = (pseq[0] if pseq else 0) + 1
        for index, item in enumerate(inputs):
            if not isinstance(item, dict) or set(item) != {
                "client_event_id",
                "transaction_type",
                "payload",
            }:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Each event requires client_event_id, transaction_type and payload.",
                )
            client_id = item["client_event_id"]
            if (
                not isinstance(client_id, str)
                or not client_id.strip()
                or len(client_id) > 200
                or client_id in client_ids
                or not isinstance(item["payload"], dict)
            ):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Event IDs must be nonblank and unique within a request.",
                )
            event = self.normalize(conn, item["transaction_type"], item["payload"])
            event["transaction_id"] = next_id + index
            if event["transaction_type"] == "TRADE":
                oid = event["observable_id"]
                if oid not in positions:
                    positions[oid] = next_position
                    next_position += 1
                event["position_id"] = positions[oid]
            client_ids[client_id] = event["transaction_id"]
            candidates.append(event)
        state, lines, evidence = self.replay(conn, candidates=candidates)
        # Allocate parents in request order, then persist effects in economic order.
        # A later-dated sale can precede its earlier-dated BUY in the submitted list.
        for event in candidates:
            tid = conn.execute(
                "INSERT INTO transactions(transaction_type,effective_date,memo) VALUES (?,?,?)",
                (event["transaction_type"], event["effective_date"], event["memo"]),
            ).lastrowid
            if tid != event["transaction_id"]:
                raise LedgerError("INTEGRITY_ERROR", "Transaction ordering conflict.")
        for event in sorted(
            candidates, key=lambda e: (e["effective_date"], e["transaction_id"])
        ):
            tid = event["transaction_id"]
            self._persist(conn, event, state, lines[tid], evidence[tid])
        add_relationships(conn, relationships, client_ids)
        conn.execute(
            "INSERT INTO command_receipts VALUES (?,?)", (request_key, fingerprint)
        )
        results = []
        for ordinal, (client_id, tid) in enumerate(client_ids.items()):
            conn.execute(
                "INSERT INTO command_receipt_transactions VALUES (?,?,?,?)",
                (request_key, ordinal, client_id, tid),
            )
            item = {"client_event_id": client_id, "transaction_id": str(tid)}
            if preview:
                event = candidates[ordinal]
                item.update(
                    position_scope_id=(
                        str(event["data"]["position_scope_id"])
                        if event["transaction_type"] == "TRADE"
                        else None
                    ),
                    journal=serialize_lines(lines[tid]),
                    effective_date=event["effective_date"],
                    allocations=[
                        {
                            "buy_transaction_id": str(source),
                            "quantity_disposed": decimal_text(q),
                            "book_cost_disposed": decimal_text(cost),
                        }
                        for source, q, cost in state.effects.get(tid, {}).get(
                            "allocations", []
                        )
                    ],
                )
            results.append(item)
        return {"events": results, "replayed": False}

    def _persist(self, conn, event, state, lines, evidence):
        kind = event["transaction_type"]
        tid = event["transaction_id"]
        if kind == "CASH_TRANSFER":
            conn.execute(
                "INSERT INTO cash_transfers VALUES (?,?,?)",
                (tid, event["data"]["currency"], event["data"]["amount"]),
            )
        elif kind == "TRADE":
            conn.execute(
                "INSERT OR IGNORE INTO positions(position_id,observable_id) VALUES (?,?)",
                (event["position_id"], event["observable_id"]),
            )
            pins = [
                ("PRODUCT", event["data"]["product_id"]),
                ("OBSERVABLE", event["observable_id"]),
            ]
            if event["data"]["listing_id"]:
                pins.append(("LISTING", event["data"]["listing_id"]))
            for target_type, target_id in pins:
                conn.execute(
                    "INSERT OR IGNORE INTO reference_catalog_pins VALUES (?,?,?)",
                    (
                        target_type,
                        target_id,
                        self.store.catalog.fingerprint(target_type, target_id),
                    ),
                )
        if kind == "INVESTMENT_CHARGE":
            investment_charges.save(conn, event)
        if kind in cash_events.TABLES:
            cash_events.save(conn, event)
            if kind == "DIVIDEND_RECEIPT":
                oid = event["data"]["observable_id"]
                conn.execute(
                    "INSERT OR IGNORE INTO reference_catalog_pins VALUES ('OBSERVABLE',?,?)",
                    (oid, self.store.catalog.fingerprint("OBSERVABLE", oid)),
                )
        conn.executemany(
            "INSERT INTO transaction_accounts VALUES (?,?,?)",
            [(tid, r, a) for r, a in event["accounts"].items()],
        )
        line_ids = save_lines(conn, tid, lines)
        if kind == "TRADE":
            trades.save(
                conn,
                event,
                state.effects[tid],
                line_ids,
                lines,
                self.store.catalog,
            )
        conn.executemany(
            "INSERT INTO book_fx_evidence VALUES (?,?)",
            [(tid, i) for i in evidence],
        )

    def _reversal_target(self, conn, tid):
        target = conn.execute(
            "SELECT * FROM transactions WHERE transaction_id=?", (tid,)
        ).fetchone()
        if target is None:
            raise LedgerError("REFERENCE_NOT_FOUND", "Transaction not found.")
        if target["transaction_type"] == "REVERSAL":
            raise LedgerError("VALIDATION_ERROR", "A Reversal cannot be reversed.")
        if conn.execute(
            "SELECT 1 FROM transaction_relationships WHERE object_transaction_id=? AND relationship_type='REVERSES'",
            (tid,),
        ).fetchone():
            raise LedgerError(
                "VALIDATION_ERROR", "This transaction has already been reversed."
            )
        self.replay(conn, exclude={tid})
        return target

    def reversal_check(self, tid):
        with localcontext() as context:
            context.prec = 80
            with self.store.read() as conn:
                target = self._reversal_target(conn, tid)
                return {
                    "allowed": True,
                    "target_transaction_id": str(tid),
                    "effective_date": target["effective_date"],
                    "journal": serialize_lines(
                        [l.inverse() for l in stored_lines(conn, tid)]
                    ),
                }

    def reverse(self, tid, request_key, memo=None):
        if (
            not isinstance(request_key, str)
            or not request_key.strip()
            or len(request_key) > 200
        ):
            raise LedgerError("VALIDATION_ERROR", "A valid request ID is required.")
        if memo is not None and (not isinstance(memo, str) or len(memo) > 2000):
            raise LedgerError("VALIDATION_ERROR", "Memo is too long.")
        fingerprint = sha256(
            json.dumps(["REVERSAL", tid, memo], ensure_ascii=False).encode()
        ).hexdigest()
        with localcontext() as context:
            context.prec = 80
            with self.store.transaction() as conn:
                receipt = conn.execute(
                    "SELECT * FROM command_receipts WHERE request_key=?", (request_key,)
                ).fetchone()
                if receipt:
                    if receipt["payload_hash"] != fingerprint:
                        raise LedgerError(
                            "VALIDATION_ERROR",
                            "This request ID has already been used for different content.",
                            "IDEMPOTENCY_CONFLICT",
                        )
                    return {
                        "transaction_id": str(
                            conn.execute(
                                "SELECT transaction_id FROM command_receipt_transactions WHERE request_key=? ORDER BY ordinal",
                                (request_key,),
                            ).fetchone()[0]
                        ),
                        "replayed": True,
                    }
                target = self._reversal_target(conn, tid)
                new = conn.execute(
                    "INSERT INTO transactions(transaction_type,effective_date,memo) VALUES ('REVERSAL',?,?)",
                    (target["effective_date"], memo),
                ).lastrowid
                conn.execute(
                    "INSERT INTO transaction_relationships VALUES (?,'REVERSES',?)",
                    (new, tid),
                )
                save_lines(
                    conn, new, [line.inverse() for line in stored_lines(conn, tid)]
                )
                position.reverse(conn, tid, new)
                conn.execute(
                    "INSERT INTO command_receipts VALUES (?,?)",
                    (request_key, fingerprint),
                )
                conn.execute(
                    "INSERT INTO command_receipt_transactions VALUES (?,0,'event',?)",
                    (request_key, new),
                )
                self.replay(conn)
                return {"transaction_id": str(new), "replayed": False}

    def balances(self, as_of=None, include_zero=False):
        with localcontext() as context:
            context.prec = 80
            with self.store.read() as conn:
                state = position.read_state(conn, as_of)
                state.include_zero = include_zero
                raw = {}
                sql = "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE ledger_account_code='CASH'"
                if as_of:
                    sql += " AND t.effective_date<=?"
                for line in conn.execute(sql, (as_of,) if as_of else ()):
                    key = (line["financial_account_id"], line["native_currency"])
                    q, b = raw.get(key, (Decimal(0), Decimal(0)))
                    sign = 1 if line["side"] == "DEBIT" else -1
                    raw[key] = (
                        q + sign * Decimal(line["native_amount"]),
                        b + sign * Decimal(line["book_amount"]),
                    )
                accounts = {
                    r["financial_account_id"]: dict(r)
                    for r in conn.execute("SELECT * FROM financial_accounts")
                }
                result = {
                    "as_of": as_of,
                    "transaction_count": len(self.events(conn, as_of)),
                    "cash": [
                        {
                            "financial_account_id": str(account),
                            "account_name": accounts[account]["display_name"],
                            "currency": currency,
                            "observable_id": self.store.catalog.currencies[currency],
                            "quantity": decimal_text(q),
                            "book_value": decimal_text(b),
                        }
                        for (account, currency), (q, b) in sorted(raw.items())
                        if q or include_zero
                    ],
                    "investments": investment_rows(
                        conn, state, self.store.catalog, accounts
                    ),
                }
                return result

    def transactions(
        self,
        as_of=None,
        limit=50,
        offset=0,
        account_id=None,
        transaction_type=None,
        date_from=None,
        currency=None,
        observable_id=None,
        status=None,
        date_to=None,
    ):
        with self.store.read() as conn:
            events = self.events(conn, as_of)
            if status not in (None, "ACTIVE", "REVERSED"):
                raise LedgerError("VALIDATION_ERROR", "Invalid transaction status.")
            reversed_ids = {
                int(e["data"]["target_transaction_id"])
                for e in events
                if e["transaction_type"] == "REVERSAL"
            }
            if status:
                events = [
                    e
                    for e in events
                    if (e["transaction_id"] in reversed_ids) == (status == "REVERSED")
                ]
            if date_to:
                events = [e for e in events if e["effective_date"] <= date_to]
            if account_id is not None:
                all_events = {e["transaction_id"]: e for e in self.events(conn)}
                events = [
                    e
                    for e in events
                    if account_id
                    in (
                        all_events[int(e["data"]["target_transaction_id"])]["accounts"]
                        if e["transaction_type"] == "REVERSAL"
                        else e["accounts"]
                    ).values()
                ]
            all_events = {e["transaction_id"]: e for e in self.events(conn)}

            def economic(e):
                return (
                    all_events[int(e["data"]["target_transaction_id"])]
                    if e["transaction_type"] == "REVERSAL"
                    else e
                )

            if transaction_type:
                events = [
                    e for e in events if e["transaction_type"] == transaction_type
                ]
            if date_from:
                events = [e for e in events if e["effective_date"] >= date_from]
            if currency:
                events = [
                    e
                    for e in events
                    if currency
                    in [
                        economic(e).get("currency"),
                        *(
                            economic(e)["data"].get(k)
                            for k in ("currency", "sell_currency", "buy_currency")
                        ),
                    ]
                ]
            if observable_id:
                events = [
                    e
                    for e in events
                    if economic(e).get(
                        "observable_id", economic(e)["data"].get("observable_id")
                    )
                    == observable_id
                ]
            return {
                "total": len(events),
                "rows": [serialize_event(e) for e in reversed(events)][
                    offset : offset + limit
                ],
            }

    def detail(self, tid):
        with self.store.read() as conn:
            event = next(
                (e for e in self.events(conn) if e["transaction_id"] == tid), None
            )
            if event is None:
                raise LedgerError("REFERENCE_NOT_FOUND", "Transaction not found.")
            reversal = conn.execute(
                "SELECT subject_transaction_id FROM transaction_relationships WHERE object_transaction_id=? AND relationship_type='REVERSES'",
                (tid,),
            ).fetchone()
            return serialize_ids(
                {
                    "reversed_by": str(reversal[0]) if reversal else None,
                    **serialize_event(event),
                    **position.detail(conn, tid),
                    "journal": serialize_lines(stored_lines(conn, tid)),
                    "charge_relationships": [
                        dict(r)
                        for r in conn.execute(
                            "SELECT * FROM transaction_relationships WHERE relationship_type='CHARGE_FOR' AND (subject_transaction_id=? OR object_transaction_id=?) ORDER BY subject_transaction_id,object_transaction_id",
                            (tid, tid),
                        )
                    ],
                    "book_fx_evidence": [
                        dict(r)
                        for r in conn.execute(
                            "SELECT o.* FROM book_fx_observations o JOIN book_fx_evidence e USING(observation_id) WHERE e.transaction_id=?",
                            (tid,),
                        )
                    ],
                }
            )


def serialize_event(event):
    return serialize_ids(
        {
            **event,
            "transaction_id": str(event["transaction_id"]),
            "accounts": {r: str(a) for r, a in event["accounts"].items()},
        }
    )


def serialize_lines(lines):
    return [
        {
            k: (
                decimal_text(v)
                if isinstance(v, Decimal)
                else str(v) if k.endswith("_id") and v is not None else v
            )
            for k, v in asdict(line).items()
        }
        for line in lines
    ]


def investment_rows(conn, state, catalog, accounts):
    buckets = {}
    for lot in state.lots.values():
        key = (lot["position_id"], lot["scope_id"])
        q, b = buckets.get(key, (Decimal(0), Decimal(0)))
        buckets[key] = (q + lot["remaining_quantity"], b + lot["remaining_basis"])
    actual = {}
    sql = "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE l.line_type='LOCATION'"
    if state.as_of:
        sql += " AND t.effective_date<=?"
    for line in conn.execute(sql, (state.as_of,) if state.as_of else ()):
        key = (line["position_id"], line["position_scope_id"])
        actual[key] = actual.get(key, Decimal(0)) + Decimal(line["quantity_delta"])
    if {k: v for k, v in actual.items() if v} != {
        k: v[0] for k, v in buckets.items() if v[0]
    }:
        raise LedgerError(
            "INTEGRITY_ERROR",
            "Position and Cost Basis Lot quantities are inconsistent.",
        )
    owners = {}
    sql = "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE l.line_type='OWNERSHIP'"
    if state.as_of:
        sql += " AND t.effective_date<=?"
    for line in conn.execute(sql, (state.as_of,) if state.as_of else ()):
        if line["owner_id"] != 1:
            raise LedgerError("INTEGRITY_ERROR", "Unsupported Position owner.")
        owners[line["position_id"]] = owners.get(
            line["position_id"], Decimal(0)
        ) + Decimal(line["quantity_delta"])
    totals = {}
    for (pid, sid), q in actual.items():
        totals[pid] = totals.get(pid, Decimal(0)) + q
    if {k: v for k, v in owners.items() if v} != {k: v for k, v in totals.items() if v}:
        raise LedgerError(
            "INTEGRITY_ERROR", "Ownership and Location quantities do not balance."
        )
    investment = {}
    sql = "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE ledger_account_code='INVESTMENT'"
    if state.as_of:
        sql += " AND t.effective_date<=?"
    for line in conn.execute(sql, (state.as_of,) if state.as_of else ()):
        pid = line["position_id"]
        investment[pid] = investment.get(pid, Decimal(0)) + (
            1 if line["side"] == "DEBIT" else -1
        ) * Decimal(line["book_amount"])
    basis = {}
    for (pid, account), (q, b) in buckets.items():
        basis[pid] = basis.get(pid, Decimal(0)) + b
    if {k: v for k, v in investment.items() if v} != {
        k: v for k, v in basis.items() if v
    }:
        raise LedgerError(
            "INTEGRITY_ERROR",
            "Investment journal lines and Cost Basis Lot costs are inconsistent.",
        )
    if getattr(state, "include_zero", False):
        for key in actual:
            buckets.setdefault(key, (Decimal(0), Decimal(0)))
    positions = {
        r["position_id"]: r["observable_id"]
        for r in conn.execute("SELECT * FROM positions")
    }
    scope_map = {int(r["position_scope_id"]): r for r in scopes(conn)}
    grouped = {}
    for (pid, sid), (q, b) in sorted(buckets.items()):
        if not q and not getattr(state, "include_zero", False):
            continue
        scope = scope_map[sid]
        account = int(scope["financial_account_id"])
        key = (pid, account)
        if key not in grouped:
            observable = catalog.observables[positions[pid]]
            grouped[key] = {
                "observable_id": positions[pid],
                "name": observable.name,
                "code": observable.code,
                "asset_class": observable.asset_class,
                "position_id": str(pid),
                "financial_account_id": str(account),
                "account_name": accounts[account]["display_name"],
                "quantity": Decimal(0),
                "book_value": Decimal(0),
                "scopes": [],
            }
        row = grouped[key]
        row["quantity"] += q
        row["book_value"] += b
        row["scopes"].append(
            {**scope, "quantity": decimal_text(q), "book_value": decimal_text(b)}
        )
    return [
        {
            **r,
            "quantity": decimal_text(r["quantity"]),
            "book_value": decimal_text(r["book_value"]),
        }
        for _, r in sorted(grouped.items())
    ]


def serialize_ids(value):
    if isinstance(value, list):
        return [serialize_ids(v) for v in value]
    if isinstance(value, dict):
        return {
            k: str(v) if k.endswith("_id") and isinstance(v, int) else serialize_ids(v)
            for k, v in value.items()
        }
    return value
