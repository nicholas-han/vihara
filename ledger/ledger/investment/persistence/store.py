"""Dedicated persistent database; writes share one explicit Unit of Work."""

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import re
import sqlite3

from ledger.investment.accounting import ACCOUNT_DEFINITIONS
from instrument_manager.holding_catalog import CatalogError
from ..errors import LedgerError
from ..numbers import decimal_text

APPLICATION = "vihara.portfolio-holdings"
VERSION = 6
IMMUTABLE_TABLES = (
    "currencies",
    "owners",
    "ledger_account_definitions",
    "transactions",
    "transaction_relationships",
    "reference_catalog_pins",
    "book_fx_observations",
    "book_fx_evidence",
)
CASH_TABLES = (
    "transaction_accounts",
    "cash_transfers",
    "positions",
    "journal_entries",
    "journal_lines",
    "command_receipts",
)


def _execute_migration(conn, text):
    statement = ""
    for line in text.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("Incomplete migration")


class Store:
    def __init__(self, path, catalog):
        self.path = Path(path).expanduser().resolve()
        self.catalog = catalog

    def _connect(self, *, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw"),
            uri=True,
            isolation_level=None,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _validate(self, conn, *, allow_upgrade=False):
        try:
            marker = conn.execute(
                "SELECT value FROM holdings_metadata WHERE key='application'"
            ).fetchone()
            version = conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
        except sqlite3.DatabaseError:
            raise LedgerError(
                "INTEGRITY_ERROR",
                "This is not a Portfolio Holdings database. Use a separate new database.",
            ) from None
        if (
            not marker
            or marker[0] != APPLICATION
            or (
                version not in range(1, VERSION + 1)
                or (not allow_upgrade and version != VERSION)
            )
        ):
            raise LedgerError(
                "INTEGRITY_ERROR", "Database type or version does not match."
            )
        for pin in conn.execute("SELECT * FROM reference_catalog_pins"):
            try:
                fingerprint = self.catalog.fingerprint(
                    pin["target_type"], pin["target_id"]
                )
            except CatalogError as exc:
                raise LedgerError("INTEGRITY_ERROR", str(exc)) from exc
            if fingerprint != pin["economics_hash"]:
                raise LedgerError(
                    "INTEGRITY_ERROR",
                    "A referenced Instrument economic definition has changed.",
                )
        for row in conn.execute("SELECT * FROM currencies"):
            if (
                self.catalog.currencies.get(row["currency_code"])
                != row["observable_id"]
            ):
                raise LedgerError(
                    "INTEGRITY_ERROR",
                    "Currency and Instrument reference data mappings are inconsistent.",
                )

    def initialize(self):
        conn = self._connect(create=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if tables:
                self._validate(conn, allow_upgrade=True)
                self._migrate(conn)
                conn.commit()
                return
            if "HKD" not in self.catalog.currencies:
                raise LedgerError(
                    "REFERENCE_NOT_FOUND", "Reference data must include HKD."
                )
            _execute_migration(
                conn, Path(__file__).with_name("001_foundation.sql").read_text()
            )
            conn.executemany(
                "INSERT INTO currencies VALUES (?,?)", self.catalog.currencies.items()
            )
            conn.execute("INSERT INTO owners VALUES (1,'SELF','Self')")
            conn.execute("INSERT INTO accounting_config VALUES (1,'HKD')")
            conn.executemany(
                "INSERT INTO ledger_account_definitions VALUES (?,?,?)",
                ACCOUNT_DEFINITIONS,
            )
            for oid in self.catalog.currencies.values():
                conn.execute(
                    "INSERT INTO reference_catalog_pins VALUES ('OBSERVABLE',?,?)",
                    (oid, self.catalog.fingerprint("OBSERVABLE", oid)),
                )
            for table in IMMUTABLE_TABLES:
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END"
                    )
            conn.execute("INSERT INTO schema_migrations VALUES (1)")
            self._migrate(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate(self, conn):
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
            0
        ]
        if version < 2:
            _execute_migration(
                conn, Path(__file__).with_name("002_cash.sql").read_text()
            )
            for table in CASH_TABLES:
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END"
                    )
            conn.execute("INSERT INTO schema_migrations VALUES (2)")

        if version < 3:
            _execute_migration(
                conn, Path(__file__).with_name("003_trades.sql").read_text()
            )
            for table in (
                "trades",
                "trade_fees",
                "position_entries",
                "position_lines",
                "position_cost_basis_lots",
                "position_cost_basis_allocations",
            ):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END"
                    )
            conn.execute("INSERT INTO schema_migrations VALUES (3)")

        if version < 4:
            _execute_migration(
                conn, Path(__file__).with_name("004_cash_events.sql").read_text()
            )
            for table in ("fx_conversions", "dividend_receipts"):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END"
                    )
            conn.execute("INSERT INTO schema_migrations VALUES (4)")

        if version < 5:
            _execute_migration(
                conn, Path(__file__).with_name("005_market.sql").read_text()
            )
            for table in ("market_prices", "market_fx"):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Observations are immutable'); END"
                    )
            conn.execute("INSERT INTO schema_migrations VALUES (5)")

        if version < 6:
            _execute_migration(
                conn, Path(__file__).with_name("006_imports.sql").read_text()
            )
            conn.execute("INSERT INTO schema_migrations VALUES (6)")

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate(conn)
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self):
        conn = self._connect()
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            self._validate(conn)
            yield conn
        finally:
            conn.rollback()
            conn.close()

    def configuration(self):
        with self.read() as conn:
            return {
                "functional_currency": conn.execute(
                    "SELECT functional_currency FROM accounting_config"
                ).fetchone()[0],
                "owner": "SELF",
                "transaction_count": conn.execute(
                    "SELECT COUNT(*) FROM transactions"
                ).fetchone()[0],
                "currencies": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM currencies ORDER BY currency_code"
                    )
                ],
            }

    def accounts(self):
        with self.read() as conn:
            return [
                {**dict(r), "financial_account_id": str(r["financial_account_id"])}
                for r in conn.execute(
                    "SELECT * FROM financial_accounts ORDER BY financial_account_id"
                )
            ]

    def create_account(self, code, name):
        code, name = code.strip(), name.strip()
        if (
            not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,63}", code)
            or not name
            or len(name) > 200
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Account code must use uppercase letters, digits, underscores or hyphens; display name is required.",
            )
        try:
            with self.transaction() as conn:
                account_id = conn.execute(
                    "INSERT INTO financial_accounts(account_code,display_name) VALUES (?,?)",
                    (code, name),
                ).lastrowid
        except sqlite3.IntegrityError:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Financial Account code already exists.",
                "DUPLICATE_ACCOUNT",
            ) from None
        return {
            "financial_account_id": str(account_id),
            "account_code": code,
            "display_name": name,
        }

    def rename_account(self, account_id, name):
        name = name.strip()
        if not name or len(name) > 200:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Financial Account name is required and must not exceed 200 characters.",
            )
        with self.transaction() as conn:
            result = conn.execute(
                "UPDATE financial_accounts SET display_name=? WHERE financial_account_id=?",
                (name, account_id),
            )
            if result.rowcount != 1:
                raise LedgerError("REFERENCE_NOT_FOUND", "Financial Account not found.")

    def add_book_fx(self, base, effective_date, rate, source):
        return self.import_book_fx(
            [
                {
                    "base_currency": base,
                    "effective_date": effective_date,
                    "rate": rate,
                    "source": source,
                }
            ]
        )[0]

    def import_book_fx(self, rows):
        """Operator input batch is atomic; revisions never UPDATE observations."""
        ids = []
        with self.transaction() as conn:
            functional = conn.execute(
                "SELECT functional_currency FROM accounting_config"
            ).fetchone()[0]
            currencies = {
                r[0] for r in conn.execute("SELECT currency_code FROM currencies")
            }
            for row in rows:
                base = row["base_currency"]
                day = row["effective_date"]
                if type(day) is not date:
                    raise LedgerError(
                        "VALIDATION_ERROR", "FX effective date must be a date."
                    )
                rate = decimal_text(row["rate"], positive=True)
                source = row["source"].strip()
                if base not in currencies or base == functional or not source:
                    raise LedgerError(
                        "VALIDATION_ERROR",
                        "FX requires a registered foreign currency and a source.",
                    )
                revision = conn.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM book_fx_observations "
                    "WHERE base_currency=? AND quote_currency=? AND effective_date=?",
                    (base, functional, day.isoformat()),
                ).fetchone()[0]
                ids.append(
                    str(
                        conn.execute(
                            "INSERT INTO book_fx_observations "
                            "(base_currency,quote_currency,effective_date,revision,rate,source) VALUES (?,?,?,?,?,?)",
                            (base, functional, day.isoformat(), revision, rate, source),
                        ).lastrowid
                    )
                )
        return ids

    def book_fx(self, base, effective_date, *, observation_id=None):
        with self.read() as conn:
            functional = conn.execute(
                "SELECT functional_currency FROM accounting_config"
            ).fetchone()[0]
            if base == functional:
                if observation_id is not None:
                    raise LedgerError(
                        "VALIDATION_ERROR",
                        "Functional Currency does not use external FX records.",
                    )
                return {
                    "rate": "1",
                    "observation_id": None,
                    "effective_date": effective_date.isoformat(),
                }
            params = [base, functional, effective_date.isoformat()]
            sql = "SELECT * FROM book_fx_observations WHERE base_currency=? AND quote_currency=? AND effective_date=?"
            if observation_id is not None:
                sql += " AND observation_id=?"
                params.append(observation_id)
            row = conn.execute(
                sql + " ORDER BY revision DESC LIMIT 1", params
            ).fetchone()
            if row is None:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    f"Missing Book FX for {base}→{functional} on {effective_date}.",
                    "MISSING_BOOK_FX",
                )
            return {**dict(row), "observation_id": str(row["observation_id"])}
