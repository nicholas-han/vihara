"""bridge/mapping.toml — account_id -> ledger accounts configuration.

Example:

    [defaults]
    uncategorized = "Equity:Uncategorized"
    opening = "Equity:Opening"

    [accounts.taxable]
    positions   = "Assets:Broker:IBKR:Positions"
    cash        = "Assets:Broker:IBKR:Cash"
    pnl         = "Income:PnL:Realized:IBKR"
    dividends   = "Income:Dividends:IBKR"
    withholding = "Expenses:Tax:Withholding"
    cost_method = "fifo"      # must equal the method pm reports with

The five mapped accounts are BRIDGE-OWNED: the generator emits their open
directives (with the booking string implied by cost_method), so they must
not be opened by hand in accounts.beancount. Counter accounts named by
cashflows (banks, Equity:*) are hand-owned and must be opened there.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..records.models import CostMethod

try:
    from ledger.core.account import is_valid_account
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "ledger_bridge requires the ledger package (vihara monorepo root on "
        "the path, or `pip install -e ledger`)"
    ) from exc

_ROLE_KEYS = ("positions", "cash", "pnl", "dividends", "withholding")


@dataclass(frozen=True)
class AccountMapping:
    account_id: str
    positions: str
    cash: str
    pnl: str
    dividends: str
    withholding: str
    cost_method: CostMethod

    @property
    def booking(self) -> str:
        """Ledger booking string for the positions account. AVERAGE pools
        need "NONE" (bean-check-legal; our engine gives it pool semantics);
        every lot method books "STRICT" because generated reductions are
        always fully lot-addressed by {date, label}."""
        return "NONE" if self.cost_method is CostMethod.AVERAGE else "STRICT"

    def owned_accounts(self) -> tuple[str, ...]:
        return (self.positions, self.cash, self.pnl, self.dividends, self.withholding)


@dataclass(frozen=True)
class BridgeMapping:
    accounts: dict[str, AccountMapping]
    uncategorized: str = "Equity:Uncategorized"
    opening: str = "Equity:Opening"

    def require(self, account_id: str) -> AccountMapping:
        mapping = self.accounts.get(account_id)
        if mapping is None:
            raise ValueError(
                f"account {account_id!r} has records but no [accounts.{account_id}] "
                "entry in bridge/mapping.toml"
            )
        return mapping


def load_mapping(path: Path) -> BridgeMapping:
    if not path.exists():
        raise FileNotFoundError(f"bridge mapping not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    defaults = data.get("defaults", {})
    uncategorized = defaults.get("uncategorized", "Equity:Uncategorized")
    opening = defaults.get("opening", "Equity:Opening")
    for name, value in (("uncategorized", uncategorized), ("opening", opening)):
        if not is_valid_account(value):
            raise ValueError(f"defaults.{name} is not a valid ledger account: {value!r}")

    accounts: dict[str, AccountMapping] = {}
    for account_id, entry in data.get("accounts", {}).items():
        missing = [k for k in (*_ROLE_KEYS, "cost_method") if k not in entry]
        if missing:
            raise ValueError(f"[accounts.{account_id}] is missing keys: {missing}")
        for key in _ROLE_KEYS:
            if not is_valid_account(entry[key]):
                raise ValueError(
                    f"[accounts.{account_id}].{key} is not a valid ledger "
                    f"account: {entry[key]!r}"
                )
        try:
            method = CostMethod(entry["cost_method"])
        except ValueError:
            raise ValueError(
                f"[accounts.{account_id}].cost_method must be one of "
                f"{sorted(m.value for m in CostMethod)}"
            ) from None
        accounts[account_id] = AccountMapping(
            account_id=account_id,
            positions=entry["positions"],
            cash=entry["cash"],
            pnl=entry["pnl"],
            dividends=entry["dividends"],
            withholding=entry["withholding"],
            cost_method=method,
        )

    # positions/cash/pnl/dividends are reconciled per account_id, so they
    # must be exclusive; withholding is a plain expense and may be shared.
    owned: dict[str, str] = {}
    for mapping in accounts.values():
        for account in (mapping.positions, mapping.cash, mapping.pnl, mapping.dividends):
            other = owned.get(account)
            if other is not None and other != mapping.account_id:
                raise ValueError(
                    f"ledger account {account!r} is mapped by both "
                    f"{other!r} and {mapping.account_id!r}; positions/cash/"
                    "pnl/dividends accounts must be exclusive per account_id"
                )
            owned[account] = mapping.account_id

    return BridgeMapping(accounts=accounts, uncategorized=uncategorized, opening=opening)
