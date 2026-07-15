"""Parser tests: token-level snippets, directive shapes, error recovery."""

import datetime
from decimal import Decimal

from ledger.core import model
from ledger.parser.parser import parse_string

D = Decimal


def _one(text: str):
    parsed = parse_string(text)
    assert not parsed.errors, [str(e) for e in parsed.errors]
    assert len(parsed.items) == 1
    return parsed.items[0]


def test_open_with_currencies_and_booking():
    d = _one('2026-01-01 open Assets:Broker:IBKR:Cash USD,HKD "STRICT"')
    assert isinstance(d, model.Open)
    assert d.account == "Assets:Broker:IBKR:Cash"
    assert d.currencies == ("USD", "HKD")
    assert d.booking == "STRICT"


def test_close_and_commodity_and_note_and_document():
    text = """\
2026-01-01 commodity US.AAPL
  instrument_id: "AAPL.US"
2026-12-31 close Assets:Cash:Wallet
2026-06-01 note Assets:Cash:Wallet "counted"
2026-06-01 document Assets:Cash:Wallet "statements/x.pdf"
"""
    parsed = parse_string(text)
    assert not parsed.errors
    commodity, close, note, document = parsed.items
    assert isinstance(commodity, model.Commodity)
    assert commodity.currency == "US.AAPL"
    assert commodity.meta["instrument_id"] == "AAPL.US"
    assert isinstance(close, model.Close)
    assert isinstance(note, model.Note) and note.comment == "counted"
    assert isinstance(document, model.Document)


def test_transaction_full():
    text = """\
2026-01-07 * "Payee" "narration" #food #trip ^t.1
  trade_id: "X-1"
  Expenses:Food  120.00 HKD
    split: "half"
  Assets:Cash:Wallet
"""
    txn = _one(text)
    assert isinstance(txn, model.Transaction)
    assert txn.payee == "Payee" and txn.narration == "narration"
    assert txn.tags == frozenset({"food", "trip"})
    assert txn.links == frozenset({"t.1"})
    assert txn.meta["trade_id"] == "X-1"
    first, second = txn.postings
    assert first.units == model.Amount(D("120.00"), "HKD")
    assert first.meta["split"] == "half"
    assert second.units is None  # elided


def test_costs_and_prices():
    text = """\
2026-03-02 * "buy"
  Assets:Broker:IBKR:Positions  10 US.AAPL {{1751.00 USD, 2026-03-02, "t:1"}}
  Assets:Broker:IBKR:Cash  -1751.00 USD

2026-04-01 * "sell"
  Assets:Broker:IBKR:Positions  -4 US.AAPL {2026-03-02, "t:1"} @ 180.00 USD
  Assets:Broker:IBKR:Cash  719.00 USD
  Income:PnL:Realized:IBKR  -18.60 USD
"""
    parsed = parse_string(text)
    assert not parsed.errors
    buy, sell = parsed.items
    cost = buy.postings[0].cost
    assert cost.is_total and cost.number == D("1751.00") and cost.currency == "USD"
    assert cost.date == datetime.date(2026, 3, 2) and cost.label == "t:1"
    reduction = sell.postings[0]
    assert reduction.cost.number is None and not reduction.cost.is_total
    assert reduction.cost.label == "t:1"
    assert reduction.price == model.Amount(D("180.00"), "USD")
    assert not reduction.price_is_total


def test_total_price_annotation():
    txn = _one(
        "2026-01-20 * \"fx\"\n"
        "  Assets:Cash:Wallet  780.00 HKD @@ 100.00 USD\n"
        "  Assets:Bank:BOA:Checking  -100.00 USD\n"
    )
    posting = txn.postings[0]
    assert posting.price == model.Amount(D("100.00"), "USD")
    assert posting.price_is_total


def test_balance_with_tolerance():
    d = _one("2026-02-01 balance Assets:Bank:BOA:Checking 7400.00 ~ 0.05 USD")
    assert isinstance(d, model.Balance)
    assert d.amount == model.Amount(D("7400.00"), "USD")
    assert d.tolerance == D("0.05")


def test_price_option_include():
    parsed = parse_string(
        'option "title" "T"\ninclude "sub.beancount"\n'
        "2026-01-31 price HKD 0.1282 USD\n"
    )
    assert not parsed.errors
    option, include, price = parsed.items
    assert isinstance(option, model.Option) and option.value == "T"
    assert isinstance(include, model.Include)
    assert isinstance(price, model.Price)
    assert price.amount == model.Amount(D("0.1282"), "USD")


def test_metadata_value_types():
    txn = _one(
        '2026-01-01 * "m"\n'
        '  s: "text"\n'
        "  d: 2026-05-01\n"
        "  n: 42.5\n"
        "  a: 10.00 USD\n"
        "  b: TRUE\n"
        "  c: HKD\n"
        "  Assets:Cash:Wallet  1.00 HKD\n"
        "  Equity:Opening  -1.00 HKD\n"
    )
    meta = txn.meta
    assert meta["s"] == "text"
    assert meta["d"] == datetime.date(2026, 5, 1)
    assert meta["n"] == D("42.5")
    assert meta["a"] == model.Amount(D("10.00"), "USD")
    assert meta["b"] is True
    assert meta["c"] == "HKD"


def test_comments_org_headings_and_blank_lines():
    parsed = parse_string(
        "* org heading is skipped\n"
        "; a comment\n"
        "\n"
        "2026-01-01 open Assets:Cash:Wallet ; trailing comment\n"
    )
    assert not parsed.errors
    assert len(parsed.items) == 1


def test_error_recovery_continues_parsing():
    parsed = parse_string(
        "2026-01-01 open Foo:Bar\n"
        "2026-01-02 open Assets:Cash:Wallet\n"
    )
    assert len(parsed.errors) == 1
    assert "invalid account" in parsed.errors[0].message
    assert parsed.errors[0].pos.line == 1
    assert len(parsed.items) == 1  # the good directive survived


def test_bad_currency_and_number_reported():
    parsed = parse_string("2026-01-01 balance Assets:Cash:Wallet 12..0 USD\n")
    assert parsed.errors


def test_indented_line_outside_directive():
    parsed = parse_string("  Assets:Cash:Wallet  1.00 USD\n")
    assert parsed.errors and "outside" in parsed.errors[0].message


def test_duplicate_strings_on_txn_line_rejected():
    parsed = parse_string('2026-01-01 * "a" "b" "c"\n  Assets:Cash:Wallet\n')
    assert parsed.errors
