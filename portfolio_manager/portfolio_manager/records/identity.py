"""Instrument identity rules for portfolio records.

An instrument_id is an opaque, stable identifier. It never embeds a ticker,
market, venue, or company name; those mutable values belong in identifier
mappings owned by instrument_manager.
"""

from __future__ import annotations

import re
import secrets

# Markets supported by the records app. UNKNOWN is a storage-side fallback for
# legacy rows only — imports and id construction reject it.
VALID_MARKETS = frozenset({"US", "HK", "CN"})
VALID_CURRENCIES = frozenset({"USD", "HKD", "CNY"})

MARKET_DEFAULT_CURRENCY = {
    "US": "USD",
    "HK": "HKD",
    "CN": "CNY",
}

TICKER_SCHEME = "TICKER"

# 110 bits in Crockford Base32. Lowercase is canonical; the omitted letters
# make IDs easier to read and transcribe without changing their opacity.
INSTRUMENT_ID_RE = re.compile(r"ins_[0-9a-hjkmnp-tv-z]{22}")
_CROCKFORD_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def new_instrument_id() -> str:
    """Allocate a random opaque id with approximately 110 bits of entropy."""
    return "ins_" + "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(22))


def validate_instrument_id(instrument_id: str) -> str:
    """Return a canonical internal id or reject aliases masquerading as ids."""
    value = instrument_id.strip()
    if INSTRUMENT_ID_RE.fullmatch(value) is None:
        raise ValueError(
            "instrument_id must use the internal format "
            "'ins_' + 22 lowercase Crockford Base32 characters"
        )
    return value


def ticker_alias(symbol: str, market: str) -> str:
    """Identifier stored under the TICKER scheme in instrument_aliases."""
    return f"{symbol.strip().upper()}.{market.strip().upper()}"
