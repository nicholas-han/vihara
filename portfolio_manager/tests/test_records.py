from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from portfolio_manager.records import CostMethod, PortfolioRecordsService, Trade, calculate_position
from portfolio_manager.records.models import (
    Account,
    DividendAnnual,
    FinancialAnnual,
    InstrumentSummary,
    OpeningPosition,
    PositionSnapshot,
    SnapshotKind,
    TradeSide,
)


def _trade(trade_id: str, side: TradeSide, quantity: int, price: int, day: int | None = None) -> Trade:
    return Trade(
        trade_id=trade_id,
        account_id="taxable",
        instrument_id="AAPL.US",
        trade_date=date(2025, 1, day if day is not None else int(trade_id)),
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("0"),
        currency="USD",
    )


LOT_TRADES = [
    _trade("1", TradeSide.BUY, 10, 100),
    _trade("2", TradeSide.BUY, 10, 80),
    _trade("3", TradeSide.BUY, 10, 120),
    _trade("4", TradeSide.SELL, 15, 130),
]


def test_cost_basis_methods_consume_expected_lots():
    average = calculate_position(LOT_TRADES, CostMethod.AVERAGE)
    assert average.quantity == Decimal(15)
    assert average.average_cost == Decimal(100)

    fifo = calculate_position(LOT_TRADES, CostMethod.FIFO)
    assert fifo.quantity == Decimal(15)
    assert fifo.average_cost == Decimal(5 * 80 + 10 * 120) / Decimal(15)

    lifo = calculate_position(LOT_TRADES, CostMethod.LIFO)
    assert lifo.quantity == Decimal(15)
    assert lifo.average_cost == Decimal(10 * 100 + 5 * 80) / Decimal(15)

    low_cost = calculate_position(LOT_TRADES, CostMethod.LOWEST_COST_FIRST)
    assert low_cost.quantity == Decimal(15)
    assert low_cost.average_cost == Decimal(5 * 100 + 10 * 120) / Decimal(15)


def test_realized_pnl_per_cost_method():
    # sell 15 @ 130 => proceeds 1950; consumed basis differs by method
    assert calculate_position(LOT_TRADES, CostMethod.AVERAGE).realized_pnl == Decimal(450)
    assert calculate_position(LOT_TRADES, CostMethod.FIFO).realized_pnl == Decimal(550)
    assert calculate_position(LOT_TRADES, CostMethod.LIFO).realized_pnl == Decimal(350)
    assert calculate_position(LOT_TRADES, CostMethod.LOWEST_COST_FIRST).realized_pnl == Decimal(650)


def test_realized_pnl_deducts_sell_fee_and_reports_trades():
    trades = [
        _trade("1", TradeSide.BUY, 10, 100),
        replace(_trade("2", TradeSide.SELL, 4, 150), fee=Decimal("2")),
    ]

    result = calculate_position(trades, CostMethod.FIFO)

    assert len(result.realized_trades) == 1
    realized = result.realized_trades[0]
    assert realized.proceeds == Decimal(4 * 150 - 2)
    assert realized.cost_consumed == Decimal(400)
    assert realized.sell_fee == Decimal("2")
    assert result.realized_pnl == Decimal(198)
    # remaining basis unaffected by the sell fee
    assert result.average_cost == Decimal(100)


def test_closed_position_keeps_realized_pnl():
    trades = [
        _trade("1", TradeSide.BUY, 10, 100),
        _trade("2", TradeSide.SELL, 10, 110),
    ]

    result = calculate_position(trades, CostMethod.AVERAGE)

    assert result.quantity == Decimal(0)
    assert result.total_cost == Decimal(0)
    assert result.realized_pnl == Decimal(100)


def test_cost_basis_capitalizes_buy_fees():
    trades = [replace(_trade("1", TradeSide.BUY, 10, 100), fee=Decimal("5"))]

    position = calculate_position(trades, CostMethod.FIFO)

    assert position.quantity == Decimal(10)
    assert position.average_cost == Decimal("100.5")


def test_cost_basis_rejects_short_sale():
    trades = [_trade("1", TradeSide.SELL, 1, 100)]

    with pytest.raises(ValueError, match="sell quantity exceeds open position"):
        calculate_position(trades, CostMethod.AVERAGE)


OPENING = OpeningPosition(as_of=date(2024, 12, 31), quantity=Decimal(20), average_cost=Decimal(90), currency="USD")


def test_opening_position_seeds_synthetic_lot():
    trades = [
        _trade("1", TradeSide.BUY, 10, 100, day=5),
        _trade("2", TradeSide.SELL, 25, 120, day=10),
    ]

    fifo = calculate_position(trades, CostMethod.FIFO, opening=OPENING)
    # FIFO consumes the opening lot (20 @ 90) then 5 of the buy (@ 100)
    assert fifo.quantity == Decimal(5)
    assert fifo.average_cost == Decimal(100)
    assert fifo.realized_pnl == Decimal(25 * 120 - (20 * 90 + 5 * 100))

    lifo = calculate_position(trades, CostMethod.LIFO, opening=OPENING)
    # LIFO consumes the buy (10 @ 100) then 15 of the opening lot (@ 90)
    assert lifo.quantity == Decimal(5)
    assert lifo.average_cost == Decimal(90)
    assert lifo.realized_pnl == Decimal(25 * 120 - (10 * 100 + 15 * 90))


def test_opening_position_conflicts_with_earlier_trades():
    trades = [_trade("1", TradeSide.BUY, 10, 100, day=5)]
    opening = replace(OPENING, as_of=date(2025, 1, 5))

    with pytest.raises(ValueError, match="opening snapshot"):
        calculate_position(trades, CostMethod.AVERAGE, opening=opening)


def _opening_snapshot(kind: SnapshotKind, quantity: int, as_of: date) -> PositionSnapshot:
    return PositionSnapshot(
        account_id="taxable",
        instrument_id="AAPL.US",
        as_of=as_of,
        quantity=Decimal(quantity),
        average_cost=Decimal(88),
        currency="USD",
        cost_method=None,
        kind=kind,
    )


def test_service_checkpoint_snapshot_does_not_override_trades():
    store = _FakeStore(
        snapshots=[_opening_snapshot(SnapshotKind.CHECKPOINT, 7, date(2025, 12, 31))],
        trades=[_trade("1", TradeSide.BUY, 10, 100)],
    )
    service = PortfolioRecordsService(store)

    rows = service.holdings("taxable", cost_method=CostMethod.LIFO)

    assert len(rows) == 1
    assert rows[0].quantity == Decimal(10)
    assert rows[0].position_source == "trades"
    assert rows[0].cost_method == CostMethod.LIFO


def test_service_opening_snapshot_seeds_position():
    store = _FakeStore(
        snapshots=[_opening_snapshot(SnapshotKind.OPENING, 7, date(2024, 12, 31))],
        trades=[_trade("1", TradeSide.BUY, 10, 100)],
    )
    service = PortfolioRecordsService(store)

    rows = service.holdings("taxable")

    assert len(rows) == 1
    assert rows[0].quantity == Decimal(17)
    assert rows[0].position_source == "trades+opening"


def test_service_reconcile_flags_quantity_mismatch():
    store = _FakeStore(
        snapshots=[_opening_snapshot(SnapshotKind.CHECKPOINT, 7, date(2025, 12, 31))],
        trades=[_trade("1", TradeSide.BUY, 10, 100)],
    )
    service = PortfolioRecordsService(store)

    issues = service.reconcile("taxable")

    assert len(issues) == 1
    assert issues[0].snapshot_quantity == Decimal(7)
    assert issues[0].computed_quantity == Decimal(10)
    assert issues[0].difference == Decimal(3)


def test_service_reconcile_passes_when_quantities_match():
    store = _FakeStore(
        snapshots=[_opening_snapshot(SnapshotKind.CHECKPOINT, 10, date(2025, 12, 31))],
        trades=[_trade("1", TradeSide.BUY, 10, 100)],
    )
    service = PortfolioRecordsService(store)

    assert service.reconcile("taxable") == []


def test_service_reports_dividends_received():
    store = _FakeStore(snapshots=[], trades=[_trade("1", TradeSide.BUY, 10, 100)])
    store.dividends = {"AAPL.US": Decimal("7.05")}
    service = PortfolioRecordsService(store)

    rows = service.holdings("taxable")

    assert rows[0].dividends_received == Decimal("7.05")
    assert rows[0].dividend_per_share == Decimal("0.96")


def test_records_service_filters_multiple_accounts():
    store = _FakeStore(snapshots=[], trades=[_trade("1", TradeSide.BUY, 10, 100)])
    service = PortfolioRecordsService(store)

    rows = service.holdings_for_accounts(["taxable", "retirement"], cost_method=CostMethod.AVERAGE)

    assert [row.account_id for row in rows] == ["taxable"]


def test_records_service_can_exclude_selected_accounts():
    store = _FakeStore(snapshots=[], trades=[_trade("1", TradeSide.BUY, 10, 100)])
    service = PortfolioRecordsService(store)

    rows = service.holdings_for_accounts(["retirement"], cost_method=CostMethod.AVERAGE, exclude_accounts=True)

    assert [row.account_id for row in rows] == ["taxable"]


class _FakeStore:
    def __init__(self, snapshots: list[PositionSnapshot], trades: list[Trade]) -> None:
        self._snapshots = snapshots
        self._trades = trades
        self.dividends: dict[str, Decimal] = {}

    def list_accounts(self):
        return [Account("retirement", "Retirement", "USD"), Account("taxable", "Taxable", "USD")]

    def get_instruments(self, instrument_ids: list[str]):
        return {
            "AAPL.US": InstrumentSummary("AAPL.US", "AAPL", "Apple Inc.", "US", "USD")
            for instrument_id in instrument_ids
            if instrument_id == "AAPL.US"
        }

    def latest_snapshots(self, account_id: str, as_of=None, kind=None):
        return {
            snapshot.instrument_id: snapshot
            for snapshot in self._snapshots
            if (kind is None or snapshot.kind == kind) and snapshot.account_id == account_id
        }

    def list_trades(self, account_id: str, as_of=None):
        return [trade for trade in self._trades if trade.account_id == account_id]

    def dividends_received(self, account_id: str, as_of=None):
        return dict(self.dividends)

    def latest_annual_dividends(self, instrument_ids: list[str]):
        return {
            "AAPL.US": DividendAnnual("AAPL.US", 2024, Decimal("0.96"), "USD")
            for instrument_id in instrument_ids
            if instrument_id == "AAPL.US"
        }

    def latest_annual_financials(self, instrument_ids: list[str]):
        return {
            "AAPL.US": FinancialAnnual("AAPL.US", 2024, Decimal("6.08"), "USD")
            for instrument_id in instrument_ids
            if instrument_id == "AAPL.US"
        }
