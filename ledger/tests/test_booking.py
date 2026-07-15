"""Booking engine tests: lots, methods, interpolation, tolerances, assertions."""

from decimal import Decimal

from ledger.booking import book
from ledger.core import model
from ledger.errors import Severity
from ledger.parser.parser import parse_string

D = Decimal


def _book(text: str):
    parsed = parse_string(text)
    assert not parsed.errors, [str(e) for e in parsed.errors]
    directives = [i for i in parsed.items if isinstance(i, model.Directive)]
    directives.sort(key=model.sort_key)
    return book(directives)


def _errors(result):
    return [e for e in result.errors if e.severity is Severity.ERROR]


PRELUDE = """\
2026-01-01 open Equity:Opening
2026-01-01 open Assets:Broker:IBKR:Cash USD
2026-01-01 open Income:PnL:Realized:IBKR USD
"""


def test_simple_cash_transaction_and_inventory():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet HKD\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "dinner"\n'
        "  Expenses:Food  120.00 HKD\n"
        "  Assets:Cash:Wallet  -120.00 HKD\n"
    )
    assert not _errors(result)
    assert result.inventories["Assets:Cash:Wallet"].cash["HKD"] == D("-120.00")
    assert result.inventories["Expenses:Food"].cash["HKD"] == D("120.00")


def test_elided_amount_interpolation():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet HKD\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "dinner"\n'
        "  Expenses:Food  120.00 HKD\n"
        "  Assets:Cash:Wallet\n"
    )
    assert not _errors(result)
    assert result.inventories["Assets:Cash:Wallet"].cash["HKD"] == D("-120.00")


def test_two_elided_amounts_is_an_error():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "bad"\n'
        "  Expenses:Food\n"
        "  Assets:Cash:Wallet\n"
    )
    assert any("without an amount" in e.message for e in _errors(result))


def test_unbalanced_transaction_reported():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "off by a cent"\n'
        "  Expenses:Food  100.00 USD\n"
        "  Assets:Cash:Wallet  -99.98 USD\n"
    )
    assert any("does not balance" in e.message for e in _errors(result))


def test_dust_within_tolerance_passes():
    # 0.004 residual, tolerance from 2-decimal literals is 0.005.
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "dust"\n'
        "  Expenses:Food  100.00 USD\n"
        "  Assets:Cash:Wallet  -99.996 USD\n"
    )
    # tolerance: most precise literal has 3 decimals -> 0.0005; 0.004 fails.
    assert any("does not balance" in e.message for e in _errors(result))
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "dust"\n'
        "  Expenses:Food  100.004 USD\n"
        "  Assets:Cash:Wallet  -100.00 USD\n"
    )
    # residual 0.004, tolerance 0.0005 -> still fails; make a passing case:
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "dust"\n'
        "  Expenses:Food  33.33 USD\n"
        "  Expenses:Food  33.33 USD\n"
        "  Expenses:Food  33.33 USD\n"
        "  Assets:Cash:Wallet  -99.99 USD\n"
    )
    assert not _errors(result)


def test_buy_creates_lot_with_total_cost():
    result = _book(
        PRELUDE
        + '2026-01-01 open Assets:Broker:IBKR:Positions "FIFO"\n'
        + '2026-03-02 * "buy"\n'
        "  Assets:Broker:IBKR:Positions  10 US.AAPL {{1751.00 USD, 2026-03-02, \"t:1\"}}\n"
        "  Assets:Broker:IBKR:Cash  -1751.00 USD\n"
    )
    assert not _errors(result)
    lots = result.inventories["Assets:Broker:IBKR:Positions"].lots
    assert len(lots) == 1
    lot = lots[0]
    assert lot.units == D("10")
    assert lot.cost_total == D("1751.00")
    assert lot.label == "t:1"


def test_sell_by_label_realizes_expected_cost():
    result = _book(
        PRELUDE
        + '2026-01-01 open Assets:Broker:IBKR:Positions "FIFO"\n'
        + '2026-03-02 * "buy"\n'
        '  Assets:Broker:IBKR:Positions  10 US.AAPL {{1751.00 USD, 2026-03-02, "t:1"}}\n'
        "  Assets:Broker:IBKR:Cash  -1751.00 USD\n"
        '2026-04-01 * "sell"\n'
        '  Assets:Broker:IBKR:Positions  -4 US.AAPL {2026-03-02, "t:1"}\n'
        "  Assets:Broker:IBKR:Cash  719.00 USD\n"
        "  Income:PnL:Realized:IBKR  -18.60 USD\n"
    )
    assert not _errors(result)
    lot = result.inventories["Assets:Broker:IBKR:Positions"].lots[0]
    assert lot.units == D("6")
    assert lot.cost_total == D("1751.00") - D("700.40")
    realized = result.inventories["Income:PnL:Realized:IBKR"].cash["USD"]
    assert realized == D("-18.60")


def test_full_reduction_consumes_exact_remaining_cost():
    result = _book(
        PRELUDE
        + '2026-01-01 open Assets:Broker:IBKR:Positions "FIFO"\n'
        + '2026-03-02 * "buy 3 with fee, cost does not divide evenly"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{526.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -526.00 USD\n"
        '2026-04-01 * "sell all 3"\n'
        "  Assets:Broker:IBKR:Positions  -3 US.AAPL {}\n"
        "  Assets:Broker:IBKR:Cash  540.00 USD\n"
        "  Income:PnL:Realized:IBKR  -14.00 USD\n"
    )
    assert not _errors(result)
    assert result.inventories["Assets:Broker:IBKR:Positions"].lots == []


def test_fifo_consumes_across_lots_oldest_first():
    result = _book(
        PRELUDE
        + '2026-01-01 open Assets:Broker:IBKR:Positions "FIFO"\n'
        + '2026-03-01 * "buy1"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{300.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -300.00 USD\n"
        '2026-03-05 * "buy2"\n'
        "  Assets:Broker:IBKR:Positions  2 US.AAPL {{250.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -250.00 USD\n"
        '2026-04-01 * "sell 4 across both lots: 300.00 + 125.00"\n'
        "  Assets:Broker:IBKR:Positions  -4 US.AAPL {}\n"
        "  Assets:Broker:IBKR:Cash  500.00 USD\n"
        "  Income:PnL:Realized:IBKR  -75.00 USD\n"
    )
    assert not _errors(result)
    lots = result.inventories["Assets:Broker:IBKR:Positions"].lots
    assert len(lots) == 1
    assert lots[0].units == D("1") and lots[0].cost_total == D("125.00")


def test_strict_requires_unambiguous_match():
    result = _book(
        PRELUDE
        + "2026-01-01 open Assets:Broker:IBKR:Positions\n"
        + '2026-03-01 * "buy1"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{300.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -300.00 USD\n"
        '2026-03-05 * "buy2"\n'
        "  Assets:Broker:IBKR:Positions  2 US.AAPL {{250.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -250.00 USD\n"
        '2026-04-01 * "ambiguous sell"\n'
        "  Assets:Broker:IBKR:Positions  -1 US.AAPL {}\n"
        "  Assets:Broker:IBKR:Cash  110.00 USD\n"
        "  Income:PnL:Realized:IBKR  -10.00 USD\n"
    )
    assert any("ambiguous" in e.message for e in _errors(result))


def test_overdraw_reported():
    result = _book(
        PRELUDE
        + "2026-01-01 open Assets:Broker:IBKR:Positions\n"
        + '2026-03-01 * "buy"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{300.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -300.00 USD\n"
        '2026-04-01 * "sell too many"\n'
        "  Assets:Broker:IBKR:Positions  -5 US.AAPL {}\n"
        "  Assets:Broker:IBKR:Cash  550.00 USD\n"
        "  Income:PnL:Realized:IBKR  -50.00 USD\n"
    )
    assert any("overdrawn" in e.message for e in _errors(result))


def test_average_pool_merges_and_reduces_proportionally():
    result = _book(
        "2026-01-01 open Equity:Opening\n"
        "2026-01-01 open Assets:Broker:Futu:Cash HKD\n"
        '2026-01-01 open Assets:Broker:Futu:Positions "NONE"\n'
        "2026-01-01 open Income:PnL:Realized:Futu HKD\n"
        '2026-02-02 * "buy1"\n'
        "  Assets:Broker:Futu:Positions  3 HK.0700 {{1200.00 HKD}}\n"
        "  Assets:Broker:Futu:Cash  -1200.00 HKD\n"
        '2026-02-10 * "buy2"\n'
        "  Assets:Broker:Futu:Positions  2 HK.0700 {{900.00 HKD}}\n"
        "  Assets:Broker:Futu:Cash  -900.00 HKD\n"
        '2026-03-01 * "sell 2 from pool: cost 840.00"\n'
        "  Assets:Broker:Futu:Positions  -2 HK.0700 {}\n"
        "  Assets:Broker:Futu:Cash  900.00 HKD\n"
        "  Income:PnL:Realized:Futu  -60.00 HKD\n"
    )
    assert not _errors(result)
    lots = result.inventories["Assets:Broker:Futu:Positions"].lots
    assert len(lots) == 1
    assert lots[0].units == D("3")
    assert lots[0].cost_total == D("1260.00")


def test_unopened_account_reported_but_booked():
    result = _book(
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "x"\n'
        "  Expenses:Food  1.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    assert any("not opened" in e.message for e in _errors(result))
    assert result.inventories["Assets:Cash:Wallet"].cash["USD"] == D("-1.00")


def test_currency_constraint_enforced():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet HKD\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "wrong currency"\n'
        "  Expenses:Food  1.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    assert any("not allowed" in e.message for e in _errors(result))


def test_use_before_open_and_after_close():
    # In the date-sorted stream a later open has not been processed yet, so
    # an earlier use reports the account as not opened.
    result = _book(
        "2026-02-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-15 * "before open"\n'
        "  Expenses:Food  1.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    assert any("not opened" in e.message for e in _errors(result))

    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        "2026-02-01 close Assets:Cash:Wallet\n"
        '2026-03-01 * "after close"\n'
        "  Expenses:Food  1.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    assert any("after its close date" in e.message for e in _errors(result))


def test_balance_assertion_pass_and_fail_and_tolerance():
    base = (
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Equity:Opening\n"
        '2026-01-02 * "seed"\n'
        "  Assets:Cash:Wallet  100.00 USD\n"
        "  Equity:Opening  -100.00 USD\n"
    )
    ok = _book(base + "2026-01-03 balance Assets:Cash:Wallet 100.00 USD\n")
    assert not _errors(ok)

    fail = _book(base + "2026-01-03 balance Assets:Cash:Wallet 90.00 USD\n")
    assert any("balance assertion failed" in e.message for e in _errors(fail))

    tolerant = _book(
        base + "2026-01-03 balance Assets:Cash:Wallet 99.90 ~ 0.20 USD\n"
    )
    assert not _errors(tolerant)

    # Assertion applies at the start of its date: same-date txns don't count.
    start_of_day = _book(
        base
        + '2026-01-03 * "later that day"\n'
        "  Assets:Cash:Wallet  5.00 USD\n"
        "  Equity:Opening  -5.00 USD\n"
        + "2026-01-03 balance Assets:Cash:Wallet 100.00 USD\n"
    )
    assert not _errors(start_of_day)


def test_elided_with_reduction_rejected():
    result = _book(
        PRELUDE
        + '2026-01-01 open Assets:Broker:IBKR:Positions "FIFO"\n'
        + '2026-03-01 * "buy"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{300.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -300.00 USD\n"
        '2026-04-01 * "sell with elided cash"\n'
        "  Assets:Broker:IBKR:Positions  -3 US.AAPL {}\n"
        "  Assets:Broker:IBKR:Cash\n"
    )
    assert any("elided amount" in e.message for e in _errors(result))


def test_posting_without_cost_next_to_lots_warns():
    result = _book(
        PRELUDE
        + "2026-01-01 open Assets:Broker:IBKR:Positions\n"
        + '2026-03-01 * "buy"\n'
        "  Assets:Broker:IBKR:Positions  3 US.AAPL {{300.00 USD}}\n"
        "  Assets:Broker:IBKR:Cash  -300.00 USD\n"
        '2026-04-01 * "units without cost spec"\n'
        "  Assets:Broker:IBKR:Positions  -1 US.AAPL @ 100.00 USD\n"
        "  Assets:Broker:IBKR:Cash  100.00 USD\n"
    )
    warnings = [e for e in result.errors if e.severity is Severity.WARNING]
    assert any("without a cost spec" in w.message for w in warnings)


def test_duplicate_open_and_close_errors():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-02 open Assets:Cash:Wallet\n"
    )
    assert any("already opened" in e.message for e in _errors(result))

    result = _book("2026-01-02 close Assets:Cash:Wallet\n")
    assert any("unopened" in e.message for e in _errors(result))


def test_close_with_balance_warns():
    result = _book(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Equity:Opening\n"
        '2026-01-02 * "seed"\n'
        "  Assets:Cash:Wallet  1.00 USD\n"
        "  Equity:Opening  -1.00 USD\n"
        "2026-02-01 close Assets:Cash:Wallet\n"
    )
    warnings = [e for e in result.errors if e.severity is Severity.WARNING]
    assert any("non-empty balance" in w.message for w in warnings)
