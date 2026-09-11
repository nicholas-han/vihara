"""Charge reference data and mutable, deterministic ingestion configuration."""

import sqlite3
import unicodedata
from ..errors import LedgerError
from .references import identity

ACCOUNTS = {"INVESTMENT_FEES", "INVESTMENT_TAXES", "INVESTMENT_FINANCING_INTEREST"}
SEEDS = (
    ("BROKER_DEALER_FEE", "Broker-dealer fee", "INVESTMENT_FEES"),
    ("EXCHANGE_FEE", "Exchange fee", "INVESTMENT_FEES"),
    ("SETTLEMENT_FEE", "Settlement fee", "INVESTMENT_FEES"),
    ("CUSTODY_FEE", "Custody fee", "INVESTMENT_FEES"),
    ("REGULATORY_FEE", "Regulatory fee", "INVESTMENT_FEES"),
    ("STAMP_TAX", "Stamp tax", "INVESTMENT_TAXES"),
    ("CONSUMPTION_TAX", "Consumption tax", "INVESTMENT_TAXES"),
    ("CAPITAL_GAIN_TAX", "Capital gain tax", "INVESTMENT_TAXES"),
    ("DIVIDEND_WITHHOLDING_TAX", "Dividend withholding tax", "INVESTMENT_TAXES"),
    ("FINANCING_INTEREST", "Financing interest", "INVESTMENT_FINANCING_INTEREST"),
)


def seed(conn):
    for code, name, ledger in SEEDS:
        row = conn.execute(
            "SELECT * FROM investment_charge_categories WHERE code=?", (code,)
        ).fetchone()
        if row and row["ledger_account_code"] != ledger:
            raise LedgerError(
                "INTEGRITY_ERROR",
                "Initial charge category conflicts with its accounting meaning.",
            )
        if not row:
            conn.execute(
                "INSERT INTO investment_charge_categories(code,display_name,ledger_account_code) VALUES (?,?,?)",
                (code, name, ledger),
            )


def nonblank(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{name} requires nonblank text of at most 2000 characters.",
        )
    return value.strip()


def normalize_label(value):
    value = nonblank(value, "Source label")
    return " ".join(unicodedata.normalize("NFKC", value).split()).translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def category(conn, value):
    row = conn.execute(
        "SELECT * FROM investment_charge_categories WHERE id=?",
        (identity(value, "investment_charge_category_id"),),
    ).fetchone()
    if not row:
        raise LedgerError(
            "REFERENCE_NOT_FOUND", "Investment Charge category not found."
        )
    return dict(row)


def serialize(row):
    return {
        k: str(v) if (k == "id" or k.endswith("_id")) and v is not None else v
        for k, v in dict(row).items()
    }


class ChargeReferences:
    def __init__(self, store):
        self.store = store

    def categories(self):
        with self.store.read() as conn:
            return [
                serialize(r)
                for r in conn.execute(
                    "SELECT * FROM investment_charge_categories ORDER BY id"
                )
            ]

    def create_category(self, code, display_name, ledger_account_code):
        code, display_name = nonblank(code, "Code"), nonblank(
            display_name, "Display name"
        )
        if ledger_account_code not in ACCOUNTS:
            raise LedgerError(
                "VALIDATION_ERROR", "Select an investment expense ledger account."
            )
        try:
            with self.store.transaction() as conn:
                key = conn.execute(
                    "INSERT INTO investment_charge_categories(code,display_name,ledger_account_code) VALUES (?,?,?)",
                    (code, display_name, ledger_account_code),
                ).lastrowid
                return serialize(category(conn, str(key)))
        except sqlite3.IntegrityError as exc:
            raise LedgerError(
                "VALIDATION_ERROR", "Category code already exists."
            ) from exc

    def rename_category(self, key, display_name):
        with self.store.transaction() as conn:
            category(conn, str(key))
            conn.execute(
                "UPDATE investment_charge_categories SET display_name=? WHERE id=?",
                (nonblank(display_name, "Display name"), key),
            )
            return serialize(category(conn, str(key)))

    def mappings(self, financial_account_id=None, source_label_raw=None):
        with self.store.read() as conn:
            conditions, args = [], []
            if financial_account_id is not None:
                conditions.append("financial_account_id=?")
                args.append(financial_account_id)
            if source_label_raw is not None:
                conditions.append("source_label_normalized=?")
                args.append(normalize_label(source_label_raw))
            sql = (
                "SELECT * FROM investment_charge_source_mappings"
                + (" WHERE " + " AND ".join(conditions) if conditions else "")
                + " ORDER BY id"
            )
            return [serialize(r) for r in conn.execute(sql, args)]

    def save_mapping(
        self,
        financial_account_id,
        source_label_raw,
        investment_charge_category_id,
        description=None,
        *,
        key=None,
    ):
        from ..application.trades import account

        normalized = normalize_label(source_label_raw)
        if description is not None and (
            not isinstance(description, str) or len(description) > 2000
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Description must be text of at most 2000 characters.",
            )
        try:
            with self.store.transaction() as conn:
                args = (
                    account(conn, financial_account_id),
                    source_label_raw,
                    normalized,
                    category(conn, investment_charge_category_id)["id"],
                    description,
                )
                if key is None:
                    key = conn.execute(
                        "INSERT INTO investment_charge_source_mappings(financial_account_id,source_label_raw,source_label_normalized,investment_charge_category_id,description) VALUES (?,?,?,?,?)",
                        args,
                    ).lastrowid
                elif (
                    conn.execute(
                        "UPDATE investment_charge_source_mappings SET financial_account_id=?,source_label_raw=?,source_label_normalized=?,investment_charge_category_id=?,description=? WHERE id=?",
                        (*args, key),
                    ).rowcount
                    != 1
                ):
                    raise LedgerError(
                        "REFERENCE_NOT_FOUND", "Source mapping not found."
                    )
                return serialize(
                    conn.execute(
                        "SELECT * FROM investment_charge_source_mappings WHERE id=?",
                        (key,),
                    ).fetchone()
                )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(
                "VALIDATION_ERROR",
                "A mapping already exists for this account and normalized source label.",
                "DUPLICATE_SOURCE_MAPPING",
            ) from exc

    def delete_mapping(self, key):
        with self.store.transaction() as conn:
            if (
                conn.execute(
                    "DELETE FROM investment_charge_source_mappings WHERE id=?", (key,)
                ).rowcount
                != 1
            ):
                raise LedgerError("REFERENCE_NOT_FOUND", "Source mapping not found.")
