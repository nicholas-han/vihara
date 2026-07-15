"""Booking: apply the sorted directive stream to account inventories.

Responsibilities:
- account lifecycle (open/close, currency constraints, booking method);
- interpolation of at most one elided posting amount per transaction;
- lot creation (augmentation) and lot reduction per the account's method;
- per-transaction balance check: weights sum to ~zero per currency;
- balance assertions, checked at the start of their date.

Booking methods
---------------
STRICT (default)  reductions must match exactly one lot via the cost spec.
FIFO              reductions consume matching lots oldest-first.
AVERAGE_POOL      all lots merge into one pool per (commodity, cost currency);
                  reductions consume proportional pool cost. Journal files
                  declare this as booking "NONE" (a beancount-legal string;
                  beancount performs no matching for NONE, we give it pool
                  semantics — see docs/20-model-and-booking.md). "AVERAGE"
                  is accepted as an alias.

Weight rules (beancount-compatible)
-----------------------------------
- posting with a cost: weight = signed total cost in the cost currency;
- else with a price: weight = units x price (@) or the total (@@);
- else: weight = units.

Transaction residuals must stay within a tolerance inferred per currency as
half the last decimal place of the most precise literal written in that
currency (explicit units, total costs, total prices); zero when no literal
exists. Balance assertions use half the last place of the asserted literal
unless an explicit ``~ tolerance`` is given.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .core import model
from .core.inventory import ZERO, Inventory, Lot
from .errors import LedgerError, Severity

HALF = Decimal("0.5")


class BookingMethod(Enum):
    STRICT = "STRICT"
    FIFO = "FIFO"
    AVERAGE_POOL = "AVERAGE_POOL"


_METHOD_ALIASES = {
    None: BookingMethod.STRICT,
    "STRICT": BookingMethod.STRICT,
    "FIFO": BookingMethod.FIFO,
    "NONE": BookingMethod.AVERAGE_POOL,
    "AVERAGE": BookingMethod.AVERAGE_POOL,
}


@dataclass
class AccountState:
    open: model.Open
    close: model.Close | None = None
    method: BookingMethod = BookingMethod.STRICT


@dataclass(frozen=True)
class ResolvedPosting:
    """A posting after interpolation and lot resolution."""

    account: str
    units: model.Amount
    weight: model.Amount
    cost_total: Decimal | None = None  # signed: + acquired, - consumed
    cost_currency: str | None = None
    cost_date: datetime.date | None = None
    cost_label: str | None = None
    price: model.Amount | None = None
    meta: model.Meta = field(default_factory=dict)


@dataclass
class BookedTransaction:
    txn: model.Transaction
    postings: list[ResolvedPosting]


@dataclass
class BookResult:
    accounts: dict[str, AccountState] = field(default_factory=dict)
    inventories: dict[str, Inventory] = field(default_factory=dict)
    booked: list[BookedTransaction] = field(default_factory=list)
    prices: dict[tuple[str, str], list[tuple[datetime.date, Decimal]]] = field(
        default_factory=dict
    )
    commodities: dict[str, model.Commodity] = field(default_factory=dict)
    errors: list[LedgerError] = field(default_factory=list)


def book(directives: list[model.Directive]) -> BookResult:
    """Book a date-sorted directive stream (see ``loader.load``)."""
    return _Booker().run(directives)


def _decimal_places(number: Decimal) -> int:
    exponent = number.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _literal_tolerance(number: Decimal) -> Decimal:
    """Half the last decimal place of a literal (1751.00 -> 0.005, 10 -> 0.5)."""
    return HALF.scaleb(-_decimal_places(number))


class _Booker:
    def __init__(self) -> None:
        self.result = BookResult()

    def _error(self, message: str, directive: model.Directive) -> None:
        self.result.errors.append(
            LedgerError(Severity.ERROR, message, directive.pos)
        )

    def _warn(self, message: str, directive: model.Directive) -> None:
        self.result.errors.append(
            LedgerError(Severity.WARNING, message, directive.pos)
        )

    def _inventory(self, account: str) -> Inventory:
        return self.result.inventories.setdefault(account, Inventory())

    def run(self, directives: list[model.Directive]) -> BookResult:
        for directive in directives:
            if isinstance(directive, model.Open):
                self._do_open(directive)
            elif isinstance(directive, model.Close):
                self._do_close(directive)
            elif isinstance(directive, model.Commodity):
                self._do_commodity(directive)
            elif isinstance(directive, model.Balance):
                self._do_balance(directive)
            elif isinstance(directive, model.Price):
                pair = (directive.currency, directive.amount.currency)
                self.result.prices.setdefault(pair, []).append(
                    (directive.date, directive.amount.number)
                )
            elif isinstance(directive, model.Transaction):
                self._do_transaction(directive)
            # Note / Document need no booking work.
        return self.result

    # -- account lifecycle -----------------------------------------------

    def _do_open(self, directive: model.Open) -> None:
        if directive.account in self.result.accounts:
            self._error(f"account {directive.account} already opened", directive)
            return
        method = _METHOD_ALIASES.get(directive.booking)
        if method is None:
            self._error(
                f"unknown booking method {directive.booking!r} "
                "(expected STRICT, FIFO, NONE or AVERAGE)",
                directive,
            )
            method = BookingMethod.STRICT
        self.result.accounts[directive.account] = AccountState(directive, None, method)

    def _do_close(self, directive: model.Close) -> None:
        state = self.result.accounts.get(directive.account)
        if state is None:
            self._error(f"closing unopened account {directive.account}", directive)
            return
        if state.close is not None:
            self._error(f"account {directive.account} already closed", directive)
            return
        state.close = directive
        inventory = self.result.inventories.get(directive.account)
        if inventory is not None and not inventory.is_empty():
            self._warn(
                f"account {directive.account} closed with a non-empty balance",
                directive,
            )

    def _do_commodity(self, directive: model.Commodity) -> None:
        if directive.currency in self.result.commodities:
            self._error(f"commodity {directive.currency} already declared", directive)
            return
        self.result.commodities[directive.currency] = directive

    def _check_account_usable(
        self, account: str, directive: model.Directive
    ) -> AccountState | None:
        state = self.result.accounts.get(account)
        if state is None:
            self._error(f"account {account} is not opened", directive)
            return None
        if directive.date < state.open.date:
            self._error(
                f"account {account} used before its open date {state.open.date}",
                directive,
            )
        if state.close is not None and directive.date > state.close.date:
            self._error(
                f"account {account} used after its close date {state.close.date}",
                directive,
            )
        return state

    # -- balance assertions ------------------------------------------------

    def _do_balance(self, directive: model.Balance) -> None:
        self._check_account_usable(directive.account, directive)
        inventory = self._inventory(directive.account)
        actual = inventory.units_of(directive.amount.currency)
        tolerance = (
            directive.tolerance
            if directive.tolerance is not None
            else _literal_tolerance(directive.amount.number)
        )
        difference = actual - directive.amount.number
        if abs(difference) > tolerance:
            self._error(
                f"balance assertion failed for {directive.account}: "
                f"expected {directive.amount}, actual "
                f"{format(actual, 'f')} {directive.amount.currency} "
                f"(difference {format(difference, 'f')})",
                directive,
            )

    # -- transactions ------------------------------------------------------

    def _do_transaction(self, txn: model.Transaction) -> None:
        postings = self._interpolate(txn)
        if postings is None:
            return

        resolved: list[ResolvedPosting] = []
        for posting in postings:
            state = self._check_account_usable(posting.account, txn)
            method = state.method if state else BookingMethod.STRICT
            if state is not None and state.open.currencies:
                assert posting.units is not None
                if posting.units.currency not in state.open.currencies:
                    self._error(
                        f"currency {posting.units.currency} not allowed in "
                        f"{posting.account} (open declares "
                        f"{', '.join(state.open.currencies)})",
                        txn,
                    )
            resolved.append(self._book_posting(posting, method, txn))

        self._check_balance(txn, resolved)
        self.result.booked.append(BookedTransaction(txn, resolved))

    def _interpolate(self, txn: model.Transaction) -> list[model.Posting] | None:
        """Fill in at most one elided posting amount; returns None on error."""
        elided = [p for p in txn.postings if p.units is None]
        if len(elided) > 1:
            self._error("more than one posting without an amount", txn)
            return None
        if not elided:
            return list(txn.postings)

        residual: dict[str, Decimal] = {}
        for posting in txn.postings:
            if posting.units is None:
                continue
            if posting.cost is not None and (
                posting.units.number < ZERO or posting.cost.number is None
            ):
                # A reduction's true weight is only known after lot matching;
                # interpolating around it would be silently wrong.
                self._error(
                    "an elided amount cannot be combined with a lot reduction "
                    "in the same transaction; write the amount explicitly",
                    txn,
                )
                return None
            weight = self._weight_of(posting, txn)
            residual[weight.currency] = (
                residual.get(weight.currency, ZERO) + weight.number
            )
        nonzero = {c: n for c, n in residual.items() if n != ZERO}
        if len(nonzero) != 1:
            self._error(
                "cannot infer the elided amount: residual is "
                + (
                    "zero in every currency"
                    if not nonzero
                    else f"in multiple currencies ({', '.join(sorted(nonzero))})"
                ),
                txn,
            )
            return None
        ((currency, number),) = nonzero.items()
        filled = model.Posting(
            elided[0].account,
            model.Amount(-number, currency),
            flag=elided[0].flag,
            meta=elided[0].meta,
        )
        return [filled if p.units is None else p for p in txn.postings]

    def _weight_of(self, posting: model.Posting, txn: model.Transaction) -> model.Amount:
        """Weight of a posting WITHOUT booking lots (used for interpolation).

        For cost postings this uses the spec for augmentations; reductions
        get their true weight during booking, so elided amounts alongside
        reductions are not supported (kept simple deliberately).
        """
        assert posting.units is not None
        units = posting.units
        if posting.cost is not None and posting.cost.number is not None:
            total = (
                posting.cost.number
                if posting.cost.is_total
                else posting.cost.number * units.number.copy_abs()
            )
            sign = -1 if units.number < ZERO else 1
            assert posting.cost.currency is not None
            return model.Amount(sign * total, posting.cost.currency)
        if posting.price is not None:
            if posting.price_is_total:
                sign = -1 if units.number < ZERO else 1
                return model.Amount(sign * posting.price.number, posting.price.currency)
            return model.Amount(
                units.number * posting.price.number, posting.price.currency
            )
        return units

    # -- posting booking ---------------------------------------------------

    def _book_posting(
        self,
        posting: model.Posting,
        method: BookingMethod,
        txn: model.Transaction,
    ) -> ResolvedPosting:
        assert posting.units is not None
        units = posting.units
        inventory = self._inventory(posting.account)

        if posting.cost is None:
            if units.number != ZERO and inventory.lots_of(units.currency):
                self._warn(
                    f"posting {units} to {posting.account} without a cost spec "
                    "while lots of that commodity are held at cost",
                    txn,
                )
            inventory.add_cash(units.number, units.currency)
            weight = self._weight_of(posting, txn)
            return ResolvedPosting(
                posting.account, units, weight, price=posting.price, meta=posting.meta
            )

        if units.number > ZERO:
            return self._book_augmentation(posting, method, inventory, txn)
        if units.number < ZERO:
            return self._book_reduction(posting, method, inventory, txn)
        # Zero units with a cost spec: meaningless but harmless.
        return ResolvedPosting(
            posting.account, units, model.Amount(ZERO, units.currency), meta=posting.meta
        )

    def _book_augmentation(
        self,
        posting: model.Posting,
        method: BookingMethod,
        inventory: Inventory,
        txn: model.Transaction,
    ) -> ResolvedPosting:
        assert posting.units is not None and posting.cost is not None
        units, spec = posting.units, posting.cost
        if spec.number is None or spec.currency is None:
            self._error(
                f"cost amount required to acquire {units} in {posting.account}",
                txn,
            )
            return ResolvedPosting(
                posting.account, units, model.Amount(ZERO, units.currency),
                meta=posting.meta,
            )
        cost_total = spec.number if spec.is_total else spec.number * units.number
        lot_date = spec.date if spec.date is not None else txn.date

        if method is BookingMethod.AVERAGE_POOL:
            pool = self._find_pool(inventory, units.currency, spec.currency)
            if pool is None:
                inventory.add_lot(
                    Lot(units.currency, units.number, cost_total, spec.currency,
                        None, None)
                )
            else:
                inventory.lots[inventory.lots.index(pool)] = Lot(
                    pool.commodity,
                    pool.units + units.number,
                    pool.cost_total + cost_total,
                    pool.cost_currency,
                    None,
                    None,
                )
        else:
            inventory.add_lot(
                Lot(units.currency, units.number, cost_total, spec.currency,
                    lot_date, spec.label)
            )

        weight = model.Amount(cost_total, spec.currency)
        return ResolvedPosting(
            posting.account,
            units,
            weight,
            cost_total=cost_total,
            cost_currency=spec.currency,
            cost_date=lot_date,
            cost_label=spec.label,
            price=posting.price,
            meta=posting.meta,
        )

    def _find_pool(
        self, inventory: Inventory, commodity: str, cost_currency: str
    ) -> Lot | None:
        for lot in inventory.lots:
            if lot.commodity == commodity and lot.cost_currency == cost_currency:
                return lot
        return None

    def _book_reduction(
        self,
        posting: model.Posting,
        method: BookingMethod,
        inventory: Inventory,
        txn: model.Transaction,
    ) -> ResolvedPosting:
        assert posting.units is not None and posting.cost is not None
        units, spec = posting.units, posting.cost
        needed = -units.number  # positive quantity to remove

        candidates = self._match_lots(inventory, units.currency, spec, method)
        available = sum((lot.units for lot in candidates), ZERO)
        cost_currency = (
            candidates[0].cost_currency if candidates else (spec.currency or "")
        )

        if not candidates:
            self._error(
                f"no lot of {units.currency} in {posting.account} matches the "
                "cost spec",
                txn,
            )
            return ResolvedPosting(
                posting.account, units,
                model.Amount(ZERO, cost_currency or units.currency),
                price=posting.price, meta=posting.meta,
            )
        if method is BookingMethod.STRICT and len(candidates) > 1:
            self._error(
                f"ambiguous lot reduction of {units.currency} in "
                f"{posting.account}: {len(candidates)} lots match "
                "(add a date or label to the cost spec)",
                txn,
            )
            return ResolvedPosting(
                posting.account, units, model.Amount(ZERO, cost_currency),
                price=posting.price, meta=posting.meta,
            )
        if needed > available:
            self._error(
                f"overdrawn reduction of {units.currency} in {posting.account}: "
                f"removing {format(needed, 'f')}, holding {format(available, 'f')}",
                txn,
            )
            return ResolvedPosting(
                posting.account, units, model.Amount(ZERO, cost_currency),
                price=posting.price, meta=posting.meta,
            )

        # Consume candidates in order (STRICT: single lot; FIFO: oldest first;
        # AVERAGE_POOL: the single pool).
        remaining = needed
        consumed_cost = ZERO
        first = candidates[0]
        for lot in candidates:
            if remaining == ZERO:
                break
            take = min(remaining, lot.units)
            if take == lot.units:
                piece_cost = lot.cost_total
            else:
                piece_cost = lot.cost_total * take / lot.units
            inventory.reduce_lot(lot, take, piece_cost)
            consumed_cost += piece_cost
            remaining -= take

        weight = model.Amount(-consumed_cost, first.cost_currency)
        return ResolvedPosting(
            posting.account,
            units,
            weight,
            cost_total=-consumed_cost,
            cost_currency=first.cost_currency,
            cost_date=first.date,
            cost_label=first.label,
            price=posting.price,
            meta=posting.meta,
        )

    def _match_lots(
        self,
        inventory: Inventory,
        commodity: str,
        spec: model.CostSpec,
        method: BookingMethod,
    ) -> list[Lot]:
        lots = inventory.lots_of(commodity)
        if method is BookingMethod.AVERAGE_POOL:
            return lots  # the pool (matchers carry no meaning for a pool)
        matched = []
        for lot in lots:
            if spec.date is not None and lot.date != spec.date:
                continue
            if spec.label is not None and lot.label != spec.label:
                continue
            if spec.number is not None:
                if spec.is_total:
                    if lot.cost_total != spec.number:
                        continue
                elif lot.cost_total != spec.number * lot.units:
                    continue
            matched.append(lot)
        if method is BookingMethod.FIFO:
            matched.sort(key=lambda lot: (lot.date or datetime.date.min))
        return matched

    # -- transaction balance ------------------------------------------------

    def _check_balance(
        self, txn: model.Transaction, postings: list[ResolvedPosting]
    ) -> None:
        residuals: dict[str, Decimal] = {}
        for rp in postings:
            residuals[rp.weight.currency] = (
                residuals.get(rp.weight.currency, ZERO) + rp.weight.number
            )
        tolerances = self._tolerances(txn)
        for currency, residual in residuals.items():
            if residual == ZERO:
                continue
            if abs(residual) > tolerances.get(currency, ZERO):
                self._error(
                    f"transaction does not balance: {format(residual, 'f')} "
                    f"{currency} left over",
                    txn,
                )

    def _tolerances(self, txn: model.Transaction) -> dict[str, Decimal]:
        """Per-currency tolerance from literals written in that currency:
        explicit units, total costs ({{...}}), and total prices (@@).
        Per-unit cost/price numbers deliberately do not contribute — their
        precision says nothing about the converted total's precision."""
        places: dict[str, int] = {}

        def observe(currency: str, number: Decimal) -> None:
            places[currency] = max(
                places.get(currency, -1), _decimal_places(number)
            )

        for posting in txn.postings:
            if posting.units is None:
                continue
            observe(posting.units.currency, posting.units.number)
            cost = posting.cost
            if cost is not None and cost.number is not None and cost.is_total:
                assert cost.currency is not None
                observe(cost.currency, cost.number)
            if posting.price is not None and posting.price_is_total:
                observe(posting.price.currency, posting.price.number)
        return {
            currency: HALF.scaleb(-decimals)
            for currency, decimals in places.items()
            if decimals >= 0
        }
