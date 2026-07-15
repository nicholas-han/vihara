"""SQLite-backed records store for portfolio records v2."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

from .config import PortfolioRecordsSettings
from .imports import TradeImportRow
from .models import (
    Account,
    CashCheckpoint,
    Cashflow,
    CashflowType,
    CostMethod,
    DividendAnnual,
    DividendPayment,
    FinancialAnnual,
    FxRate,
    ImportBatch,
    InstrumentSummary,
    PositionSnapshot,
    SnapshotKind,
    Trade,
    TradeSide,
)


def _text(value: Decimal | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


class SQLiteRecordsStore:
    """RecordsStore implementation over one or more local SQLite databases.

    Connections are cached per database path and shared across FastAPI's
    request threadpool, so every statement runs under one lock.
    """

    def __init__(self, settings: PortfolioRecordsSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._connections: dict[Path, sqlite3.Connection] = {}

    def close(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()

    def _conn(self, path: Path) -> sqlite3.Connection:
        conn = self._connections.get(path)
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._connections[path] = conn
        return conn

    def _query(self, path: Path, sql: str, params: list[object] | None = None) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn(path).execute(sql, params or []).fetchall()

    @property
    def _portfolio_db(self) -> Path:
        return self.settings.portfolio_db_path

    @property
    def _instrument_db(self) -> Path:
        return self.settings.instrument_db_path or self.settings.portfolio_db_path

    @property
    def _financials_db(self) -> Path:
        return self.settings.financials_db_path or self.settings.portfolio_db_path

    def list_accounts(self) -> list[Account]:
        rows = self._query(
            self._portfolio_db,
            "select account_id, name, currency from accounts order by account_id",
        )
        return [Account(row["account_id"], row["name"], row["currency"]) for row in rows]

    def upsert_accounts(self, accounts: list[Account]) -> None:
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                conn.executemany(
                    "insert or ignore into accounts(account_id, name, currency) values (?, ?, ?)",
                    [(a.account_id, a.name, a.currency) for a in accounts],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def upsert_snapshots(self, snapshots: list[PositionSnapshot]) -> int:
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                conn.executemany(
                    """
                    insert or replace into position_snapshots(
                        account_id, instrument_id, as_of, quantity, average_cost,
                        currency, cost_method, kind
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            s.account_id,
                            s.instrument_id,
                            s.as_of.isoformat(),
                            _text(s.quantity),
                            _text(s.average_cost),
                            s.currency,
                            s.cost_method.value if s.cost_method else None,
                            s.kind.value,
                        )
                        for s in snapshots
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return len(snapshots)

    def get_instruments(self, instrument_ids: list[str]) -> dict[str, InstrumentSummary]:
        if not instrument_ids:
            return {}
        placeholders = ",".join("?" for _ in instrument_ids)
        rows = self._query(
            self._instrument_db,
            f"""
            select instrument_id, symbol, name, market, currency, status
            from instruments
            where instrument_id in ({placeholders})
            """,
            list(instrument_ids),
        )
        return {
            row["instrument_id"]: InstrumentSummary(
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                name=row["name"],
                market=row["market"],
                currency=row["currency"],
                status=row["status"],
            )
            for row in rows
        }

    def latest_snapshots(
        self,
        account_id: str,
        as_of: date | None = None,
        kind: SnapshotKind | None = None,
    ) -> dict[str, PositionSnapshot]:
        params: list[object] = [account_id]
        as_of_filter = ""
        if as_of is not None:
            as_of_filter = "and as_of <= ?"
            params.append(as_of.isoformat())
        kind_filter = ""
        if kind is not None:
            kind_filter = "and kind = ?"
            params.append(kind.value)

        rows = self._query(
            self._portfolio_db,
            f"""
            select ps.account_id, ps.instrument_id, ps.as_of, ps.quantity,
                   ps.average_cost, ps.currency, ps.cost_method, ps.kind
            from position_snapshots ps
            join (
                select instrument_id, max(as_of) as max_as_of
                from position_snapshots
                where account_id = ? {as_of_filter} {kind_filter}
                group by instrument_id
            ) latest
              on latest.instrument_id = ps.instrument_id
             and latest.max_as_of = ps.as_of
            where ps.account_id = ?
            """,
            [*params, account_id],
        )

        return {
            row["instrument_id"]: PositionSnapshot(
                account_id=row["account_id"],
                instrument_id=row["instrument_id"],
                as_of=date.fromisoformat(row["as_of"]),
                quantity=Decimal(str(row["quantity"])),
                average_cost=Decimal(str(row["average_cost"])),
                currency=row["currency"],
                cost_method=CostMethod(row["cost_method"]) if row["cost_method"] else None,
                kind=SnapshotKind(row["kind"]),
            )
            for row in rows
        }

    def list_trades(self, account_id: str, as_of: date | None = None) -> list[Trade]:
        params: list[object] = [account_id]
        as_of_filter = ""
        if as_of is not None:
            as_of_filter = "and trade_date <= ?"
            params.append(as_of.isoformat())

        rows = self._query(
            self._portfolio_db,
            f"""
            select trade_id, account_id, instrument_id, trade_date, side,
                   quantity, price, fee, currency, external_trade_id
            from trades
            where account_id = ? {as_of_filter}
            order by trade_date, trade_id
            """,
            params,
        )

        return [
            Trade(
                trade_id=str(row["trade_id"]),
                account_id=row["account_id"],
                instrument_id=row["instrument_id"],
                trade_date=date.fromisoformat(row["trade_date"]),
                side=TradeSide(row["side"]),
                quantity=Decimal(str(row["quantity"])),
                price=Decimal(str(row["price"])),
                fee=Decimal(str(row["fee"])),
                currency=row["currency"],
                external_trade_id=row["external_trade_id"],
            )
            for row in rows
        ]

    def latest_annual_dividends(self, instrument_ids: list[str]) -> dict[str, DividendAnnual]:
        if not instrument_ids:
            return {}
        placeholders = ",".join("?" for _ in instrument_ids)
        rows = self._query(
            self._financials_db,
            f"""
            select d.instrument_id, d.fiscal_year, d.dividend_per_share, d.currency
            from dividends d
            join (
                select instrument_id, max(fiscal_year) as fiscal_year
                from dividends
                where instrument_id in ({placeholders})
                group by instrument_id
            ) latest
              on latest.instrument_id = d.instrument_id
             and latest.fiscal_year = d.fiscal_year
            """,
            list(instrument_ids),
        )
        return {
            row["instrument_id"]: DividendAnnual(
                instrument_id=row["instrument_id"],
                fiscal_year=int(row["fiscal_year"]),
                dividend_per_share=Decimal(str(row["dividend_per_share"])),
                currency=row["currency"],
            )
            for row in rows
        }

    def upsert_instruments(self, instruments: list[InstrumentSummary], aliases: dict[str, str]) -> None:
        with self._lock:
            conn = self._conn(self._instrument_db)
            try:
                conn.executemany(
                    """
                    insert or ignore into instruments(instrument_id, symbol, name, market, currency, status)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (i.instrument_id, i.symbol, i.name, i.market, i.currency, i.status)
                        for i in instruments
                    ],
                )
                conn.executemany(
                    "insert or ignore into instrument_aliases(instrument_id, scheme, identifier) values (?, 'TICKER', ?)",
                    [(instrument_id, identifier) for instrument_id, identifier in aliases.items()],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def insert_trades(self, rows: list[TradeImportRow], batch_id: str) -> tuple[int, int]:
        inserted = 0
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                known_accounts = {
                    row["account_id"]
                    for row in conn.execute("select account_id from accounts").fetchall()
                }
                missing = sorted({r.trade.account_id for r in rows} - known_accounts)
                if missing:
                    raise ValueError(f"unknown account_id(s) in import: {missing}")

                for row in rows:
                    trade = row.trade
                    cursor = conn.execute(
                        """
                        insert or ignore into trades(
                            account_id, instrument_id, trade_date, side, quantity, price, fee,
                            currency, external_trade_id, row_hash, import_batch_id, broker,
                            settle_date, gross_amount, commission, tax, other_fee, net_amount,
                            fx_rate_to_account, account_currency, notes
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trade.account_id,
                            trade.instrument_id,
                            trade.trade_date.isoformat(),
                            trade.side.value,
                            _text(trade.quantity),
                            _text(trade.price),
                            _text(trade.fee),
                            trade.currency,
                            trade.external_trade_id,
                            row.row_hash,
                            batch_id,
                            row.broker,
                            _text(row.settle_date),
                            _text(row.gross_amount),
                            _text(row.commission),
                            _text(row.tax),
                            _text(row.other_fee),
                            _text(row.net_amount),
                            _text(row.fx_rate_to_account),
                            row.account_currency,
                            row.notes,
                        ),
                    )
                    inserted += cursor.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted, len(rows) - inserted

    def get_fx_rate(self, base_currency: str, quote_currency: str, as_of: date | None = None) -> FxRate | None:
        params: list[object] = [base_currency, quote_currency]
        as_of_filter = ""
        if as_of is not None:
            as_of_filter = "and as_of <= ?"
            params.append(as_of.isoformat())
        rows = self._query(
            self._portfolio_db,
            f"""
            select base_currency, quote_currency, as_of, rate
            from fx_rates
            where base_currency = ? and quote_currency = ? {as_of_filter}
            order by as_of desc
            limit 1
            """,
            params,
        )
        if not rows:
            return None
        row = rows[0]
        return FxRate(
            base_currency=row["base_currency"],
            quote_currency=row["quote_currency"],
            as_of=date.fromisoformat(row["as_of"]),
            rate=Decimal(str(row["rate"])),
        )

    def upsert_fx_rates(self, rates: list[FxRate]) -> int:
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                conn.executemany(
                    """
                    insert or replace into fx_rates(base_currency, quote_currency, as_of, rate)
                    values (?, ?, ?, ?)
                    """,
                    [
                        (r.base_currency, r.quote_currency, r.as_of.isoformat(), _text(r.rate))
                        for r in rates
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return len(rates)

    def dividends_received(self, account_id: str, as_of: date | None = None) -> dict[str, Decimal]:
        params: list[object] = [account_id]
        as_of_filter = ""
        if as_of is not None:
            as_of_filter = "and pay_date <= ?"
            params.append(as_of.isoformat())
        rows = self._query(
            self._portfolio_db,
            f"""
            select instrument_id, group_concat(amount, '|') as amounts
            from dividend_payments
            where account_id = ? {as_of_filter}
            group by instrument_id
            """,
            params,
        )
        return {
            row["instrument_id"]: sum(
                (Decimal(part) for part in row["amounts"].split("|")), Decimal("0")
            )
            for row in rows
        }

    def insert_dividend_payments(self, payments: list[DividendPayment]) -> tuple[int, int]:
        inserted = 0
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                known_accounts = {
                    row["account_id"]
                    for row in conn.execute("select account_id from accounts").fetchall()
                }
                missing = sorted({p.account_id for p in payments} - known_accounts)
                if missing:
                    raise ValueError(f"unknown account_id(s) in dividend import: {missing}")

                for payment in payments:
                    cursor = conn.execute(
                        """
                        insert or ignore into dividend_payments(
                            account_id, instrument_id, pay_date, amount, currency,
                            withholding_tax, external_id, row_hash, notes
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payment.account_id,
                            payment.instrument_id,
                            payment.pay_date.isoformat(),
                            _text(payment.amount),
                            payment.currency,
                            _text(payment.withholding_tax),
                            payment.external_id,
                            payment.row_hash,
                            payment.notes,
                        ),
                    )
                    inserted += cursor.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted, len(payments) - inserted

    def insert_cashflows(self, flows: list[Cashflow]) -> tuple[int, int]:
        inserted = 0
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                known_accounts = {
                    row["account_id"]
                    for row in conn.execute("select account_id from accounts").fetchall()
                }
                missing = sorted({f.account_id for f in flows} - known_accounts)
                if missing:
                    raise ValueError(f"unknown account_id(s) in cashflow import: {missing}")

                for flow in flows:
                    cursor = conn.execute(
                        """
                        insert or ignore into cashflows(
                            account_id, flow_date, type, amount, currency,
                            counter_account, external_id, row_hash, notes
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            flow.account_id,
                            flow.flow_date.isoformat(),
                            flow.type.value,
                            _text(flow.amount),
                            flow.currency,
                            flow.counter_account,
                            flow.external_id,
                            flow.row_hash,
                            flow.notes,
                        ),
                    )
                    inserted += cursor.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted, len(flows) - inserted

    def list_cashflows(self, account_id: str, as_of: date | None = None) -> list[Cashflow]:
        params: list[object] = [account_id]
        as_of_filter = ""
        if as_of is not None:
            as_of_filter = "and flow_date <= ?"
            params.append(as_of.isoformat())
        rows = self._query(
            self._portfolio_db,
            f"""
            select cashflow_id, account_id, flow_date, type, amount, currency,
                   counter_account, external_id, row_hash, notes
            from cashflows
            where account_id = ? {as_of_filter}
            order by flow_date, cashflow_id
            """,
            params,
        )
        return [
            Cashflow(
                cashflow_id=str(row["cashflow_id"]),
                account_id=row["account_id"],
                flow_date=date.fromisoformat(row["flow_date"]),
                type=CashflowType(row["type"]),
                amount=Decimal(str(row["amount"])),
                currency=row["currency"],
                counter_account=row["counter_account"],
                external_id=row["external_id"],
                row_hash=row["row_hash"],
                notes=row["notes"],
            )
            for row in rows
        ]

    def upsert_cash_checkpoints(self, checkpoints: list[CashCheckpoint]) -> int:
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                conn.executemany(
                    """
                    insert or replace into cash_checkpoints(account_id, as_of, currency, balance)
                    values (?, ?, ?, ?)
                    """,
                    [
                        (c.account_id, c.as_of.isoformat(), c.currency, _text(c.balance))
                        for c in checkpoints
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return len(checkpoints)

    def list_cash_checkpoints(self, account_id: str) -> list[CashCheckpoint]:
        rows = self._query(
            self._portfolio_db,
            """
            select account_id, as_of, currency, balance
            from cash_checkpoints
            where account_id = ?
            order by as_of, currency
            """,
            [account_id],
        )
        return [
            CashCheckpoint(
                account_id=row["account_id"],
                as_of=date.fromisoformat(row["as_of"]),
                currency=row["currency"],
                balance=Decimal(str(row["balance"])),
            )
            for row in rows
        ]

    def create_import_batch(self, batch: ImportBatch) -> None:
        with self._lock:
            conn = self._conn(self._portfolio_db)
            try:
                conn.execute(
                    """
                    insert into import_batches(batch_id, source_file, imported_at, row_count,
                                               inserted_count, skipped_count, status)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch.batch_id,
                        batch.source_file,
                        batch.imported_at,
                        batch.row_count,
                        batch.inserted_count,
                        batch.skipped_count,
                        batch.status,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def latest_annual_financials(self, instrument_ids: list[str]) -> dict[str, FinancialAnnual]:
        if not instrument_ids:
            return {}
        placeholders = ",".join("?" for _ in instrument_ids)
        rows = self._query(
            self._financials_db,
            f"""
            select f.instrument_id, f.fiscal_year, f.eps, f.currency
            from financials f
            join (
                select instrument_id, max(fiscal_year) as fiscal_year
                from financials
                where instrument_id in ({placeholders})
                group by instrument_id
            ) latest
              on latest.instrument_id = f.instrument_id
             and latest.fiscal_year = f.fiscal_year
            """,
            list(instrument_ids),
        )
        return {
            row["instrument_id"]: FinancialAnnual(
                instrument_id=row["instrument_id"],
                fiscal_year=int(row["fiscal_year"]),
                eps=Decimal(str(row["eps"])),
                currency=row["currency"],
            )
            for row in rows
        }
