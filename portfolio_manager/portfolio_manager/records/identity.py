"""Instrument identity for portfolio records.

This is the ONLY module allowed to construct or parse an instrument_id.
Everywhere else instrument_id is an opaque string, so a future
instrument_manager adapter only has to replace this module (mapping through
instrument_aliases, which mirrors instrument_manager's external_identifiers)
without touching callers.

v2 ids are ``{SYMBOL}.{MARKET}`` (e.g. ``AAPL.US``, ``0700.HK``, ``600519.CN``).
"""

from __future__ import annotations

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


def make_instrument_id(symbol: str, market: str) -> str:
    """Build the canonical v2 instrument_id from a symbol and market."""
    cleaned_symbol = symbol.strip().upper()
    cleaned_market = market.strip().upper()
    if not cleaned_symbol:
        raise ValueError("symbol must not be empty")
    if cleaned_market not in VALID_MARKETS:
        raise ValueError(f"market must be one of {sorted(VALID_MARKETS)}")
    return f"{cleaned_symbol}.{cleaned_market}"


def ticker_alias(symbol: str, market: str) -> str:
    """Identifier stored under the TICKER scheme in instrument_aliases."""
    return f"{symbol.strip().upper()}.{market.strip().upper()}"
