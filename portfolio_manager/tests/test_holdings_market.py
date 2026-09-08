from datetime import date
from portfolio_manager.holdings.analysis import HoldingsService
from test_holdings_foundation import store
from test_holdings_cash import setup, move
from test_holdings_trades import funding, trade
from test_holdings_cash_events import fx, dividend
from portfolio_manager.holdings.integrations.market import import_rows
from ledger.investment.validation import validate


def test_fixed_valuation_does_not_change_books(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    trade(s, a, price="8", day="2026-09-03")
    trade(s, a, side="SELL", quantity="12", price="12", day="2026-09-04")
    store.add_book_fx("USD", date(2026, 9, 5), "7.9", "controlled")
    dividend(s, a)
    fx(s, a, "USD", "974", "HKD", "7792")
    missing = HoldingsService(store).holdings("2026-09-06")
    oid = missing["investments"][0]["observable_id"]
    assert (
        not missing["valuation"]["complete"]
        and missing["investments"][0]["market_value"] is None
    )
    import_rows(
        store,
        "prices",
        [
            {
                "observable_id": oid,
                "price": "12",
                "currency": "USD",
                "as_of": "2026-09-06",
                "source": "fixture",
            }
        ],
    )
    assert (
        HoldingsService(store).holdings("2026-09-06")["investments"][0][
            "valuation_status"
        ]
        == "MISSING_FX"
    )
    import_rows(
        store,
        "fx",
        [
            {
                "base_currency": "USD",
                "quote_currency": "HKD",
                "rate": "8",
                "as_of": "2026-09-06",
                "source": "fixture",
            }
        ],
    )
    result = HoldingsService(store).holdings("2026-09-06")
    assert result["valuation"]["valued_subtotal"] == "8560"
    assert result["investments"][0]["unrealized_difference"] == "128"
    assert result["investments"][0]["book_value"] == "640"
    assert validate(store)["valid"]


def test_real_zero_price_and_different_quote_currency_and_asof(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    oid = HoldingsService(store).holdings()["investments"][0]["observable_id"]
    import_rows(
        store,
        "prices",
        [
            {
                "observable_id": oid,
                "price": "0",
                "currency": "HKD",
                "as_of": "2026-09-03",
                "source": "zero price",
            }
        ],
    )
    assert (
        HoldingsService(store).holdings("2026-09-02")["investments"][0][
            "valuation_status"
        ]
        == "MISSING_PRICE"
    )
    row = HoldingsService(store).holdings("2026-09-03")["investments"][0]
    assert (
        row["market_value"] == "0"
        and row["valuation_currency"] == "HKD"
        and row["book_value"] == "800"
    )
    assert row["unrealized_difference"] == "-800"
    assert validate(store)["valid"]
