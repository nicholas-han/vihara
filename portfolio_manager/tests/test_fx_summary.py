from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.records import PortfolioRecordsService
from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.fx import convert
from portfolio_manager.records.models import FxRate
from portfolio_manager.records.sample_db import create_sample_db
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore


class _FakeFx:
    def __init__(self, rates: dict[tuple[str, str], FxRate]) -> None:
        self._rates = rates

    def get_fx_rate(self, base, quote, as_of=None):
        return self._rates.get((base, quote))


HKD_USD = FxRate("HKD", "USD", date(2024, 12, 31), Decimal("0.128"))


def test_convert_same_currency_is_identity():
    fx = _FakeFx({})
    result = convert(fx, Decimal("100"), "USD", "USD")
    assert result.amount == Decimal("100")


def test_convert_uses_direct_rate():
    fx = _FakeFx({("HKD", "USD"): HKD_USD})
    result = convert(fx, Decimal("1000"), "HKD", "USD")
    assert result.amount == Decimal("128.000")
    assert result.rate_as_of == date(2024, 12, 31)


def test_convert_falls_back_to_inverse_rate():
    fx = _FakeFx({("HKD", "USD"): HKD_USD})
    result = convert(fx, Decimal("128"), "USD", "HKD")
    assert result.amount == Decimal("128") / Decimal("0.128")


def test_convert_returns_none_when_rate_missing():
    fx = _FakeFx({})
    assert convert(fx, Decimal("100"), "HKD", "USD") is None


@pytest.fixture
def store(tmp_path: Path):
    db_path = tmp_path / "records.db"
    create_sample_db(db_path)
    store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=db_path))
    yield store
    store.close()


def test_sqlite_fx_rate_picks_latest_at_or_before_as_of(store):
    rate = store.get_fx_rate("HKD", "USD", as_of=date(2025, 1, 15))
    assert rate.rate == Decimal("0.1287")
    assert rate.as_of == date(2024, 12, 31)

    latest = store.get_fx_rate("HKD", "USD")
    assert latest.rate == Decimal("0.1274")

    assert store.get_fx_rate("HKD", "USD", as_of=date(2024, 1, 1)) is None


def test_portfolio_summary_converts_to_base_currency(store):
    service = PortfolioRecordsService(store)

    summary = service.portfolio_summary(base_currency="USD")

    assert summary.unconverted_currencies == ()
    by_ccy = {b.currency: b for b in summary.by_currency}
    assert set(by_ccy) == {"USD", "HKD", "CNY"}

    # USD: realized comes from the taxable AAPL sell (average method)
    assert by_ccy["USD"].realized_pnl == Decimal("219.8")
    assert by_ccy["USD"].realized_pnl_base == Decimal("219.8")

    # HKD converts at the latest rate (0.1274)
    assert by_ccy["HKD"].dividends_received == Decimal("1240.00")
    assert by_ccy["HKD"].dividends_received_base == Decimal("1240.00") * Decimal("0.1274")

    assert summary.total_cost_base == (
        by_ccy["USD"].total_cost_base + by_ccy["HKD"].total_cost_base + by_ccy["CNY"].total_cost_base
    )
    assert summary.dividends_received_base == Decimal("7.05") + Decimal("1240.00") * Decimal("0.1274")


def test_portfolio_summary_reports_unconverted_currencies(store):
    # an FX provider that only knows HKD/USD leaves CNY unconverted
    fx = _FakeFx({("HKD", "USD"): HKD_USD})
    service = PortfolioRecordsService(store, fx=fx)

    summary = service.portfolio_summary(base_currency="USD")

    assert summary.unconverted_currencies == ("CNY",)
    by_ccy = {b.currency: b for b in summary.by_currency}
    assert by_ccy["CNY"].total_cost_base is None
    # CNY amounts are excluded from base totals rather than silently guessed
    assert summary.total_cost_base == by_ccy["USD"].total_cost_base + by_ccy["HKD"].total_cost_base


def test_portfolio_summary_respects_account_filter(store):
    service = PortfolioRecordsService(store)

    summary = service.portfolio_summary(account_ids=["taxable"], base_currency="USD")

    by_ccy = {b.currency: b for b in summary.by_currency}
    assert set(by_ccy) == {"USD"}
    assert summary.realized_pnl_base == Decimal("219.8")
