"""Data-store protocol for portfolio records.

A single protocol keeps service wiring simple (one store object) while still
being a swap seam: a future instrument_manager adapter can implement the
instrument methods and delegate the rest, and identity mapping goes through
records/identity.py + the instrument_aliases table.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from decimal import Decimal

from .models import (
    Account,
    DividendAnnual,
    DividendPayment,
    FinancialAnnual,
    FxRate,
    ImportBatch,
    InstrumentSummary,
    PositionSnapshot,
    SnapshotKind,
    Trade,
)

from .imports import TradeImportRow


class RecordsStore(Protocol):
    # accounts
    def list_accounts(self) -> list[Account]: ...

    # instruments
    def get_instruments(self, instrument_ids: list[str]) -> dict[str, InstrumentSummary]: ...

    # position snapshots (opening balances + reconciliation checkpoints)
    def latest_snapshots(
        self,
        account_id: str,
        as_of: date | None = None,
        kind: SnapshotKind | None = None,
    ) -> dict[str, PositionSnapshot]: ...

    # trades
    def list_trades(self, account_id: str, as_of: date | None = None) -> list[Trade]: ...

    # dividend cash flows
    def dividends_received(self, account_id: str, as_of: date | None = None) -> dict[str, Decimal]:
        """Total dividend cash received per instrument (native currency)."""
        ...

    def insert_dividend_payments(self, payments: list[DividendPayment]) -> tuple[int, int]:
        """Insert payments, skipping duplicates on (account_id, external_id).
        Returns (inserted, skipped)."""
        ...

    # reference data (display only)
    def latest_annual_dividends(self, instrument_ids: list[str]) -> dict[str, DividendAnnual]: ...

    def latest_annual_financials(self, instrument_ids: list[str]) -> dict[str, FinancialAnnual]: ...

    # fx rates (manually maintained; see records/fx.py for conversion)
    def get_fx_rate(self, base_currency: str, quote_currency: str, as_of: date | None = None) -> FxRate | None: ...

    def upsert_fx_rates(self, rates: list[FxRate]) -> int: ...

    # import persistence
    def upsert_instruments(self, instruments: list[InstrumentSummary], aliases: dict[str, str]) -> None:
        """Insert missing instruments (never overwrites existing reference
        data). ``aliases`` maps instrument_id -> TICKER-scheme identifier."""
        ...

    def insert_trades(self, rows: list[TradeImportRow], batch_id: str) -> tuple[int, int]:
        """Insert rows, skipping duplicates on (account_id, external_trade_id)
        or (account_id, row_hash). Returns (inserted, skipped)."""
        ...

    def create_import_batch(self, batch: ImportBatch) -> None: ...
