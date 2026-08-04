from datetime import date
from pathlib import Path

import pytest

from portfolio_manager.records.instrument_registry import SQLiteInstrumentRegistry
from portfolio_manager.records.rebuild import create_schema
from portfolio_manager.records.resolver import (
    InstrumentAliasOverlapError,
    SQLiteInstrumentResolver,
)


@pytest.fixture()
def registry(tmp_path: Path) -> SQLiteInstrumentRegistry:
    db_path = tmp_path / "instruments.sqlite3"
    create_schema(db_path)
    return SQLiteInstrumentRegistry(db_path)


def test_register_allocates_id_and_resolvable_alias(registry: SQLiteInstrumentRegistry):
    result = registry.register(
        symbol="aapl",
        market="us",
        name="Apple Inc.",
        valid_from=date(1980, 12, 12),
    )
    resolver = SQLiteInstrumentResolver(registry.db_path)

    assert result.instrument_id.startswith("ins_")
    assert result.currency == "USD"
    assert resolver.resolve_instrument_id("AAPL", "US", date(2025, 1, 1)) == result.instrument_id


def test_register_accepts_preallocated_id(registry: SQLiteInstrumentRegistry):
    instrument_id = "ins_01j3m8w7rx6f4k2p9c5vbn"
    result = registry.register(
        instrument_id=instrument_id,
        symbol="0700",
        market="HK",
        name="Tencent Holdings Ltd.",
        valid_from=date(2004, 6, 16),
    )

    assert result.instrument_id == instrument_id
    assert result.currency == "HKD"


def test_alias_collision_rolls_back_registration(registry: SQLiteInstrumentRegistry):
    first = registry.register(
        symbol="AAPL",
        market="US",
        name="First Issuer",
        valid_from=date(1980, 1, 1),
    )

    with pytest.raises(InstrumentAliasOverlapError, match="overlaps mapping"):
        registry.register(
            symbol="AAPL",
            market="US",
            name="Second Issuer",
            valid_from=date(2025, 1, 1),
        )

    resolver = SQLiteInstrumentResolver(registry.db_path)
    assert resolver.resolve_instrument_id("AAPL", "US", date(2025, 1, 1)) == first.instrument_id


def test_ticker_change_keeps_instrument_identity(registry: SQLiteInstrumentRegistry):
    original = registry.register(
        symbol="OLD",
        market="US",
        name="Renamed Issuer",
        valid_from=date(2000, 1, 1),
    )
    registry.close_ticker_alias(symbol="OLD", market="US", valid_to=date(2020, 1, 1))
    registry.add_ticker_alias(
        instrument_id=original.instrument_id,
        symbol="NEW",
        market="US",
        valid_from=date(2020, 1, 1),
    )
    resolver = SQLiteInstrumentResolver(registry.db_path)

    assert resolver.resolve_instrument_id("OLD", "US", date(2019, 12, 31)) == original.instrument_id
    assert resolver.resolve_instrument_id("NEW", "US", date(2020, 1, 1)) == original.instrument_id


def test_closed_ticker_can_be_reused_by_new_instrument(registry: SQLiteInstrumentRegistry):
    original = registry.register(
        symbol="REUSE",
        market="US",
        name="Original Issuer",
        valid_from=date(2000, 1, 1),
    )
    registry.close_ticker_alias(
        symbol="REUSE", market="US", valid_to=date(2020, 1, 1)
    )
    replacement = registry.register(
        symbol="REUSE",
        market="US",
        name="Replacement Issuer",
        valid_from=date(2020, 1, 1),
    )
    resolver = SQLiteInstrumentResolver(registry.db_path)

    assert resolver.resolve_instrument_id("REUSE", "US", date(2019, 1, 1)) == original.instrument_id
    assert resolver.resolve_instrument_id("REUSE", "US", date(2021, 1, 1)) == replacement.instrument_id
