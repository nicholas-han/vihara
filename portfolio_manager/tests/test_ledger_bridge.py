"""ledger_bridge tests: encoding, generation, cross-engine agreement,
reconciliation on clean and perturbed fixtures."""

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.ledger_bridge.commodities import from_commodity, to_commodity
from portfolio_manager.ledger_bridge.generator import build_files, generate
from portfolio_manager.ledger_bridge.mapping import load_mapping
from portfolio_manager.ledger_bridge.reconciler import run_checks

from ledger.validate import check as ledger_check

MAPPING = """\
[defaults]
uncategorized = "Equity:Uncategorized"
opening = "Equity:Opening"

[accounts.taxable]
positions   = "Assets:Broker:IBKR:Positions"
cash        = "Assets:Broker:IBKR:Cash"
pnl         = "Income:PnL:Realized:IBKR"
dividends   = "Income:Dividends:IBKR"
withholding = "Expenses:Tax:Withholding"
cost_method = "{method}"
"""

MAIN = """\
option "title" "Bridge fixture"
option "operating_currency" "USD"

include "accounts.beancount"
include "generated/index.beancount"
"""

HAND_ACCOUNTS = """\
2026-01-01 open Equity:Opening
2026-01-01 open Equity:Uncategorized
2026-01-01 open Assets:Bank:BOA:Checking
"""

TRADES = """\
schema_version,account_id,broker,external_trade_id,trade_date,symbol,market,side,quantity,price,trade_currency,commission
1,taxable,IBKR,IBKR-1,2026-03-02,AAPL,US,buy,10,175.00,USD,1.00
1,taxable,IBKR,IBKR-2,2026-03-10,AAPL,US,buy,5,180.00,USD,1.00
1,taxable,IBKR,IBKR-3,2026-04-01,AAPL,US,sell,12,190.00,USD,1.00
"""

DIVIDENDS = """\
schema_version,account_id,pay_date,symbol,market,amount,currency,withholding_tax
1,taxable,2026-03-20,AAPL,US,8.50,USD,1.50
"""

CASHFLOWS = """\
schema_version,account_id,flow_date,type,amount,currency,counter_account,external_id
1,taxable,2026-01-05,deposit,10000.00,USD,Assets:Bank:BOA:Checking,DEP-1
"""

CHECKPOINT_POSITIONS = """\
schema_version,account_id,symbol,market,as_of,quantity,currency
1,taxable,AAPL,US,2026-05-01,3,USD
"""

CHECKPOINT_CASH = """\
schema_version,account_id,as_of,currency,balance
1,taxable,2026-05-01,USD,9635.50
"""


def _write_fixture(root: Path, method: str = "fifo") -> Path:
    portfolio = root / "portfolio"
    (portfolio / "trades" / "taxable").mkdir(parents=True)
    (portfolio / "dividends" / "taxable").mkdir(parents=True)
    (portfolio / "cashflows" / "taxable").mkdir(parents=True)
    (portfolio / "checkpoints" / "taxable").mkdir(parents=True)
    (portfolio / "trades" / "taxable" / "2026.csv").write_text(TRADES)
    (portfolio / "dividends" / "taxable" / "2026.csv").write_text(DIVIDENDS)
    (portfolio / "cashflows" / "taxable" / "2026.csv").write_text(CASHFLOWS)
    (portfolio / "checkpoints" / "taxable" / "positions.csv").write_text(
        CHECKPOINT_POSITIONS
    )
    (portfolio / "checkpoints" / "taxable" / "cash.csv").write_text(CHECKPOINT_CASH)
    (root / "bridge").mkdir()
    (root / "bridge" / "mapping.toml").write_text(MAPPING.format(method=method))
    (root / "ledger").mkdir()
    (root / "ledger" / "main.beancount").write_text(MAIN)
    (root / "ledger" / "accounts.beancount").write_text(HAND_ACCOUNTS)
    return root


def test_commodity_encoding_roundtrip():
    for instrument_id, commodity in [
        ("AAPL.US", "US.AAPL"),
        ("0700.HK", "HK.0700"),
        ("600519.CN", "CN.600519"),
        ("BRK.B.US", "US.BRK.B"),
    ]:
        assert to_commodity(instrument_id) == commodity
        assert from_commodity(commodity) == instrument_id
    with pytest.raises(ValueError):
        to_commodity("AAPL")  # no market segment
    with pytest.raises(ValueError):
        from_commodity("USD")  # not an instrument commodity


def test_mapping_validation(tmp_path: Path):
    good = tmp_path / "mapping.toml"
    good.write_text(MAPPING.format(method="fifo"))
    mapping = load_mapping(good)
    taxable = mapping.require("taxable")
    assert taxable.booking == "STRICT"
    assert mapping.uncategorized == "Equity:Uncategorized"
    with pytest.raises(ValueError, match="no \\[accounts.other\\]"):
        mapping.require("other")

    bad = tmp_path / "bad.toml"
    bad.write_text(MAPPING.format(method="fifo").replace(
        '"Assets:Broker:IBKR:Positions"', '"Broker:Positions"'
    ))
    with pytest.raises(ValueError, match="not a valid ledger account"):
        load_mapping(bad)

    bad.write_text(MAPPING.format(method="martingale"))
    with pytest.raises(ValueError, match="cost_method"):
        load_mapping(bad)


def test_generate_is_deterministic_and_idempotent(tmp_path: Path):
    data_dir = _write_fixture(tmp_path)
    first = build_files(data_dir).files
    second = build_files(data_dir).files
    assert first == second

    generate(data_dir)
    on_disk = {
        str(p.relative_to(data_dir / "ledger" / "generated")): p.read_text()
        for p in (data_dir / "ledger" / "generated").rglob("*.beancount")
    }
    assert on_disk == first
    generate(data_dir)  # second run rewrites byte-identically
    for relpath, content in on_disk.items():
        assert (data_dir / "ledger" / "generated" / relpath).read_text() == content


@pytest.mark.parametrize("method", ["average", "fifo", "lifo", "lowest_cost_first"])
def test_reconcile_clean_for_every_cost_method(tmp_path: Path, method: str):
    data_dir = _write_fixture(tmp_path, method=method)
    generate(data_dir)
    result = ledger_check(data_dir / "ledger" / "main.beancount")
    assert result.ok, [str(e) for e in result.errors]
    breaks = run_checks(data_dir)
    assert breaks == [], [str(b) for b in breaks]


def test_ledger_agrees_with_pm_numbers(tmp_path: Path):
    data_dir = _write_fixture(tmp_path, method="fifo")
    generate(data_dir)
    result = ledger_check(data_dir / "ledger" / "main.beancount")
    assert result.ok

    positions = result.book.inventories["Assets:Broker:IBKR:Positions"]
    assert positions.units_of("US.AAPL") == Decimal("3")
    (lot,) = positions.lots_of("US.AAPL")
    # FIFO: sell 12 = all of lot1 (1751.00) + 2/5 of lot2 (360.40)
    assert lot.cost_total == Decimal("540.60")
    assert lot.label == "t:IBKR-2"

    pnl = result.book.inventories["Income:PnL:Realized:IBKR"].cash["USD"]
    assert pnl == Decimal("-167.60")  # proceeds 2279.00 - cost 2111.40

    cash = result.book.inventories["Assets:Broker:IBKR:Cash"].cash["USD"]
    assert cash == Decimal("9635.50")


def test_perturbations_fire_the_right_checks(tmp_path: Path):
    data_dir = _write_fixture(tmp_path, method="fifo")
    generate(data_dir)
    assert run_checks(data_dir) == []

    # Hand-editing a generated file -> R2 drift (and here also R1/R3: the
    # edit changes a booked amount).
    target = data_dir / "ledger" / "generated" / "taxable" / "2026.beancount"
    target.write_text(target.read_text().replace("-1751.00 USD", "-1751.01 USD"))
    checks = {b.check for b in run_checks(data_dir)}
    assert "R2-generated-drift" in checks

    generate(data_dir)  # heal

    # A wrong broker checkpoint -> R1 (generated assertion fails) + R5.
    (data_dir / "portfolio" / "checkpoints" / "taxable" / "positions.csv").write_text(
        CHECKPOINT_POSITIONS.replace(",3,", ",4,")
    )
    checks = {b.check for b in run_checks(data_dir)}
    assert "R2-generated-drift" in checks  # assertions file is stale too
    generate(data_dir)
    checks = {b.check for b in run_checks(data_dir)}
    assert "R5-depot" in checks
    assert "R1-ledger-check" in checks  # balance assertion fails in-ledger

    # Restore, then edit a source CSV without regenerating -> R2 + R3.
    (data_dir / "portfolio" / "checkpoints" / "taxable" / "positions.csv").write_text(
        CHECKPOINT_POSITIONS
    )
    generate(data_dir)
    (data_dir / "portfolio" / "trades" / "taxable" / "2026.csv").write_text(
        TRADES + "1,taxable,IBKR,IBKR-4,2026-04-15,AAPL,US,buy,2,170.00,USD,0\n"
    )
    checks = {b.check for b in run_checks(data_dir)}
    assert "R2-generated-drift" in checks
    assert "R3-units" in checks


def test_opening_anchor_generates_and_reconciles(tmp_path: Path):
    root = tmp_path
    portfolio = root / "portfolio"
    (portfolio / "trades" / "taxable").mkdir(parents=True)
    (portfolio / "snapshots").mkdir(parents=True)
    (portfolio / "checkpoints" / "taxable").mkdir(parents=True)
    (portfolio / "trades" / "taxable" / "2026.csv").write_text(
        "schema_version,account_id,broker,external_trade_id,trade_date,symbol,market,side,quantity,price,trade_currency,commission\n"
        "1,taxable,IBKR,IBKR-9,2026-02-01,AAPL,US,sell,2,160.00,USD,0\n"
    )
    (portfolio / "snapshots" / "opening.csv").write_text(
        "schema_version,account_id,symbol,market,as_of,quantity,average_cost,currency\n"
        "1,taxable,AAPL,US,2026-01-01,4,150.00,USD\n"
    )
    (portfolio / "checkpoints" / "taxable" / "positions.csv").write_text(
        "schema_version,account_id,symbol,market,as_of,quantity,currency\n"
        "1,taxable,AAPL,US,2026-03-01,2,USD\n"
    )
    (root / "bridge").mkdir()
    (root / "bridge" / "mapping.toml").write_text(MAPPING.format(method="fifo"))
    (root / "ledger").mkdir()
    (root / "ledger" / "main.beancount").write_text(MAIN)
    (root / "ledger" / "accounts.beancount").write_text(HAND_ACCOUNTS)

    generate(root)
    result = ledger_check(root / "ledger" / "main.beancount")
    assert result.ok, [str(e) for e in result.errors]
    breaks = run_checks(root)
    assert breaks == [], [str(b) for b in breaks]

    positions = result.book.inventories["Assets:Broker:IBKR:Positions"]
    (lot,) = positions.lots_of("US.AAPL")
    assert lot.units == Decimal("2")
    assert lot.cost_total == Decimal("300.00")  # half of the 600 opening basis
    assert lot.label == "t:opening"
    pnl = result.book.inventories["Income:PnL:Realized:IBKR"].cash["USD"]
    assert pnl == Decimal("-20.00")


@pytest.mark.parametrize("method", ["average", "fifo"])
def test_beancount_accepts_generated_journal(tmp_path: Path, method: str):
    beancount_loader = pytest.importorskip("beancount.loader")
    data_dir = _write_fixture(tmp_path, method=method)
    generate(data_dir)
    entries, errors, _ = beancount_loader.load_file(
        str(data_dir / "ledger" / "main.beancount")
    )
    assert not errors, [str(e) for e in errors]
    assert entries
