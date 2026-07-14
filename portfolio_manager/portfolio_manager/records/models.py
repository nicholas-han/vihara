"""Typed records used by the portfolio records service.

All money and quantity fields are decimal.Decimal; SQLite stores them as TEXT
decimal strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal("0")


class CostMethod(StrEnum):
    AVERAGE = "average"
    FIFO = "fifo"
    LIFO = "lifo"
    LOWEST_COST_FIRST = "lowest_cost_first"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SnapshotKind(StrEnum):
    # Anchor lot when trade history before as_of is unavailable.
    OPENING = "opening"
    # Broker statement figure used to reconcile trade-derived positions;
    # never a position source.
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True)
class Account:
    account_id: str
    name: str
    currency: str = "USD"


@dataclass(frozen=True)
class InstrumentSummary:
    instrument_id: str
    symbol: str
    name: str
    market: str
    currency: str
    status: str = "ACTIVE"


@dataclass(frozen=True)
class PositionSnapshot:
    account_id: str
    instrument_id: str
    as_of: date
    quantity: Decimal
    average_cost: Decimal
    currency: str
    cost_method: CostMethod | None = None
    kind: SnapshotKind = SnapshotKind.CHECKPOINT


@dataclass(frozen=True)
class Trade:
    account_id: str
    instrument_id: str
    trade_date: date
    side: TradeSide
    quantity: Decimal
    price: Decimal
    fee: Decimal = ZERO
    currency: str = "USD"
    trade_id: str | None = None
    external_trade_id: str | None = None


@dataclass(frozen=True)
class DividendAnnual:
    instrument_id: str
    fiscal_year: int
    dividend_per_share: Decimal
    currency: str


@dataclass(frozen=True)
class FinancialAnnual:
    instrument_id: str
    fiscal_year: int
    eps: Decimal
    currency: str


@dataclass(frozen=True)
class ImportBatch:
    batch_id: str
    imported_at: str  # ISO-8601 UTC timestamp
    row_count: int
    inserted_count: int
    skipped_count: int
    status: str = "completed"
    source_file: str | None = None


@dataclass(frozen=True)
class OpeningPosition:
    """Anchor position derived from an 'opening' snapshot: history before
    as_of is unavailable, so it enters cost-basis math as one synthetic lot."""

    as_of: date
    quantity: Decimal
    average_cost: Decimal
    currency: str


@dataclass(frozen=True)
class RealizedTrade:
    trade_id: str | None
    trade_date: date
    quantity: Decimal
    proceeds: Decimal       # quantity * price - sell fee
    cost_consumed: Decimal  # basis of the lots (or average cost) consumed
    sell_fee: Decimal
    realized_pnl: Decimal   # proceeds - cost_consumed


@dataclass(frozen=True)
class PositionResult:
    quantity: Decimal
    total_cost: Decimal
    realized_pnl: Decimal
    realized_trades: tuple[RealizedTrade, ...] = ()
    currency: str | None = None

    @property
    def average_cost(self) -> Decimal:
        if self.quantity == 0:
            return ZERO
        return self.total_cost / self.quantity


@dataclass(frozen=True)
class DividendPayment:
    account_id: str
    instrument_id: str
    pay_date: date
    amount: Decimal          # net cash received, in `currency`
    currency: str
    withholding_tax: Decimal = ZERO
    external_id: str | None = None
    notes: str | None = None
    payment_id: str | None = None


@dataclass(frozen=True)
class FxRate:
    base_currency: str
    quote_currency: str
    as_of: date
    rate: Decimal  # 1 base = rate quote


@dataclass(frozen=True)
class CurrencyBreakdown:
    currency: str
    total_cost: Decimal
    realized_pnl: Decimal
    dividends_received: Decimal
    # converted to the summary's base currency; None when no FX rate exists
    total_cost_base: Decimal | None = None
    realized_pnl_base: Decimal | None = None
    dividends_received_base: Decimal | None = None


@dataclass(frozen=True)
class PortfolioSummary:
    base_currency: str
    by_currency: tuple[CurrencyBreakdown, ...]
    # sums over currencies that could be converted
    total_cost_base: Decimal
    realized_pnl_base: Decimal
    dividends_received_base: Decimal
    # currencies with no available rate — their amounts are NOT in the totals
    unconverted_currencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationIssue:
    """A checkpoint snapshot whose quantity disagrees with the trade-derived
    position at its as_of date. Quantity is cost-method independent, so this
    comparison needs no method choice."""

    account_id: str
    instrument_id: str
    as_of: date
    snapshot_quantity: Decimal
    computed_quantity: Decimal

    @property
    def difference(self) -> Decimal:
        return self.computed_quantity - self.snapshot_quantity


@dataclass(frozen=True)
class HoldingRow:
    account_id: str
    instrument_id: str
    symbol: str
    name: str
    market: str
    currency: str
    quantity: Decimal
    average_cost: Decimal
    cost_method: CostMethod
    position_source: str
    dividend_per_share: Decimal | None
    dividend_fiscal_year: int | None
    eps: Decimal | None
    eps_fiscal_year: int | None
    realized_pnl: Decimal = ZERO
    dividends_received: Decimal = ZERO
