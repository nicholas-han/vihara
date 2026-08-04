"""Controlled creation of portfolio instruments and their initial aliases."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .identity import (
    MARKET_DEFAULT_CURRENCY,
    VALID_CURRENCIES,
    VALID_MARKETS,
    new_instrument_id,
    ticker_alias,
    validate_instrument_id,
)
from .resolver import ensure_alias_available


@dataclass(frozen=True)
class InstrumentRegistration:
    instrument_id: str
    symbol: str
    market: str
    name: str
    currency: str
    valid_from: date


class SQLiteInstrumentRegistry:
    """Small local registry; replaceable by the instrument_manager adapter."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def register(
        self,
        *,
        symbol: str,
        market: str,
        name: str,
        valid_from: date,
        currency: str | None = None,
        instrument_id: str | None = None,
    ) -> InstrumentRegistration:
        normalized_symbol = symbol.strip().upper()
        normalized_market = market.strip().upper()
        normalized_name = name.strip()
        if not normalized_symbol:
            raise ValueError("symbol must not be empty")
        if normalized_market not in VALID_MARKETS:
            raise ValueError(f"market must be one of {sorted(VALID_MARKETS)}")
        if not normalized_name:
            raise ValueError("name must not be empty")
        normalized_currency = (
            currency.strip().upper()
            if currency is not None
            else MARKET_DEFAULT_CURRENCY[normalized_market]
        )
        if normalized_currency not in VALID_CURRENCIES:
            raise ValueError(f"currency must be one of {sorted(VALID_CURRENCIES)}")
        stable_id = (
            validate_instrument_id(instrument_id)
            if instrument_id is not None
            else new_instrument_id()
        )
        identifier = ticker_alias(normalized_symbol, normalized_market)

        with sqlite3.connect(self.db_path) as conn:
            ensure_alias_available(conn, identifier, valid_from)
            try:
                conn.execute(
                    """
                    insert into instruments(
                        instrument_id, symbol, name, market, currency, status
                    ) values (?, ?, ?, ?, ?, 'ACTIVE')
                    """,
                    (
                        stable_id,
                        normalized_symbol,
                        normalized_name,
                        normalized_market,
                        normalized_currency,
                    ),
                )
                conn.execute(
                    """
                    insert into instrument_aliases(
                        instrument_id, scheme, identifier, valid_from
                    ) values (?, 'TICKER', ?, ?)
                    """,
                    (stable_id, identifier, valid_from.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"instrument_id {stable_id} is already registered"
                ) from exc

        return InstrumentRegistration(
            instrument_id=stable_id,
            symbol=normalized_symbol,
            market=normalized_market,
            name=normalized_name,
            currency=normalized_currency,
            valid_from=valid_from,
        )

    def add_ticker_alias(
        self,
        *,
        instrument_id: str,
        symbol: str,
        market: str,
        valid_from: date,
        valid_to: date | None = None,
    ) -> None:
        stable_id = validate_instrument_id(instrument_id)
        normalized_symbol, normalized_market = _ticker(symbol, market)
        if valid_to is not None and valid_to <= valid_from:
            raise ValueError("valid_to must be later than valid_from")
        identifier = ticker_alias(normalized_symbol, normalized_market)

        with sqlite3.connect(self.db_path) as conn:
            exists = conn.execute(
                "select 1 from instruments where instrument_id = ?", (stable_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"unknown instrument_id {stable_id}")
            ensure_alias_available(conn, identifier, valid_from, valid_to)
            conn.execute(
                """
                insert into instrument_aliases(
                    instrument_id, scheme, identifier, valid_from, valid_to
                ) values (?, 'TICKER', ?, ?, ?)
                """,
                (
                    stable_id,
                    identifier,
                    valid_from.isoformat(),
                    valid_to.isoformat() if valid_to is not None else None,
                ),
            )
            if valid_to is None:
                conn.execute(
                    """
                    update instruments set symbol = ?, market = ?
                    where instrument_id = ?
                    """,
                    (normalized_symbol, normalized_market, stable_id),
                )

    def close_ticker_alias(
        self,
        *,
        symbol: str,
        market: str,
        valid_to: date,
    ) -> str:
        normalized_symbol, normalized_market = _ticker(symbol, market)
        identifier = ticker_alias(normalized_symbol, normalized_market)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                select instrument_id, valid_from
                from instrument_aliases
                where scheme = 'TICKER' and identifier = ? and valid_to is null
                """,
                (identifier,),
            ).fetchall()
            if not rows:
                raise ValueError(f"no active ticker alias {identifier}")
            if len(rows) > 1:
                raise ValueError(f"multiple active ticker aliases found for {identifier}")
            instrument_id, valid_from_text = rows[0]
            if valid_to <= date.fromisoformat(valid_from_text):
                raise ValueError("valid_to must be later than the alias valid_from")
            conn.execute(
                """
                update instrument_aliases set valid_to = ?
                where scheme = 'TICKER' and identifier = ? and valid_to is null
                """,
                (valid_to.isoformat(), identifier),
            )
        return str(instrument_id)


def _ticker(symbol: str, market: str) -> tuple[str, str]:
    normalized_symbol = symbol.strip().upper()
    normalized_market = market.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be empty")
    if normalized_market not in VALID_MARKETS:
        raise ValueError(f"market must be one of {sorted(VALID_MARKETS)}")
    return normalized_symbol, normalized_market
