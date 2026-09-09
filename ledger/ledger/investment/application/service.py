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
from . import trades, cash_events
from ..accounting import cash
from ..position import ledger as position


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
            if row["transaction_type"] in cash_events.TABLES:
                event["data"] = cash_events.load(
                    conn, row["transaction_type"], row["transaction_id"]
                )
                result.append(event)
                continue
            if row["transaction_type"] == "TRADE":
                event["data"] = trades.load(conn, row["transaction_id"])
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

    def replay(self, conn, *, candidate=None, as_of=None, exclude=None):
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
        changing = candidate is not None or bool(exclude)
        if candidate:
            events.append(candidate)
            events.sort(key=lambda e: (e["effective_date"], e["transaction_id"]))
        functional = conn.execute(
            "SELECT functional_currency FROM accounting_config"
        ).fetchone()[0]
        state = position.State()
        state.as_of = as_of
        candidate_lines = None
        candidate_evidence = []
        affected = []
        for event in events:
            is_new = event is candidate
            try:
                rates, evidence = self.rates(conn, event, frozen=not is_new)
                lines = (
                    trades.build(event, state, rates)
                    if event["transaction_type"] == "TRADE"
                    else (
                        cash_events.build(event, state, rates, functional)
                        if event["transaction_type"] in cash_events.TABLES
                        else cash.build(event, state, rates)
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
                candidate_lines, candidate_evidence = lines, evidence
        if affected:
            raise LedgerError(
                "REVERSAL_DEPENDENCY" if exclude else "VALIDATION_ERROR",
                "This operation would change frozen amounts or Cost Basis Lots of later transactions.",
                None if exclude else "BACKDATED_EFFECT_CHANGE",
                related_transaction_ids=affected,
            )
        return state, candidate_lines, candidate_evidence

    def submit(self, kind, payload, request_key, *, preview=False, connection=None):
        if (
            not isinstance(request_key, str)
            or not request_key.strip()
            or len(request_key) > 200
        ):
            raise LedgerError("VALIDATION_ERROR", "A valid request ID is required.")
        # Hash the original exact request. A retry must repeat the same content.
        fingerprint = sha256(
            json.dumps(
                [kind, payload],
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
                receipt = conn.execute(
                    "SELECT * FROM command_receipts WHERE request_key=?", (request_key,)
                ).fetchone()
                if receipt and not preview:
                    if receipt["payload_hash"] != fingerprint:
                        raise LedgerError(
                            "VALIDATION_ERROR",
                            "This request ID has already been used for different content.",
                            "IDEMPOTENCY_CONFLICT",
                        )
                    return {
                        "transaction_id": str(receipt["transaction_id"]),
                        "replayed": True,
                    }
                event = self.normalize(conn, kind, payload)
                # Use the next real AUTOINCREMENT value under the same exclusive writer lock.
                sequence = conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='transactions'"
                ).fetchone()
                event["transaction_id"] = (sequence[0] if sequence else 0) + 1
                state, lines, evidence = self.replay(conn, candidate=event)
                if preview:
                    return {
                        "journal": serialize_lines(lines),
                        "effective_date": event["effective_date"],
                        "allocations": [
                            {
                                "buy_transaction_id": str(source),
                                "quantity_disposed": decimal_text(q),
                                "book_cost_disposed": decimal_text(cost),
                            }
                            for source, q, cost in state.effects.get(
                                event["transaction_id"], {}
                            ).get("allocations", [])
                        ],
                    }
                tid = conn.execute(
                    "INSERT INTO transactions(transaction_type,effective_date,memo) VALUES (?,?,?)",
                    (kind, event["effective_date"], event["memo"]),
                ).lastrowid
                if tid != event["transaction_id"]:
                    raise LedgerError(
                        "INTEGRITY_ERROR", "Transaction ordering conflict."
                    )
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
                conn.execute(
                    "INSERT INTO command_receipts VALUES (?,?,?)",
                    (request_key, fingerprint, tid),
                )
                self.replay(conn)
                return {"transaction_id": str(tid), "replayed": False}

    def _reversal_target(self, conn, tid):
        target = conn.execute(
            "SELECT * FROM transactions WHERE transaction_id=?", (tid,)
        ).fetchone()
        if target is None:
            raise LedgerError("REFERENCE_NOT_FOUND", "Transaction not found.")
        if target["transaction_type"] == "REVERSAL":
            raise LedgerError("VALIDATION_ERROR", "A Reversal cannot be reversed.")
        if conn.execute(
            "SELECT 1 FROM transaction_relationships WHERE object_transaction_id=?",
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
                        "transaction_id": str(receipt["transaction_id"]),
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
                    "INSERT INTO command_receipts VALUES (?,?,?)",
                    (request_key, fingerprint, new),
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
                "SELECT subject_transaction_id FROM transaction_relationships WHERE object_transaction_id=?",
                (tid,),
            ).fetchone()
            return serialize_ids(
                {
                    "reversed_by": str(reversal[0]) if reversal else None,
                    **serialize_event(event),
                    **position.detail(conn, tid),
                    "journal": serialize_lines(stored_lines(conn, tid)),
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
        key = (lot["position_id"], lot["account_id"])
        q, b = buckets.get(key, (Decimal(0), Decimal(0)))
        buckets[key] = (q + lot["remaining_quantity"], b + lot["remaining_basis"])
    actual = {}
    sql = "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE l.line_type='LOCATION'"
    if state.as_of:
        sql += " AND t.effective_date<=?"
    for line in conn.execute(sql, (state.as_of,) if state.as_of else ()):
        key = (line["position_id"], line["financial_account_id"])
        actual[key] = actual.get(key, Decimal(0)) + Decimal(line["quantity_delta"])
    if {k: v for k, v in actual.items() if v} != {
        k: v[0] for k, v in buckets.items() if v[0]
    }:
        raise LedgerError(
            "INTEGRITY_ERROR",
            "Position and Cost Basis Lot quantities are inconsistent.",
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
    return [
        {
            "observable_id": positions[pid],
            "name": catalog.observables[positions[pid]].name,
            "code": catalog.observables[positions[pid]].code,
            "asset_class": catalog.observables[positions[pid]].asset_class,
            "position_id": str(pid),
            "financial_account_id": str(account),
            "account_name": accounts[account]["display_name"],
            "quantity": decimal_text(q),
            "book_value": decimal_text(b),
        }
        for (pid, account), (q, b) in sorted(buckets.items())
        if q or getattr(state, "include_zero", False)
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
