from datetime import date
from decimal import localcontext
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

KINDS = {"TRADE", "CASH_TRANSFER", "FX_CONVERSION", "DIVIDEND_RECEIPT"}
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
    if kind not in KINDS:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Only TRADE, CASH_TRANSFER, FX_CONVERSION and DIVIDEND_RECEIPT are supported.",
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
        try:
            fees = json.loads(raw.get("fees") or "[]")
        except (ValueError, TypeError):
            raise LedgerError(
                "VALIDATION_ERROR", "Fees must be a JSON array."
            ) from None
        if not isinstance(fees, list) or any(
            not isinstance(f, dict)
            or set(f) != {"fee_type", "amount"}
            or not isinstance(f["fee_type"], str)
            or not isinstance(f["amount"], str)
            for f in fees
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Fees require string fee_type and decimal-string amount.",
            )
        payload.update(
            product_id=product,
            listing_id=listing,
            side=raw.get("side", "").upper(),
            quantity=raw.get("quantity"),
            price=raw.get("price"),
            fees=fees,
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
        key = "source:" + digest([system, scope, external])
    else:
        file_hash = conn.execute(
            "SELECT file_hash FROM import_batches WHERE batch_id=?", (row["batch_id"],)
        ).fetchone()[0]
        key = "file:" + digest([file_hash, row["row_number"], economic_hash])
    return kind, payload, key, economic_hash


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

    def _commit_row(self, store, conn, row):
        if conn.execute(
            "SELECT 1 FROM import_links WHERE row_id=?", (row["row_id"],)
        ).fetchone():
            return
        kind, payload, key, fingerprint = normalize(store, conn, row)
        previous = conn.execute(
            "SELECT * FROM import_links WHERE dedup_key=? LIMIT 1", (key,)
        ).fetchone()
        if previous:
            if previous["payload_hash"] != fingerprint:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "The same source ID refers to different content.",
                    "IMPORT_CONFLICT",
                )
            tid = previous["transaction_id"]
            status = "DUPLICATE"
        else:
            result = Service(store).submit(
                kind, payload, "import:" + key, connection=conn
            )
            tid = int(result["transaction_id"])
            status = "COMMITTED"
        # Row status and link share the command transaction. Never link a partial event.
        conn.execute(
            "UPDATE import_rows SET status=?,payload_json=?,error_json=NULL WHERE row_id=?",
            (status, json.dumps(payload), row["row_id"]),
        )
        conn.execute(
            "INSERT INTO import_links VALUES (?,?,?,?)",
            (row["row_id"], tid, key, fingerprint),
        )

    def preview(self, batch):
        # A SQLite snapshot permits sequential preview with the same commands; no live event or ID is consumed.
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
                rows = self._ordered(conn, batch)
            if not rows:
                raise LedgerError("REFERENCE_NOT_FOUND", "Import batch not found.")
            for row in rows:
                if row["status"] in ("COMMITTED", "DUPLICATE"):
                    continue
                try:
                    with temporary.transaction() as conn:
                        self._commit_row(temporary, conn, row)
                        saved = conn.execute(
                            "SELECT status,payload_json FROM import_rows WHERE row_id=?",
                            (row["row_id"],),
                        ).fetchone()
                        linked = conn.execute(
                            "SELECT transaction_id FROM import_links WHERE row_id=?",
                            (row["row_id"],),
                        ).fetchone()[0]
                    preview_detail = Service(temporary).detail(linked)
                    preview_payload = json.dumps(
                        {
                            "input": json.loads(saved["payload_json"]),
                            "journal": preview_detail["journal"],
                            "allocations": preview_detail["allocations"],
                        }
                    )
                    note = None
                    with temporary.read() as conn:
                        link = conn.execute(
                            "SELECT * FROM import_links WHERE row_id=?",
                            (row["row_id"],),
                        ).fetchone()
                        if saved["status"] == "DUPLICATE":
                            note = {
                                "code": "DUPLICATE_PREVIEW",
                                "message": "A record with the same source ID exists; confirmation will link the original transaction.",
                                "transaction_id": str(link["transaction_id"]),
                            }
                        elif conn.execute(
                            "SELECT 1 FROM import_links WHERE payload_hash=? AND dedup_key<>?",
                            (link["payload_hash"], link["dedup_key"]),
                        ).fetchone():
                            note = {
                                "code": "POTENTIAL_DUPLICATE",
                                "message": "Another source has identical economic content; this row will create a new transaction. Please verify.",
                            }
                    results.append(
                        (
                            row["row_id"],
                            "READY",
                            preview_payload,
                            json.dumps(note) if note else None,
                            row["override_json"],
                        )
                    )
                except (LedgerError, CatalogError) as exc:
                    error = (
                        exc.as_dict()
                        if isinstance(exc, LedgerError)
                        else {"code": "REFERENCE_NOT_FOUND", "message": str(exc)}
                    )
                    results.append(
                        (
                            row["row_id"],
                            "ERROR",
                            None,
                            json.dumps(error),
                            row["override_json"],
                        )
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
            rows = self._ordered(conn, batch)
        if not rows:
            raise LedgerError("REFERENCE_NOT_FOUND", "Import batch not found.")
        for snapshot in rows:
            # Confirmation applies to rows previewed READY only; each is revalidated under the writer lock.
            if snapshot["status"] != "READY":
                continue
            try:
                with self.store.transaction() as conn:
                    row = conn.execute(
                        "SELECT * FROM import_rows WHERE row_id=?",
                        (snapshot["row_id"],),
                    ).fetchone()
                    if row["status"] != "READY":
                        continue
                    self._commit_row(self.store, conn, row)
            except (LedgerError, CatalogError) as exc:
                error = (
                    exc.as_dict()
                    if isinstance(exc, LedgerError)
                    else {"code": "REFERENCE_NOT_FOUND", "message": str(exc)}
                )
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE import_rows SET status='ERROR',error_json=? WHERE row_id=? AND status NOT IN ('COMMITTED','DUPLICATE')",
                        (json.dumps(error), snapshot["row_id"]),
                    )
        return self.detail(batch)
