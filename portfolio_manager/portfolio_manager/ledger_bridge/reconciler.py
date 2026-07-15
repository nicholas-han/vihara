"""Reconciliation: prove the ledger, the CSVs and the broker statements agree.

The check taxonomy is Simmons' (Securities Operations ch. 27) scaled to a
personal book — broker statements play the custodian:

  R1  ledger check clean            internal integrity (Sigma=0, assertions)
  R2  generated/ matches sources    trade-by-trade completeness
  R3  ledger units == pm positions  trading position (units)
  R4  ledger costs/P&L == pm        trading position (cash), tol 1e-6 dust
  R5  checkpoint qty == pm qty      depot position
  R6  checkpoint cash == ledger     nostro position
  R7  derived index staleness       (hygiene, warning only)

R1/R6 are partially redundant with the generated balance assertions — by
design: assertions fail loudly inside `ledger check`, the reconciler
explains *which side* moved.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ledger import query as ledger_query
from ledger.core.inventory import ZERO
from ledger.errors import Severity
from ledger.index import sqlite_index
from ledger.validate import check as ledger_check

from ..records.cost_basis import calculate_position
from ..records.models import OpeningPosition, TradeSide
from .commodities import to_commodity
from .generator import build_files, read_inputs
from .mapping import load_mapping

COST_TOLERANCE = Decimal("0.000001")  # partial-lot division dust (docs/20)


@dataclass(frozen=True)
class ReconBreak:
    check: str
    account_id: str
    scope: str          # instrument/commodity/currency/file
    expected: str
    actual: str
    as_of: datetime.date | None = None
    detail: str = ""

    def __str__(self) -> str:
        when = f" as of {self.as_of}" if self.as_of else ""
        detail = f" ({self.detail})" if self.detail else ""
        return (
            f"[{self.check}] {self.account_id} {self.scope}{when}: "
            f"expected {self.expected}, actual {self.actual}{detail}"
        )


def run_checks(data_dir: Path) -> list[ReconBreak]:
    data_dir = Path(data_dir)
    breaks: list[ReconBreak] = []
    mapping = load_mapping(data_dir / "bridge" / "mapping.toml")
    warnings: list[str] = []
    inputs = read_inputs(data_dir, warnings)

    # R2 — generated journal must equal what the sources produce now.
    expected_files = build_files(data_dir).files
    generated_dir = data_dir / "ledger" / "generated"
    on_disk = {
        str(p.relative_to(generated_dir)): p.read_text(encoding="utf-8")
        for p in sorted(generated_dir.rglob("*.beancount"))
    } if generated_dir.is_dir() else {}
    for relpath in sorted(set(expected_files) | set(on_disk)):
        if relpath not in on_disk:
            breaks.append(ReconBreak("R2-generated-drift", "-", relpath,
                                     "file present", "missing",
                                     detail="run generate"))
        elif relpath not in expected_files:
            breaks.append(ReconBreak("R2-generated-drift", "-", relpath,
                                     "no file", "unexpected file",
                                     detail="run generate"))
        elif expected_files[relpath] != on_disk[relpath]:
            breaks.append(ReconBreak("R2-generated-drift", "-", relpath,
                                     "sources' content", "differs",
                                     detail="hand-edited or stale; run generate"))

    # R1 — the ledger itself must check clean.
    main_path = data_dir / "ledger" / "main.beancount"
    result = ledger_check(main_path)
    for error in result.errors:
        if error.severity is Severity.ERROR:
            breaks.append(ReconBreak("R1-ledger-check", "-", str(error.pos or ""),
                                     "no error", error.message))

    # R3/R4 — pm-derived positions vs ledger inventories, per account.
    for account_id in sorted(inputs):
        acc_inputs = inputs[account_id]
        acc_mapping = mapping.require(account_id)
        inventory = result.book.inventories.get(acc_mapping.positions)

        by_instrument: dict[str, list] = {}
        for row, _ in acc_inputs.trades:
            by_instrument.setdefault(row.trade.instrument_id, []).append(row.trade)
        for instrument_id in acc_inputs.openings:
            by_instrument.setdefault(instrument_id, [])

        total_realized = ZERO
        realized_currency: str | None = None
        for instrument_id in sorted(by_instrument):
            opening_snapshot = acc_inputs.openings.get(instrument_id)
            opening = (
                OpeningPosition(opening_snapshot.as_of, opening_snapshot.quantity,
                                opening_snapshot.average_cost, opening_snapshot.currency)
                if opening_snapshot is not None else None
            )
            pm = calculate_position(
                by_instrument[instrument_id], acc_mapping.cost_method, opening
            )
            total_realized += pm.realized_pnl
            realized_currency = realized_currency or pm.currency
            commodity = to_commodity(instrument_id)
            ledger_units = inventory.units_of(commodity) if inventory else ZERO
            if ledger_units != pm.quantity:
                breaks.append(ReconBreak(
                    "R3-units", account_id, instrument_id,
                    str(pm.quantity), str(ledger_units),
                ))
            ledger_cost = (
                sum((lot.cost_total for lot in inventory.lots_of(commodity)), ZERO)
                if inventory else ZERO
            )
            if abs(ledger_cost - pm.total_cost) > COST_TOLERANCE:
                breaks.append(ReconBreak(
                    "R4-cost", account_id, instrument_id,
                    str(pm.total_cost), str(ledger_cost),
                    detail="remaining lot cost",
                ))

        pnl_inventory = result.book.inventories.get(acc_mapping.pnl)
        if realized_currency is not None:
            ledger_pnl = (
                -pnl_inventory.cash.get(realized_currency, ZERO)
                if pnl_inventory else ZERO
            )
            if abs(ledger_pnl - total_realized) > COST_TOLERANCE:
                breaks.append(ReconBreak(
                    "R4-realized", account_id, realized_currency,
                    str(total_realized), str(ledger_pnl),
                    detail="sum of Income:PnL postings (sign flipped)",
                ))

        # R5 — checkpoint positions vs pm quantities at as_of (inclusive).
        for snapshot in acc_inputs.checkpoint_positions:
            trades = by_instrument.get(snapshot.instrument_id, [])
            quantity = ZERO
            opening_snapshot = acc_inputs.openings.get(snapshot.instrument_id)
            if opening_snapshot is not None and opening_snapshot.as_of <= snapshot.as_of:
                quantity += opening_snapshot.quantity
            for trade in trades:
                if trade.trade_date <= snapshot.as_of:
                    quantity += (
                        trade.quantity if trade.side is TradeSide.BUY else -trade.quantity
                    )
            if quantity != snapshot.quantity:
                breaks.append(ReconBreak(
                    "R5-depot", account_id, snapshot.instrument_id,
                    str(snapshot.quantity), str(quantity),
                    as_of=snapshot.as_of,
                    detail="broker checkpoint vs trade-derived quantity",
                ))

        # R6 — checkpoint cash vs the ledger cash account at end of as_of.
        for checkpoint in acc_inputs.checkpoint_cash:
            at = ledger_query.balances_at(result.load.directives, checkpoint.as_of)
            cash_inventory = at.inventories.get(acc_mapping.cash)
            balance = (
                cash_inventory.cash.get(checkpoint.currency, ZERO)
                if cash_inventory else ZERO
            )
            if balance != checkpoint.balance:
                breaks.append(ReconBreak(
                    "R6-nostro", account_id, checkpoint.currency,
                    str(checkpoint.balance), str(balance),
                    as_of=checkpoint.as_of,
                    detail="statement cash vs ledger cash account",
                ))

    # R7 — derived index staleness (only when an index exists).
    index_path = data_dir / "build" / "ledger.sqlite3"
    if index_path.exists() and sqlite_index.is_stale(index_path, result.load.files):
        breaks.append(ReconBreak(
            "R7-stale-index", "-", str(index_path),
            "index in sync with text", "stale",
            detail="run: python -m ledger rebuild-index",
        ))

    return breaks
