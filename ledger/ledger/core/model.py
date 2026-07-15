"""Core data model: amounts, cost specs, postings, and directives.

All value types are frozen dataclasses; all numbers are ``decimal.Decimal``
(never float). Directives carry a ``SourcePos`` so every later error can point
at file:line. This module holds parsed, unbooked data only — booking results
live in ``ledger.booking``.

Syntax is a beancount-compatible subset; extensions ride on metadata
(see docs/10-syntax-subset.md).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Union

from ..errors import SourcePos

# Beancount currency lexeme: starts with an uppercase letter, ends with a
# letter or digit, <= 24 chars total, inner chars may add digits and '._-.
CURRENCY_RE = re.compile(r"[A-Z](?:[A-Z0-9'._\-]{0,22}[A-Z0-9])?")


def is_valid_currency(name: str) -> bool:
    return CURRENCY_RE.fullmatch(name) is not None


MetaValue = Union[str, Decimal, datetime.date, "Amount", bool]
Meta = dict[str, MetaValue]


@dataclass(frozen=True)
class Amount:
    number: Decimal
    currency: str

    def __str__(self) -> str:
        return f"{format(self.number, 'f')} {self.currency}"


@dataclass(frozen=True)
class CostSpec:
    """Contents of a ``{...}`` / ``{{...}}`` cost annotation.

    On an augmenting posting the spec defines the new lot (``number`` required;
    ``is_total`` distinguishes ``{{total}}`` from ``{per-unit}``). On a
    reducing posting the spec is a lot matcher: any provided component
    (number, date, label) filters candidate lots. An empty ``{}`` matches all.
    """

    number: Decimal | None = None
    currency: str | None = None
    date: datetime.date | None = None
    label: str | None = None
    is_total: bool = False

    @property
    def is_empty(self) -> bool:
        return self.number is None and self.date is None and self.label is None


@dataclass(frozen=True)
class Posting:
    account: str
    units: Amount | None = None  # None = elided, interpolated at booking
    cost: CostSpec | None = None
    price: Amount | None = None  # per-unit unless price_is_total
    price_is_total: bool = False
    flag: str | None = None
    meta: Meta = field(default_factory=dict)


@dataclass(frozen=True)
class Directive:
    date: datetime.date
    meta: Meta
    pos: SourcePos


@dataclass(frozen=True)
class Open(Directive):
    account: str = ""
    currencies: tuple[str, ...] = ()
    booking: str | None = None


@dataclass(frozen=True)
class Close(Directive):
    account: str = ""


@dataclass(frozen=True)
class Commodity(Directive):
    currency: str = ""


@dataclass(frozen=True)
class Transaction(Directive):
    flag: str = "*"
    payee: str | None = None
    narration: str = ""
    tags: frozenset[str] = frozenset()
    links: frozenset[str] = frozenset()
    postings: tuple[Posting, ...] = ()


@dataclass(frozen=True)
class Balance(Directive):
    account: str = ""
    amount: Amount = None  # type: ignore[assignment]  # always set by parser
    tolerance: Decimal | None = None


@dataclass(frozen=True)
class Price(Directive):
    currency: str = ""
    amount: Amount = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Note(Directive):
    account: str = ""
    comment: str = ""


@dataclass(frozen=True)
class Document(Directive):
    account: str = ""
    filename: str = ""


# Loader-level statements (no date, not part of the directive stream).


@dataclass(frozen=True)
class Option:
    name: str
    value: str
    pos: SourcePos


@dataclass(frozen=True)
class Include:
    filename: str
    pos: SourcePos


# Ordering: within one date, account state changes frame the day —
# open first, then balance assertions (asserted "at start of day"),
# then the day's activity, and close last.
_TYPE_ORDER = {Open: 0, Commodity: 0, Balance: 1, Close: 3}


def sort_key(directive: Directive) -> tuple:
    return (
        directive.date,
        _TYPE_ORDER.get(type(directive), 2),
        directive.pos.file,
        directive.pos.line,
    )
