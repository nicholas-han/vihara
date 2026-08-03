import sqlite3
from datetime import date
from pathlib import Path

import pytest

from portfolio_manager.records.identity import new_instrument_id, validate_instrument_id
from portfolio_manager.records.rebuild import create_schema
from portfolio_manager.records.resolver import (
    InstrumentAmbiguousError,
    InstrumentMismatchError,
    InstrumentNotFoundError,
    SQLiteInstrumentResolver,
    resolve_trade_alias,
    resolve_trade_csv_text,
)

AAPL_OLD = "ins_01j3m8w7rx6f4k2p9c5vbn"
AAPL_NEW = "ins_01j3m8x2qd7n5h4t8z6kcp"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.sqlite3"
    create_schema(path)
    return path


def _alias(
    db_path: Path,
    instrument_id: str,
    valid_from: str,
    valid_to: str | None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into instrument_aliases(
                instrument_id, scheme, identifier, valid_from, valid_to
            ) values (?, 'TICKER', 'AAPL.US', ?, ?)
            """,
            (instrument_id, valid_from, valid_to),
        )


def test_new_instrument_ids_are_valid_and_distinct():
    ids = {new_instrument_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(validate_instrument_id(value) == value for value in ids)


def test_resolver_handles_ticker_reuse_by_trade_date(db_path: Path):
    _alias(db_path, AAPL_OLD, "1980-01-01", "2020-01-01")
    _alias(db_path, AAPL_NEW, "2020-01-01", None)
    resolver = SQLiteInstrumentResolver(db_path)

    assert resolver.resolve_instrument_id("aapl", "us", date(2019, 12, 31)) == AAPL_OLD
    assert resolver.resolve_instrument_id("AAPL", "US", date(2020, 1, 1)) == AAPL_NEW


def test_resolver_rejects_missing_mapping(db_path: Path):
    resolver = SQLiteInstrumentResolver(db_path)
    with pytest.raises(InstrumentNotFoundError, match="no instrument mapping"):
        resolver.resolve_instrument_id("AAPL", "US", date(2020, 1, 1))


def test_resolver_rejects_overlapping_mapping(db_path: Path):
    _alias(db_path, AAPL_OLD, "2000-01-01", "2030-01-01")
    _alias(db_path, AAPL_NEW, "2020-01-01", "2040-01-01")
    resolver = SQLiteInstrumentResolver(db_path)

    with pytest.raises(InstrumentAmbiguousError, match="ambiguous instrument mapping"):
        resolver.resolve_instrument_id("AAPL", "US", date(2025, 1, 1))


def test_source_row_resolution_adds_and_checks_internal_id(db_path: Path):
    _alias(db_path, AAPL_NEW, "2020-01-01", None)
    resolver = SQLiteInstrumentResolver(db_path)
    source = {"trade_date": "2025-01-15", "symbol": "AAPL", "market": "US"}

    assert resolve_trade_alias(source, resolver)["instrument_id"] == AAPL_NEW
    with pytest.raises(InstrumentMismatchError, match="does not match"):
        resolve_trade_alias({**source, "instrument_id": AAPL_OLD}, resolver)


def test_resolve_trade_csv_text_adds_column_and_resolves_all_rows(db_path: Path):
    _alias(db_path, AAPL_NEW, "2020-01-01", None)
    source = (
        "schema_version,account_id,trade_date,symbol,market,side,quantity,price,"
        "trade_currency,transaction_fees\n"
        "1,taxable,2025-01-15,AAPL,US,buy,10,175.25,USD,1.00\n"
    )

    resolved = resolve_trade_csv_text(source, SQLiteInstrumentResolver(db_path))

    assert "trade_date,instrument_id,symbol" in resolved.splitlines()[0]
    assert f"2025-01-15,{AAPL_NEW},AAPL,US" in resolved
