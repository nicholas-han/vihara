"""Application service that builds UI-ready holding rows.

Position semantics (v2): trades are the single source of truth. An 'opening'
snapshot seeds a synthetic anchor lot when history before its as_of is
unavailable; a 'checkpoint' snapshot never contributes to positions — it is
only compared against the trade-derived quantity by ``reconcile``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .cost_basis import calculate_position
from .fx import FxProvider, convert
from .models import (
    ZERO,
    CostMethod,
    CurrencyBreakdown,
    HoldingRow,
    InstrumentSummary,
    OpeningPosition,
    PortfolioSummary,
    PositionResult,
    PositionSnapshot,
    ReconciliationIssue,
    SnapshotKind,
    Trade,
    TradeSide,
)
from .providers import RecordsStore


class PortfolioRecordsService:
    def __init__(self, store: RecordsStore, fx: FxProvider | None = None) -> None:
        self.store = store
        # the SQLite store doubles as the FX provider unless one is injected
        self.fx: FxProvider = fx if fx is not None else store  # type: ignore[assignment]

    def list_accounts(self):
        return self.store.list_accounts()

    def positions(
        self,
        account_id: str,
        as_of: date | None = None,
        cost_method: CostMethod = CostMethod.AVERAGE,
    ) -> dict[str, PositionResult]:
        """Per-instrument position results, including fully closed positions
        (quantity 0 with realized P&L)."""
        openings = self.store.latest_snapshots(account_id, as_of, kind=SnapshotKind.OPENING)
        trades_by_instrument = _group_trades(self.store.list_trades(account_id, as_of))
        instrument_ids = sorted(set(openings) | set(trades_by_instrument))

        results: dict[str, PositionResult] = {}
        for instrument_id in instrument_ids:
            results[instrument_id] = calculate_position(
                trades_by_instrument.get(instrument_id, []),
                cost_method,
                opening=_opening(openings.get(instrument_id)),
            )
        return results

    def holdings(
        self,
        account_id: str,
        as_of: date | None = None,
        cost_method: CostMethod = CostMethod.AVERAGE,
    ) -> list[HoldingRow]:
        openings = self.store.latest_snapshots(account_id, as_of, kind=SnapshotKind.OPENING)
        positions = self.positions(account_id, as_of, cost_method)
        instrument_ids = sorted(positions)

        instruments = self.store.get_instruments(instrument_ids)
        dividends = self.store.latest_annual_dividends(instrument_ids)
        financials = self.store.latest_annual_financials(instrument_ids)
        dividends_received = self.store.dividends_received(account_id, as_of)

        rows: list[HoldingRow] = []
        for instrument_id in instrument_ids:
            position = positions[instrument_id]
            if position.quantity == 0:
                # Fully closed; realized P&L still surfaces via summary().
                continue
            instrument = instruments.get(instrument_id) or _missing_instrument(instrument_id)

            dividend = dividends.get(instrument_id)
            financial = financials.get(instrument_id)
            rows.append(
                HoldingRow(
                    account_id=account_id,
                    instrument_id=instrument_id,
                    symbol=instrument.symbol,
                    name=instrument.name,
                    market=instrument.market,
                    currency=position.currency or instrument.currency,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    cost_method=cost_method,
                    position_source="trades+opening" if instrument_id in openings else "trades",
                    dividend_per_share=dividend.dividend_per_share if dividend else None,
                    dividend_fiscal_year=dividend.fiscal_year if dividend else None,
                    eps=financial.eps if financial else None,
                    eps_fiscal_year=financial.fiscal_year if financial else None,
                    realized_pnl=position.realized_pnl,
                    dividends_received=dividends_received.get(instrument_id, ZERO),
                )
            )

        return sorted(rows, key=lambda row: (row.market, row.symbol, row.instrument_id))

    def holdings_for_accounts(
        self,
        account_ids: list[str] | None = None,
        as_of: date | None = None,
        cost_method: CostMethod = CostMethod.AVERAGE,
        exclude_accounts: bool = False,
    ) -> list[HoldingRow]:
        rows: list[HoldingRow] = []
        for account_id in self._target_accounts(account_ids, exclude_accounts):
            rows.extend(self.holdings(account_id, as_of, cost_method))
        return sorted(rows, key=lambda row: (row.account_id, row.market, row.symbol, row.instrument_id))

    def portfolio_summary(
        self,
        account_ids: list[str] | None = None,
        base_currency: str = "USD",
        as_of: date | None = None,
        cost_method: CostMethod = CostMethod.AVERAGE,
        exclude_accounts: bool = False,
    ) -> PortfolioSummary:
        """Totals per currency (open-position cost, realized P&L including
        closed positions, dividends received) plus base-currency sums over the
        currencies that have an FX rate. Currencies without a rate are listed
        in unconverted_currencies and excluded from the base totals."""
        cost_by_ccy: dict[str, Decimal] = defaultdict(lambda: ZERO)
        realized_by_ccy: dict[str, Decimal] = defaultdict(lambda: ZERO)
        dividends_by_ccy: dict[str, Decimal] = defaultdict(lambda: ZERO)

        for account_id in self._target_accounts(account_ids, exclude_accounts):
            positions = self.positions(account_id, as_of, cost_method)
            instruments = self.store.get_instruments(sorted(positions))
            for instrument_id, position in positions.items():
                instrument = instruments.get(instrument_id)
                currency = position.currency or (instrument.currency if instrument else "UNKNOWN")
                cost_by_ccy[currency] += position.total_cost
                realized_by_ccy[currency] += position.realized_pnl

            received = self.store.dividends_received(account_id, as_of)
            for instrument_id, amount in received.items():
                instrument = instruments.get(instrument_id) or self.store.get_instruments([instrument_id]).get(instrument_id)
                currency = instrument.currency if instrument else "UNKNOWN"
                dividends_by_ccy[currency] += amount

        currencies = sorted(set(cost_by_ccy) | set(realized_by_ccy) | set(dividends_by_ccy))
        breakdowns: list[CurrencyBreakdown] = []
        total_cost_base = ZERO
        realized_base = ZERO
        dividends_base = ZERO
        unconverted: list[str] = []

        for currency in currencies:
            cost = cost_by_ccy[currency]
            realized = realized_by_ccy[currency]
            dividends = dividends_by_ccy[currency]
            converted = {
                name: convert(self.fx, amount, currency, base_currency, as_of)
                for name, amount in (("cost", cost), ("realized", realized), ("dividends", dividends))
            }
            if any(value is None for value in converted.values()):
                unconverted.append(currency)
                breakdowns.append(
                    CurrencyBreakdown(
                        currency=currency,
                        total_cost=cost,
                        realized_pnl=realized,
                        dividends_received=dividends,
                    )
                )
                continue

            total_cost_base += converted["cost"].amount
            realized_base += converted["realized"].amount
            dividends_base += converted["dividends"].amount
            breakdowns.append(
                CurrencyBreakdown(
                    currency=currency,
                    total_cost=cost,
                    realized_pnl=realized,
                    dividends_received=dividends,
                    total_cost_base=converted["cost"].amount,
                    realized_pnl_base=converted["realized"].amount,
                    dividends_received_base=converted["dividends"].amount,
                )
            )

        return PortfolioSummary(
            base_currency=base_currency,
            by_currency=tuple(breakdowns),
            total_cost_base=total_cost_base,
            realized_pnl_base=realized_base,
            dividends_received_base=dividends_base,
            unconverted_currencies=tuple(unconverted),
        )

    def reconcile(self, account_id: str, as_of: date | None = None) -> list[ReconciliationIssue]:
        """Compare each latest checkpoint snapshot with the trade-derived
        quantity at its as_of. Quantity is cost-method independent."""
        checkpoints = self.store.latest_snapshots(account_id, as_of, kind=SnapshotKind.CHECKPOINT)
        if not checkpoints:
            return []
        openings = self.store.latest_snapshots(account_id, as_of, kind=SnapshotKind.OPENING)
        trades = self.store.list_trades(account_id, as_of)

        issues: list[ReconciliationIssue] = []
        for instrument_id in sorted(checkpoints):
            checkpoint = checkpoints[instrument_id]
            quantity = ZERO
            opening = openings.get(instrument_id)
            if opening is not None and opening.as_of <= checkpoint.as_of:
                quantity += opening.quantity
            for trade in trades:
                if trade.instrument_id != instrument_id or trade.trade_date > checkpoint.as_of:
                    continue
                if opening is not None and trade.trade_date <= opening.as_of:
                    continue
                quantity += trade.quantity if trade.side == TradeSide.BUY else -trade.quantity
            if quantity != checkpoint.quantity:
                issues.append(
                    ReconciliationIssue(
                        account_id=account_id,
                        instrument_id=instrument_id,
                        as_of=checkpoint.as_of,
                        snapshot_quantity=checkpoint.quantity,
                        computed_quantity=quantity,
                    )
                )
        return issues

    def reconcile_accounts(
        self,
        account_ids: list[str] | None = None,
        as_of: date | None = None,
        exclude_accounts: bool = False,
    ) -> list[ReconciliationIssue]:
        issues: list[ReconciliationIssue] = []
        for account_id in self._target_accounts(account_ids, exclude_accounts):
            issues.extend(self.reconcile(account_id, as_of))
        return issues

    def _target_accounts(self, account_ids: list[str] | None, exclude_accounts: bool) -> list[str]:
        selected = set(account_ids or [])
        all_account_ids = [account.account_id for account in self.store.list_accounts()]
        if not selected:
            return all_account_ids
        return [
            account_id
            for account_id in all_account_ids
            if (account_id not in selected if exclude_accounts else account_id in selected)
        ]


def _group_trades(trades: list[Trade]) -> dict[str, list[Trade]]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.instrument_id].append(trade)
    return grouped


def _opening(snapshot: PositionSnapshot | None) -> OpeningPosition | None:
    if snapshot is None:
        return None
    return OpeningPosition(
        as_of=snapshot.as_of,
        quantity=snapshot.quantity,
        average_cost=snapshot.average_cost,
        currency=snapshot.currency,
    )


def _missing_instrument(instrument_id: str) -> InstrumentSummary:
    # Reference data is absent; do not invent a market or currency. Currency
    # shown on the holding row still comes from the position/trades.
    return InstrumentSummary(
        instrument_id=instrument_id,
        symbol=instrument_id,
        name=instrument_id,
        market="UNKNOWN",
        currency="UNKNOWN",
        status="MISSING",
    )
