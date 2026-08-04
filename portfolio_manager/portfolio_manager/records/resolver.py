"""Effective-dated instrument alias resolution.

Canonical records carry stable instrument ids. Source adapters use this module
to turn a mutable ticker plus record date into exactly one such id.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from pathlib import Path
from typing import Mapping, Protocol

from .identity import VALID_MARKETS, ticker_alias, validate_instrument_id


class InstrumentResolutionError(ValueError):
    """Base class for deterministic, user-fixable resolution failures."""


class InstrumentNotFoundError(InstrumentResolutionError):
    pass


class InstrumentAmbiguousError(InstrumentResolutionError):
    pass


class InstrumentMismatchError(InstrumentResolutionError):
    pass


class InstrumentAliasOverlapError(InstrumentResolutionError):
    pass


class InstrumentResolver(Protocol):
    def resolve_instrument_id(self, symbol: str, market: str, as_of: date) -> str: ...


class SQLiteInstrumentResolver:
    """Resolve against the portfolio-side projection of instrument aliases."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def resolve_instrument_id(self, symbol: str, market: str, as_of: date) -> str:
        with sqlite3.connect(self.db_path) as conn:
            return resolve_instrument_id(conn, symbol, market, as_of)


def resolve_instrument_id(
    conn: sqlite3.Connection,
    symbol: str,
    market: str,
    as_of: date,
) -> str:
    normalized_market = market.strip().upper()
    if normalized_market not in VALID_MARKETS:
        raise InstrumentNotFoundError(
            f"unsupported market {market!r}; expected one of {sorted(VALID_MARKETS)}"
        )
    identifier = ticker_alias(symbol, normalized_market)
    as_of_text = as_of.isoformat()
    rows = conn.execute(
        """
        select distinct instrument_id
        from instrument_aliases
        where scheme = 'TICKER'
          and identifier = ?
          and valid_from <= ?
          and (valid_to is null or ? < valid_to)
        order by instrument_id
        """,
        (identifier, as_of_text, as_of_text),
    ).fetchall()
    instrument_ids = [validate_instrument_id(str(row[0])) for row in rows]
    if not instrument_ids:
        raise InstrumentNotFoundError(
            f"no instrument mapping for {identifier} on {as_of_text}"
        )
    if len(instrument_ids) > 1:
        raise InstrumentAmbiguousError(
            f"ambiguous instrument mapping for {identifier} on {as_of_text}: "
            f"{instrument_ids}"
        )
    return instrument_ids[0]


def ensure_alias_available(
    conn: sqlite3.Connection,
    identifier: str,
    valid_from: date,
    valid_to: date | None = None,
) -> None:
    """Reject any overlap with the proposed half-open validity interval."""
    start = valid_from.isoformat()
    end = valid_to.isoformat() if valid_to is not None else None
    conflict = conn.execute(
        """
        select instrument_id, valid_from, valid_to
        from instrument_aliases
        where scheme = 'TICKER'
          and identifier = ?
          and (? is null or valid_from < ?)
          and (valid_to is null or ? < valid_to)
        limit 1
        """,
        (identifier, end, end, start),
    ).fetchone()
    if conflict is not None:
        raise InstrumentAliasOverlapError(
            f"cannot register {identifier} for [{start}, {end or 'infinity'}); "
            f"it overlaps mapping to {conflict[0]}"
        )


def resolve_trade_alias(
    row: Mapping[str, str],
    resolver: InstrumentResolver,
) -> dict[str, str]:
    """Add/verify instrument_id while converting a source trade row.

    This helper operates before canonical CSV parsing. It never guesses an id:
    missing and ambiguous aliases remain explicit conversion errors.
    """
    resolved = resolver.resolve_instrument_id(
        _required(row, "symbol"),
        _required(row, "market"),
        _trade_date(row),
    )
    supplied = row.get("instrument_id", "").strip()
    if supplied:
        supplied = validate_instrument_id(supplied)
        if supplied != resolved:
            raise InstrumentMismatchError(
                f"supplied instrument_id {supplied} does not match resolved id {resolved}"
            )
    return {**row, "instrument_id": resolved}


def resolve_trade_csv_text(text: str, resolver: InstrumentResolver) -> str:
    """Resolve every source row and return CSV with an instrument_id column."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise InstrumentResolutionError("trade CSV is missing a header")
    fieldnames = list(reader.fieldnames)
    if "instrument_id" not in fieldnames:
        anchor = "settle_date" if "settle_date" in fieldnames else "trade_date"
        try:
            fieldnames.insert(fieldnames.index(anchor) + 1, "instrument_id")
        except ValueError as exc:
            raise InstrumentResolutionError(
                "trade CSV requires trade_date before instruments can be resolved"
            ) from exc

    rows = [resolve_trade_alias(row, resolver) for row in reader]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _required(row: Mapping[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise InstrumentResolutionError(f"{key} is required for instrument resolution")
    return value


def _trade_date(row: Mapping[str, str]) -> date:
    value = _required(row, "trade_date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InstrumentResolutionError(
            f"trade_date must use YYYY-MM-DD, got {value!r}"
        ) from exc
