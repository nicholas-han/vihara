"""FX conversion for portfolio summaries.

Rates are maintained manually (fx_rates table, CSV import) — there is no live
feed in v2. A missing rate yields None and the caller must surface the amount
as "unconverted"; conversion never silently guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from .models import FxRate


class FxProvider(Protocol):
    def get_fx_rate(self, base_currency: str, quote_currency: str, as_of: date | None = None) -> FxRate | None:
        """Latest stored rate (1 base = rate quote) at/before as_of, or the
        latest available when as_of is None. Direct pairs only — inversion is
        the caller's job (see ``convert``)."""
        ...


@dataclass(frozen=True)
class ConvertedAmount:
    amount: Decimal
    rate_as_of: date


def convert(
    fx: FxProvider,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    as_of: date | None = None,
) -> ConvertedAmount | None:
    if from_currency == to_currency:
        return ConvertedAmount(amount=amount, rate_as_of=as_of or date.today())

    direct = fx.get_fx_rate(from_currency, to_currency, as_of)
    if direct is not None:
        return ConvertedAmount(amount=amount * direct.rate, rate_as_of=direct.as_of)

    inverse = fx.get_fx_rate(to_currency, from_currency, as_of)
    if inverse is not None and inverse.rate != 0:
        return ConvertedAmount(amount=amount / inverse.rate, rate_as_of=inverse.as_of)

    return None
