"""Migration tests on a DML snippet mirroring the ledger-v1 format."""

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

from ledger.validate import check

_SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_v1.py"
_spec = importlib.util.spec_from_file_location("migrate_v1", _SCRIPT)
migrate_v1 = importlib.util.module_from_spec(_spec)
sys.modules["migrate_v1"] = migrate_v1
_spec.loader.exec_module(migrate_v1)

FIXTURE = """\
USE `accounting`;

INSERT INTO `Transaction` (Datetime,Location,Description) VALUES
\t('2013-09-22 12:00:00','Los Angeles','Noodle World'),
\t('2021-01-01 01:00:00','Hong Kong Kowloon','Taxi - from Xuwen\\'s place'),
    ('2014-02-01 12:00:00','Los Angeles','Allowance from home');

INSERT INTO `TransactionJournalEntry` (Trx_ID,Acct_ID,Amount,Debit_or_Credit,Currency_ID) VALUES
\t(1,14,7.62,0,2),(1,1,7.62,1,2),
\t(2,17,164.8,0,3),(2,8,164.8,1,3),
    (3,1,500,0,2),(3,11,500,1,2);
"""


def test_migrate_shapes_and_signs(tmp_path: Path):
    by_year = migrate_v1.migrate(FIXTURE)
    assert set(by_year) == {"2013", "2014", "2021"}

    (noodle,) = by_year["2013"]
    assert noodle.narration == "Noodle World"
    assert noodle.meta["location"] == "Los Angeles"
    assert noodle.meta["legacy_trx_id"] == "1"
    food, cash = noodle.postings
    assert food.account == "Expenses:Food"
    assert food.units.number == Decimal("7.62") and food.units.currency == "USD"
    assert cash.account == "Assets:Cash:Legacy"
    assert cash.units.number == Decimal("-7.62")

    (taxi,) = by_year["2021"]
    assert "Xuwen's place" in taxi.narration  # escaped quote survived
    transport, card = taxi.postings
    assert transport.units.currency == "HKD"
    assert card.account == "Liabilities:CreditCard:Legacy"
    assert card.units.number == Decimal("-164.8")

    (allowance,) = by_year["2014"]
    cash, stake = allowance.postings
    assert cash.units.number == Decimal("500")
    assert stake.account == "Equity:Opening"


def test_migrated_output_checks_clean(tmp_path: Path):
    sql = tmp_path / "dml.sql"
    sql.write_text(FIXTURE)
    outdir = tmp_path / "journal"
    assert migrate_v1.main(["migrate_v1", str(sql), str(outdir)]) == 0

    main = tmp_path / "main.beancount"
    includes = ['include "journal/accounts-legacy.beancount"'] + [
        f'include "journal/{y}.beancount"' for y in ("2013", "2014", "2021")
    ]
    main.write_text("\n".join(includes) + "\n")
    result = check(main)
    assert result.ok, [str(e) for e in result.errors]
    assert len(result.book.booked) == 3
    assert result.book.inventories["Assets:Cash:Legacy"].cash["USD"] == Decimal(
        "492.38"
    )
