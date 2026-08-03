"""Reversible instrument-id <-> ledger-commodity encoding.

Portfolio IDs are ``ins_`` plus 22 lowercase Crockford Base32 characters.
Ledger commodities are the same opaque payload prefixed by ``I`` and uppercased;
no ticker or market information is encoded in either identifier.
"""

from __future__ import annotations

import re

from ..records.identity import validate_instrument_id

# beancount currency lexeme (ledger.core.model.CURRENCY_RE keeps the same).
_COMMODITY_RE = re.compile(r"[A-Z](?:[A-Z0-9'._\-]{0,22}[A-Z0-9])?")


def to_commodity(instrument_id: str) -> str:
    canonical = validate_instrument_id(instrument_id)
    commodity = "I" + canonical.removeprefix("ins_").upper()
    if _COMMODITY_RE.fullmatch(commodity) is None:
        raise ValueError(
            f"instrument_id {instrument_id!r} does not encode to a valid "
            f"ledger commodity ({commodity!r})"
        )
    return commodity


def from_commodity(commodity: str) -> str:
    if re.fullmatch(r"I[0-9A-HJKMNP-TV-Z]{22}", commodity) is None:
        raise ValueError(f"not an instrument commodity: {commodity!r}")
    return validate_instrument_id("ins_" + commodity[1:].lower())
