"""Dedicated persistent database; writes share one explicit Unit of Work."""

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sqlite3

from ledger.investment.accounting import ACCOUNT_DEFINITIONS
from instrument_manager.holding_catalog import CatalogError
from ..errors import LedgerError
from ..numbers import decimal_text
from . import references

APPLICATION = "vihara.portfolio-holdings"
VERSION = 8
POLICY = "PRINCIPAL_ONLY_V1"
IMMUTABLE_TABLES = (
    "external_account_references",
    "currencies",
    "owners",
    "ledger_account_definitions",
    "transactions",
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
    "command_receipt_transactions",
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
        if not marker or marker[0] != APPLICATION or (version != VERSION):
            raise LedgerError(
                "INTEGRITY_ERROR",
                "Database type or version does not match. Investment Charge v8 requires an explicitly prepared database; existing databases are not automatically migrated.",
            )
        policy = conn.execute(
            "SELECT value FROM holdings_metadata WHERE key='investment_charge_policy'"
        ).fetchone()
        if not policy or policy[0] != POLICY:
            raise LedgerError(
                "INTEGRITY_ERROR",
                "Investment Charge policy marker is missing or incompatible.",
            )
        for table, required in {
            "financial_accounts": {"institution_type", "country_or_region"},
            "position_scopes": {
                "position_scope_id",
                "financial_account_id",
                "tax_scheme_id",
            },
            "tax_schemes": {"tax_scheme_id", "scheme_code"},
            "external_account_references": {
                "external_account_number",
                "financial_account_id",
            },
            "investment_charges": {
                "investment_charge_category_id",
                "currency",
                "amount",
            },
            "investment_charge_categories": {"id", "code", "ledger_account_code"},
            "investment_charge_source_mappings": {
                "id",
                "financial_account_id",
                "source_label_raw",
                "source_label_normalized",
                "investment_charge_category_id",
            },
            "command_receipt_transactions": {
                "request_key",
                "ordinal",
                "client_event_id",
                "transaction_id",
            },
            "command_receipts": {"request_key", "payload_hash"},
            "trades": {"position_scope_id"},
            "position_lines": {"position_scope_id"},
            "position_cost_basis_lots": {"position_scope_id"},
        }.items():
            columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not required <= columns or (
                table in {"position_lines", "position_cost_basis_lots"}
                and "financial_account_id" in columns
            ):
                raise LedgerError(
                    "INTEGRITY_ERROR",
                    "Investment Ledger schema is incomplete or incompatible.",
                )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_fees'"
        ).fetchone():
            raise LedgerError(
                "INTEGRITY_ERROR",
                "Legacy TradeFee table cannot be used under the principal-only policy.",
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
                self._validate(conn)
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
        if version < 7:
            conn.execute("INSERT INTO schema_migrations VALUES (7)")
        if version < 8:
            _execute_migration(
                conn, Path(__file__).with_name("008_investment_charges.sql").read_text()
            )
            from .charges import seed

            seed(conn)
            conn.execute(
                "INSERT INTO holdings_metadata VALUES ('investment_charge_policy',?)",
                (POLICY,),
            )
            conn.execute("INSERT INTO schema_migrations VALUES (8)")

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

    def create_account(
        self,
        code,
        name,
        institution_type,
        country_or_region=None,
        position_scopes=None,
        external_account_numbers=None,
    ):
        try:
            with self.transaction() as conn:
                return references.create_account(
                    conn,
                    code,
                    name,
                    institution_type,
                    country_or_region,
                    position_scopes,
                    external_account_numbers,
                )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Duplicate or invalid Financial Account reference data.",
            ) from exc

    def position_scopes(self, account_id):
        with self.read() as conn:
            return references.scopes(
                conn, references.identity(str(account_id), "financial_account_id")
            )

    def external_account_references(self, account_id):
        with self.read() as conn:
            return references.external_references(
                conn, references.identity(str(account_id), "financial_account_id")
            )

    def import_references(self, document):
        try:
            with self.transaction() as conn:
                return references.bootstrap(conn, document)
        except (sqlite3.IntegrityError, TypeError) as exc:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Conflicting or incomplete reference data; nothing was imported.",
            ) from exc

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
