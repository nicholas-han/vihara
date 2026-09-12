from datetime import date
from decimal import localcontext, Decimal
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import sqlite3
from ..application.service import Service
from ..persistence.store import Store
from ..errors import LedgerError
from instrument_manager.holding_catalog import CatalogError

KINDS = {
    "TRADE",
    "CASH_TRANSFER",
    "FX_CONVERSION",
    "DIVIDEND_RECEIPT",
    "INVESTMENT_CHARGE",
}
ALLOWED_OVERRIDES = {
    "account_code",
    "position_scope_code",
    "source_account_code",
    "destination_account_code",
    "product_id",
    "listing_id",
    "observable_id",
}


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def normalize(store, conn, row):
    raw = {**json.loads(row["raw_json"]), **json.loads(row["override_json"])}
    if any(v is None or isinstance(v, list) for v in raw.values()):
        raise LedgerError("VALIDATION_ERROR", "CSV column count does not match.")
    kind = raw.get("transaction_type", "").strip().upper()
    if "fees" in raw:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Legacy fees columns are not supported; provide independent Investment Charge rows.",
            "LEGACY_TRADE_FEES",
        )
    if kind not in KINDS:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Unsupported transaction type.",
        )
    if None in raw or any(isinstance(v, list) for v in raw.values()):
        raise LedgerError("VALIDATION_ERROR", "CSV column count does not match.")
    payload = {
        "effective_date": raw.get("effective_date"),
        "memo": raw.get("memo") or None,
    }

    def account(code, required=True):
        if not code:
            if required:
                raise LedgerError(
                    "REFERENCE_NOT_FOUND", "Financial Account code is required."
                )
            return None
        found = conn.execute(
            "SELECT financial_account_id FROM financial_accounts WHERE account_code=?",
            (code.strip(),),
        ).fetchone()
        if found is None:
            raise LedgerError(
                "REFERENCE_NOT_FOUND", f"Financial Account code not found: {code}"
            )
        return str(found[0])

    if kind == "CASH_TRANSFER":
        payload.update(
            currency=raw.get("currency"),
            amount=raw.get("amount"),
            source_account_id=account(raw.get("source_account_code"), False),
            destination_account_id=account(raw.get("destination_account_code"), False),
        )
    else:
        account_code = raw.get("account_code")
        number = raw.get("external_account_number")
        if account_code:
            payload["account_id"] = account(account_code)
        elif number:
            matches = conn.execute(
                "SELECT financial_account_id FROM external_account_references WHERE external_account_number=?",
                (number.strip(),),
            ).fetchall()
            if len(matches) != 1:
                raise LedgerError(
                    "AMBIGUOUS_REFERENCE" if matches else "REFERENCE_NOT_FOUND",
                    "External account number does not resolve to exactly one Financial Account; map the account explicitly.",
                )
            payload["account_id"] = str(matches[0][0])
        else:
            payload["account_id"] = account(account_code)
        if (
            number
            and not conn.execute(
                "SELECT 1 FROM external_account_references WHERE financial_account_id=? AND external_account_number=?",
                (payload["account_id"], number.strip()),
            ).fetchone()
        ):
            raise LedgerError(
                "REFERENCE_NOT_FOUND",
                "External account number is not registered for this Financial Account.",
            )
    if kind == "TRADE":
        from ..persistence.references import scopes

        candidates = scopes(conn, int(payload["account_id"]))
        explicit = raw.get("position_scope_code")
        label = raw.get("source_tax_label")
        # Source labels may identify a scope directly or a tax classification shared by scopes.
        labelled = [
            c
            for c in candidates
            if label
            and label.strip()
            in (
                c["scope_code"],
                c["display_name"],
                c["tax_scheme_code"],
                c["tax_scheme_name"],
            )
        ]
        if explicit:
            selected = [c for c in candidates if c["scope_code"] == explicit.strip()]
            if not selected:
                raise LedgerError(
                    "REFERENCE_NOT_FOUND",
                    "Position Scope code not found in this Financial Account.",
                )
            if labelled and selected[0] not in labelled:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Explicit Position Scope conflicts with the source tax label.",
                )
        elif label:
            selected = labelled
        else:
            selected = candidates
        if len(selected) != 1:
            raise LedgerError(
                (
                    "AMBIGUOUS_REFERENCE"
                    if selected or candidates
                    else "REFERENCE_NOT_FOUND"
                ),
                "Trade requires exactly one Position Scope; map the scope explicitly.",
                candidates=candidates,
            )
        payload["position_scope_id"] = selected[0]["position_scope_id"]
        product, listing = raw.get("product_id"), raw.get("listing_id") or None
        if not product:
            try:
                day = date.fromisoformat(payload["effective_date"])
            except (ValueError, TypeError):
                raise LedgerError("VALIDATION_ERROR", "Invalid Trade Date.") from None
            resolution = store.catalog.resolve(
                raw.get("identifier_scheme") or "TICKER",
                raw.get("identifier") or "",
                day,
                authority=raw.get("authority") or None,
                venue_id=raw.get("venue_id") or None,
                venue_segment=raw.get("venue_segment") or None,
            )
            if resolution["state"] != "FOUND":
                raise LedgerError(
                    (
                        "AMBIGUOUS_REFERENCE"
                        if resolution["state"] == "AMBIGUOUS"
                        else "REFERENCE_NOT_FOUND"
                    ),
                    "Product identifier is ambiguous; map the Product explicitly.",
                    candidates=resolution["candidates"],
                )
            target = resolution["candidates"][0]
            if target["target_type"] == "PRODUCT":
                product = target["target_id"]
            elif target["target_type"] == "LISTING":
                listing = target["target_id"]
                product = store.catalog.listings[listing].product_id
            else:
                candidates = [
                    p.product_id
                    for p in store.catalog.products.values()
                    if p.asset_observable_id == target["target_id"]
                ]
                matching_listings = [
                    l
                    for l in store.catalog.listings.values()
                    if l.product_id in candidates
                    and (not raw.get("venue_id") or l.venue_id == raw["venue_id"])
                    and (
                        not raw.get("venue_segment")
                        or l.venue_segment == raw["venue_segment"]
                    )
                    and (not listing or l.listing_id == listing)
                ]
                if raw.get("venue_id") or raw.get("venue_segment") or listing:
                    candidates = sorted({l.product_id for l in matching_listings})
                if len(candidates) != 1:
                    raise LedgerError(
                        "AMBIGUOUS_REFERENCE",
                        "This Observable has multiple Products; specify a Product.",
                        candidates=candidates,
                    )
                product = candidates[0]
                if (raw.get("venue_id") or raw.get("venue_segment")) and len(
                    matching_listings
                ) == 1:
                    listing = matching_listings[0].listing_id
        payload.update(
            product_id=product,
            listing_id=listing,
            side=raw.get("side", "").upper(),
            quantity=raw.get("quantity"),
            price=raw.get("price"),
            trade_time=raw.get("trade_time") or None,
            scheduled_settlement_date=raw.get("scheduled_settlement_date") or None,
        )
    elif kind == "FX_CONVERSION":
        payload.update(
            {
                k: raw.get(k)
                for k in ("sell_currency", "sell_amount", "buy_currency", "buy_amount")
            }
        )
    elif kind == "DIVIDEND_RECEIPT":
        payload.update({k: raw.get(k) for k in ("observable_id", "currency", "amount")})
    elif kind == "INVESTMENT_CHARGE":
        from ..persistence.charges import normalize_label
        from ..numbers import decimal_text

        payload.update({k: raw.get(k) for k in ("currency", "amount")})
        payload["amount"] = decimal_text(payload["amount"])
        # Validate the booking date and explicit currency even for zero evidence.
        try:
            if (
                date.fromisoformat(payload["effective_date"]).isoformat()
                != payload["effective_date"]
            ):
                raise ValueError()
        except (TypeError, ValueError):
            raise LedgerError(
                "VALIDATION_ERROR", "A valid posting date is required."
            ) from None
        if payload["currency"] not in store.catalog.currencies:
            raise LedgerError("REFERENCE_NOT_FOUND", "Select the actual cash currency.")
        label = normalize_label(raw.get("source_label_raw"))
        key = source_key(conn, row, raw, payload)
        previous = conn.execute(
            "SELECT l.*,r.payload_json FROM import_links l JOIN import_rows r USING(row_id) WHERE l.dedup_key=? LIMIT 1",
            (key,),
        ).fetchone()
        if previous:
            if previous["source_hash"] != source_hash(raw):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "The same source ID refers to changed source facts.",
                    "IMPORT_CONFLICT",
                )
            # Mapping has completed its job. Do not resolve committed facts again.
            return (
                kind,
                json.loads(previous["payload_json"]),
                key,
                previous["payload_hash"],
            )
        if Decimal(payload["amount"]) == 0:
            return kind, payload, key, "ZERO_EVIDENCE"
        mapping = conn.execute(
            "SELECT investment_charge_category_id FROM investment_charge_source_mappings WHERE financial_account_id=? AND source_label_normalized=?",
            (payload["account_id"], label),
        ).fetchone()
        if mapping is None:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Assign this account's source label to an Investment Charge category before importing.",
                "UNMAPPED_INVESTMENT_CHARGE",
                field_errors={
                    "source_label_raw": raw["source_label_raw"],
                    "source_label_normalized": label,
                    "account_id": payload["account_id"],
                },
            )
        payload["investment_charge_category_id"] = str(mapping[0])
    with localcontext() as context:
        context.prec = 80
        event = Service(store).normalize(conn, kind, payload)
    # Dedup compares normalized economics, independent of optional empty fields or fee order.
    economic_hash = digest(
        {
            k: event[k]
            for k in ("transaction_type", "effective_date", "memo", "accounts", "data")
        }
    )
    return kind, payload, source_key(conn, row, raw, payload), economic_hash


def source_hash(raw):
    from ..numbers import decimal_text

    ignored = {
        "source_system",
        "source_account_namespace",
        "external_transaction_id",
        "source_component_key",
        "source_row_number",
        "related_source_component_key",
        "related_transaction_id",
    }
    facts = {k: v for k, v in raw.items() if k not in ignored and v not in ("", None)}
    for field in ("amount", "quantity", "price", "buy_amount", "sell_amount"):
        if field in facts:
            facts[field] = decimal_text(facts[field])
    return digest(facts)


def source_key(conn, row, raw, payload):
    external = (raw.get("external_transaction_id") or "").strip()
    system = (raw.get("source_system") or "").strip()
    for field, normalized in (
        ("external_transaction_id", external),
        ("source_system", system),
    ):
        if raw.get(field) and not normalized:
            raise LedgerError(
                "VALIDATION_ERROR",
                f"{field} must not contain only whitespace.",
                field_errors={
                    field: "Use a nonblank source identifier or leave the field empty."
                },
            )
    if external and not system:
        raise LedgerError(
            "VALIDATION_ERROR", "An external transaction ID requires source_system."
        )
    if external:
        # Keep provenance untouched, but use the same normalized identity as resolution.
        # Tag inferred namespaces so external number "1" cannot collide with account ID 1.
        account_id = (
            payload.get("account_id")
            or payload.get("source_account_id")
            or payload.get("destination_account_id")
        )
        explicit_namespace = (raw.get("source_account_namespace") or "").strip()
        external_number = (raw.get("external_account_number") or "").strip()
        if explicit_namespace:
            scope = ["explicit", explicit_namespace]
        elif external_number:
            scope = ["external", account_id, external_number]
        else:
            scope = ["account", account_id]
        key = "source:" + digest(
            [system, scope, external, raw.get("source_component_key") or "event"]
        )
    else:
        file_hash = conn.execute(
            "SELECT file_hash FROM import_batches WHERE batch_id=?", (row["batch_id"],)
        ).fetchone()[0]
        key = "file:" + digest(
            [
                file_hash,
                raw.get("source_row_number") or row["row_number"],
                raw.get("source_component_key") or "event",
            ]
        )
    return key


class Imports:
    def __init__(self, store):
        self.store = store

    def upload(self, filename, text):
        if not isinstance(text, str) or len(text.encode()) > 2_000_000:
            raise LedgerError("VALIDATION_ERROR", "CSV size must not exceed 2 MB.")
        try:
            reader = csv.DictReader(StringIO(text.lstrip("\ufeff")), strict=True)
            if (
                not reader.fieldnames
                or len(set(reader.fieldnames)) != len(reader.fieldnames)
                or not {"transaction_type", "effective_date"} <= set(reader.fieldnames)
            ):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "CSV requires transaction_type and effective_date with unique column names.",
                )
            if "fees" in reader.fieldnames:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Legacy fees columns are not supported. Use independent Investment Charge rows.",
                    "LEGACY_TRADE_FEES",
                )
            rows = list(reader)
        except csv.Error as exc:
            raise LedgerError("VALIDATION_ERROR", "Invalid CSV format.") from exc
        if not rows or len(rows) > 1000:
            raise LedgerError(
                "VALIDATION_ERROR", "Each batch must contain 1 to 1000 rows."
            )
        file_hash = sha256(text.encode()).hexdigest()
        with self.store.transaction() as conn:
            found = conn.execute(
                "SELECT batch_id FROM import_batches WHERE file_hash=?", (file_hash,)
            ).fetchone()
            if found:
                return {"batch_id": str(found[0]), "replayed": True}
            batch = conn.execute(
                "INSERT INTO import_batches(filename,file_hash) VALUES (?,?)",
                (filename[:255], file_hash),
            ).lastrowid
            for number, row in enumerate(rows, 1):
                conn.execute(
                    "INSERT INTO import_rows(batch_id,row_number,raw_json) VALUES (?,?,?)",
                    (batch, number, json.dumps(row, ensure_ascii=False)),
                )
            return {"batch_id": str(batch), "replayed": False}

    def list(self):
        with self.store.read() as conn:
            return {
                "rows": [
                    {**dict(r), "batch_id": str(r["batch_id"])}
                    for r in conn.execute(
                        "SELECT * FROM import_batches ORDER BY batch_id DESC LIMIT 100"
                    )
                ]
            }

    def detail(self, batch):
        with self.store.read() as conn:
            result = conn.execute(
                "SELECT * FROM import_batches WHERE batch_id=?", (batch,)
            ).fetchone()
            if result is None:
                raise LedgerError("REFERENCE_NOT_FOUND", "Import batch not found.")
            rows = []
            for r in conn.execute(
                "SELECT r.*,l.transaction_id FROM import_rows r LEFT JOIN import_links l USING(row_id) WHERE batch_id=? ORDER BY row_number",
                (batch,),
            ):
                item = dict(r)
                for field in (
                    "raw_json",
                    "override_json",
                    "payload_json",
                    "error_json",
                ):
                    item[field.removesuffix("_json")] = (
                        json.loads(item.pop(field)) if item[field] is not None else None
                    )
                item["row_id"] = str(item["row_id"])
                item["batch_id"] = str(item["batch_id"])
                item["transaction_id"] = (
                    str(item["transaction_id"]) if item["transaction_id"] else None
                )
                rows.append(item)
            return {**dict(result), "batch_id": str(batch), "rows": rows}

    def map_row(self, row_id, mapping):
        if set(mapping) - ALLOWED_OVERRIDES or any(
            not isinstance(v, str) for v in mapping.values()
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Only Financial Account, Position Scope, Product and Observable mappings can be changed.",
            )
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM import_rows WHERE row_id=?", (row_id,)
            ).fetchone()
            if row is None:
                raise LedgerError("REFERENCE_NOT_FOUND", "Import row not found.")
            if row["status"] in ("COMMITTED", "DUPLICATE"):
                raise LedgerError(
                    "VALIDATION_ERROR", "Committed or linked rows cannot be changed."
                )
            conn.execute(
                "UPDATE import_rows SET override_json=?,status='STAGED',payload_json=NULL,error_json=NULL WHERE row_id=?",
                (json.dumps(mapping), row_id),
            )

    def _ordered(self, conn, batch):
        rows = conn.execute(
            "SELECT * FROM import_rows WHERE batch_id=? ORDER BY row_number", (batch,)
        ).fetchall()
        return sorted(
            rows,
            key=lambda r: (
                json.loads(r["raw_json"]).get("effective_date") or "",
                r["row_number"],
            ),
        )

    def _groups(self, conn, batch):
        groups = {}
        for row in self._ordered(conn, batch):
            raw = json.loads(row["raw_json"])
            # Explicit source record boundaries exist only in staging.
            key = (
                (
                    raw.get("source_system"),
                    raw.get("source_account_namespace")
                    or raw.get("external_account_number")
                    or raw.get("account_code")
                    or raw.get("source_account_code")
                    or raw.get("destination_account_code"),
                    raw.get("source_row_number"),
                )
                if raw.get("source_row_number")
                else ("row", row["row_id"])
            )
            groups.setdefault(key, []).append(row)
        return list(groups.values())

    def _commit_group(self, store, conn, rows):
        prepared, new_events, relationships = [], [], []
        client_ids = {}
        for row in rows:
            if conn.execute(
                "SELECT 1 FROM import_links WHERE row_id=?", (row["row_id"],)
            ).fetchone():
                continue
            raw = {**json.loads(row["raw_json"]), **json.loads(row["override_json"])}
            kind, payload, key, fingerprint = normalize(store, conn, row)
            prior = conn.execute(
                "SELECT * FROM import_links WHERE dedup_key=? LIMIT 1", (key,)
            ).fetchone()
            if prior and prior["payload_hash"] != fingerprint:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "The same source ID refers to different content.",
                    "IMPORT_CONFLICT",
                )
            if any(p[3] == key for p in prepared):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Source components must have distinct stable identities.",
                    "IMPORT_CONFLICT",
                )
            client = str(row["row_id"])
            component = raw.get("source_component_key") or "event"
            if component in client_ids and len(rows) > 1:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "A split source record requires distinct source_component_key values.",
                )
            client_ids[component] = (client, prior["transaction_id"] if prior else None)
            prepared.append((row, kind, payload, key, fingerprint, prior, raw))
            if not prior and fingerprint != "ZERO_EVIDENCE":
                new_events.append(
                    {
                        "client_event_id": client,
                        "transaction_type": kind,
                        "payload": payload,
                    }
                )
        for row, kind, payload, key, fingerprint, prior, raw in prepared:
            if prior or fingerprint == "ZERO_EVIDENCE" or kind != "INVESTMENT_CHARGE":
                continue
            rel = {"subject_client_event_id": str(row["row_id"])}
            target = raw.get("related_source_component_key")
            existing = raw.get("related_transaction_id")
            if target and existing:
                raise LedgerError(
                    "VALIDATION_ERROR", "Specify only one related transaction identity."
                )
            if target:
                if target not in client_ids:
                    raise LedgerError(
                        "REFERENCE_NOT_FOUND",
                        "Related source component is missing from this request.",
                    )
                client, saved = client_ids[target]
                rel["object_transaction_id" if saved else "object_client_event_id"] = (
                    str(saved) if saved else client
                )
            elif existing:
                rel["object_transaction_id"] = existing
            else:
                continue
            relationships.append(rel)
        created = {}
        if new_events:
            result = Service(store).submit_many(
                new_events,
                relationships,
                "import-request:" + digest([p[3] for p in prepared]),
                connection=conn,
            )
            created = {
                r["client_event_id"]: int(r["transaction_id"]) for r in result["events"]
            }
        results = []
        from ..application.service import serialize_lines
        from ..accounting.journal import stored_lines
        from ..position.ledger import detail as position_detail

        for row, kind, payload, key, fingerprint, prior, raw in prepared:
            tid = prior["transaction_id"] if prior else created.get(str(row["row_id"]))
            if fingerprint == "ZERO_EVIDENCE":
                preview = {"input": payload, "journal": [], "allocations": []}
                status, note = "ZERO_EVIDENCE", None
            else:
                preview = {
                    "input": payload,
                    "journal": serialize_lines(stored_lines(conn, tid)),
                    "allocations": position_detail(conn, tid)["allocations"],
                }
                status = "DUPLICATE" if prior else "COMMITTED"
                note = None
                if prior:
                    note = {
                        "code": "DUPLICATE_PREVIEW",
                        "message": "This source is already recorded; confirmation links the original transaction.",
                        "transaction_id": str(tid),
                    }
                elif conn.execute(
                    "SELECT 1 FROM import_links WHERE payload_hash=? AND dedup_key<>?",
                    (fingerprint, key),
                ).fetchone():
                    note = {
                        "code": "POTENTIAL_DUPLICATE",
                        "message": "Another source has identical economic content. Please verify.",
                    }
            # A READY confirmation must reproduce the preview, including cash basis and allocations.
            if (
                row["status"] == "READY"
                and row["payload_json"]
                and json.loads(row["payload_json"]) != preview
            ):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "The source mapping or economic preview changed. Preview again before confirming.",
                    "PREVIEW_STALE",
                )
            conn.execute(
                "UPDATE import_rows SET status=?,payload_json=?,error_json=NULL WHERE row_id=?",
                (status, json.dumps(payload), row["row_id"]),
            )
            if tid is not None:
                conn.execute(
                    "INSERT INTO import_links VALUES (?,?,?,?,?)",
                    (row["row_id"], tid, key, fingerprint, source_hash(raw)),
                )
            results.append(
                (
                    row["row_id"],
                    "ZERO_EVIDENCE" if tid is None else "READY",
                    json.dumps(preview),
                    json.dumps(note) if note else None,
                    row["override_json"],
                )
            )
        return results

    def preview(self, batch):
        # Use a consistent temporary SQLite snapshot. Each source request is atomic.
        with TemporaryDirectory(prefix="holdings-preview-") as directory:
            path = Path(directory) / "preview.sqlite3"
            with self.store.read() as source:
                target = sqlite3.connect(path)
                try:
                    source.backup(target)
                finally:
                    target.close()
            temporary = Store(path, self.store.catalog)
            results = []
            with temporary.read() as conn:
                groups = self._groups(conn, batch)
            if not groups:
                raise LedgerError("REFERENCE_NOT_FOUND", "Import batch not found.")
            for group in groups:
                rows = [
                    dict(r)
                    for r in group
                    if r["status"] not in ("COMMITTED", "DUPLICATE")
                ]
                if not rows:
                    continue
                # A new preview deliberately replaces the old preview after revalidation.
                for row in rows:
                    row["status"] = "STAGED"
                try:
                    with temporary.transaction() as conn:
                        results.extend(self._commit_group(temporary, conn, rows))
                except (LedgerError, CatalogError) as exc:
                    error = (
                        exc.as_dict()
                        if isinstance(exc, LedgerError)
                        else {"code": "REFERENCE_NOT_FOUND", "message": str(exc)}
                    )
                    status = (
                        "UNMAPPED"
                        if getattr(exc, "reason", None) == "UNMAPPED_INVESTMENT_CHARGE"
                        else "ERROR"
                    )
                    results.extend(
                        (
                            r["row_id"],
                            status,
                            None,
                            json.dumps(error),
                            r["override_json"],
                        )
                        for r in rows
                    )
            with self.store.transaction() as conn:
                for row_id, status, payload, error, override in results:
                    conn.execute(
                        "UPDATE import_rows SET status=?,payload_json=?,error_json=? WHERE row_id=? AND override_json=? AND status NOT IN ('COMMITTED','DUPLICATE')",
                        (status, payload, error, row_id, override),
                    )
        return self.detail(batch)

    def canonicalize(self, batch):
        with self.store.read() as conn:
            groups = self._groups(conn, batch)
        if not groups:
            raise LedgerError("REFERENCE_NOT_FOUND", "Import batch not found.")
        for group in groups:
            pending = [
                r for r in group if r["status"] not in ("COMMITTED", "DUPLICATE")
            ]
            if not pending or any(
                r["status"] not in ("READY", "ZERO_EVIDENCE") for r in pending
            ):
                continue
            ids = [r["row_id"] for r in pending]
            try:
                with self.store.transaction() as conn:
                    rows = [
                        conn.execute(
                            "SELECT * FROM import_rows WHERE row_id=?", (key,)
                        ).fetchone()
                        for key in ids
                    ]
                    if any(r["status"] not in ("READY", "ZERO_EVIDENCE") for r in rows):
                        continue
                    self._commit_group(self.store, conn, rows)
            except (LedgerError, CatalogError) as exc:
                error = (
                    exc.as_dict()
                    if isinstance(exc, LedgerError)
                    else {"code": "REFERENCE_NOT_FOUND", "message": str(exc)}
                )
                with self.store.transaction() as conn:
                    for row_id in ids:
                        conn.execute(
                            "UPDATE import_rows SET status='ERROR',error_json=? WHERE row_id=? AND status NOT IN ('COMMITTED','DUPLICATE')",
                            (json.dumps(error), row_id),
                        )
        return self.detail(batch)
