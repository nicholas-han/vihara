"""Cost-basis and realized-P&L calculations for trade-derived positions.

All arithmetic is decimal.Decimal, so lot consumption is exact and needs no
float epsilon guards.

Realized P&L convention: buy fees are capitalized into lot cost; sell fees
reduce proceeds. For a sell, realized = (quantity * price - sell fee) - cost
of the basis consumed, where "consumed" follows the chosen cost method.

An OpeningPosition (from an 'opening' snapshot) enters as one synthetic lot
dated at its as_of. Trades on or before that date conflict with the anchor
(history is supposed to be unavailable) and are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import (
    ZERO,
    ConsumedLot,
    CostMethod,
    OpeningPosition,
    PositionResult,
    RealizedTrade,
    Trade,
    TradeSide,
)


@dataclass
class _Lot:
    quantity: Decimal
    unit_cost: Decimal
    source: Trade | None = None  # the buy that opened the lot; None = opening


def calculate_position(
    trades: list[Trade],
    method: CostMethod,
    opening: OpeningPosition | None = None,
) -> PositionResult:
    ordered = sorted(trades, key=lambda t: (t.trade_date, t.trade_id or ""))

    if opening is not None:
        conflicting = [t for t in ordered if t.trade_date <= opening.as_of]
        if conflicting:
            raise ValueError(
                f"{len(conflicting)} trade(s) on or before the opening snapshot "
                f"({opening.as_of.isoformat()}) for {conflicting[0].instrument_id}; "
                "an opening snapshot means history before it is unavailable"
            )

    if method == CostMethod.AVERAGE:
        return _calculate_average(ordered, opening)
    return _calculate_lot_method(ordered, method, opening)


def _calculate_average(trades: list[Trade], opening: OpeningPosition | None) -> PositionResult:
    quantity = opening.quantity if opening else ZERO
    total_cost = opening.quantity * opening.average_cost if opening else ZERO
    currency = opening.currency if opening else None
    realized: list[RealizedTrade] = []

    for trade in trades:
        _validate_trade(trade)
        currency = currency or trade.currency
        if trade.side == TradeSide.BUY:
            quantity += trade.quantity
            total_cost += trade.quantity * trade.price + trade.fee
            continue

        if trade.quantity > quantity:
            raise ValueError(f"sell quantity exceeds open position for {trade.instrument_id}")
        unit_cost = total_cost / quantity if quantity else ZERO
        cost_consumed = trade.quantity * unit_cost
        consumed = (ConsumedLot(trade.quantity, cost_consumed, None),)
        realized.append(_realized_trade(trade, cost_consumed, consumed))
        quantity -= trade.quantity
        total_cost -= cost_consumed

    return _result(quantity, total_cost, realized, currency)


def _calculate_lot_method(
    trades: list[Trade],
    method: CostMethod,
    opening: OpeningPosition | None,
) -> PositionResult:
    lots: list[_Lot] = []
    if opening is not None:
        lots.append(_Lot(quantity=opening.quantity, unit_cost=opening.average_cost))
    currency = opening.currency if opening else None
    realized: list[RealizedTrade] = []

    for trade in trades:
        _validate_trade(trade)
        currency = currency or trade.currency
        if trade.side == TradeSide.BUY:
            lots.append(
                _Lot(
                    quantity=trade.quantity,
                    unit_cost=(trade.quantity * trade.price + trade.fee) / trade.quantity,
                    source=trade,
                )
            )
            continue

        cost_consumed, consumed = _consume_lots(lots, trade.quantity, method, trade.instrument_id)
        realized.append(_realized_trade(trade, cost_consumed, consumed))

    quantity = sum((lot.quantity for lot in lots), ZERO)
    total_cost = sum((lot.quantity * lot.unit_cost for lot in lots), ZERO)
    return _result(quantity, total_cost, realized, currency)


def _realized_trade(
    trade: Trade,
    cost_consumed: Decimal,
    consumed_lots: tuple[ConsumedLot, ...],
) -> RealizedTrade:
    proceeds = trade.quantity * trade.price - trade.fee
    return RealizedTrade(
        trade_id=trade.trade_id,
        trade_date=trade.trade_date,
        quantity=trade.quantity,
        proceeds=proceeds,
        cost_consumed=cost_consumed,
        sell_fee=trade.fee,
        realized_pnl=proceeds - cost_consumed,
        consumed_lots=consumed_lots,
    )


def _result(
    quantity: Decimal,
    total_cost: Decimal,
    realized: list[RealizedTrade],
    currency: str | None,
) -> PositionResult:
    if quantity == 0:
        quantity = ZERO
        total_cost = ZERO
    return PositionResult(
        quantity=quantity,
        total_cost=total_cost,
        realized_pnl=sum((r.realized_pnl for r in realized), ZERO),
        realized_trades=tuple(realized),
        currency=currency,
    )


def _consume_lots(
    lots: list[_Lot],
    quantity: Decimal,
    method: CostMethod,
    instrument_id: str,
) -> tuple[Decimal, tuple[ConsumedLot, ...]]:
    open_quantity = sum((lot.quantity for lot in lots), ZERO)
    if quantity > open_quantity:
        raise ValueError(f"sell quantity exceeds open position for {instrument_id}")

    cost_consumed = ZERO
    consumed: list[ConsumedLot] = []
    remaining = quantity
    while remaining > 0:
        lot_index = _select_lot_index(lots, method)
        lot = lots[lot_index]
        take = min(lot.quantity, remaining)
        piece_cost = take * lot.unit_cost
        cost_consumed += piece_cost
        consumed.append(ConsumedLot(take, piece_cost, lot.source))
        lot.quantity -= take
        remaining -= take
        if lot.quantity == 0:
            lots.pop(lot_index)
    return cost_consumed, tuple(consumed)


def _select_lot_index(lots: list[_Lot], method: CostMethod) -> int:
    if method == CostMethod.FIFO:
        return 0
    if method == CostMethod.LIFO:
        return len(lots) - 1
    if method == CostMethod.LOWEST_COST_FIRST:
        return min(range(len(lots)), key=lambda i: lots[i].unit_cost)
    raise ValueError(f"unsupported lot cost method: {method}")


def _validate_trade(trade: Trade) -> None:
    if trade.quantity <= 0:
        raise ValueError("trade quantity must be positive")
    if trade.price < 0:
        raise ValueError("trade price cannot be negative")
    if trade.fee < 0:
        raise ValueError("trade fee cannot be negative")
