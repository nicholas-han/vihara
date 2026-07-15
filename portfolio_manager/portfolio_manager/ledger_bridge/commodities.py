"""Instrument-id <-> ledger-commodity encoding.

beancount currencies must START WITH A LETTER, so pm's ``0700.HK`` cannot
be a commodity verbatim. The encoding reverses the segments:

    instrument_id  SYMBOL.MARKET   (AAPL.US, 0700.HK, BRK.B.US)
    commodity      MARKET.SYMBOL   (US.AAPL, HK.0700, US.BRK.B)

Markets are a fixed letter-only set, so the commodity always starts with a
letter; decode splits on the FIRST dot. This module is the only place the
encoding exists; the ledger itself treats commodities as opaque.
"""

from __future__ import annotations

import re

from ..records.identity import VALID_MARKETS, make_instrument_id, split_instrument_id

# beancount currency lexeme (ledger.core.model.CURRENCY_RE keeps the same).
_COMMODITY_RE = re.compile(r"[A-Z](?:[A-Z0-9'._\-]{0,22}[A-Z0-9])?")


def to_commodity(instrument_id: str) -> str:
    symbol, market = split_instrument_id(instrument_id)
    commodity = f"{market}.{symbol}"
    if _COMMODITY_RE.fullmatch(commodity) is None:
        raise ValueError(
            f"instrument_id {instrument_id!r} does not encode to a valid "
            f"ledger commodity ({commodity!r}); symbols must be <= 21 chars "
            "of [A-Z0-9'._-] ending alphanumeric"
        )
    return commodity


def from_commodity(commodity: str) -> str:
    market, sep, symbol = commodity.partition(".")
    if not sep or market not in VALID_MARKETS:
        raise ValueError(f"not an instrument commodity: {commodity!r}")
    return make_instrument_id(symbol, market)
