"""Store roundtrip: directives -> rows -> identical directives -> same books.

The golden journals are the equivalence oracle: importing a journal into
the store and booking the DB-loaded stream must produce exactly the
balances the text pipeline produces.
"""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ledger.booking import book
from ledger.core import model
from ledger.importers import import_beancount
from ledger.store import db as store
from ledger.store import open_db
from ledger.validate import check

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN = sorted(GOLDEN_DIR.glob("*.beancount"))


@pytest.fixture()
def conn(tmp_path):
    connection = open_db(tmp_path / "ledger.db")
    yield connection
    connection.close()


def _inventory_state(result):
    state = {}
    for account, inventory in result.inventories.items():
        if inventory.is_empty():
            continue
        lots = sorted(
            (
                lot.commodity,
                lot.units,
                lot.cost_total,
                lot.cost_currency,
                lot.date,
                lot.label,
            )
            for lot in inventory.lots
        )
        state[account] = (dict(inventory.cash), lots)
    return state


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_golden_roundtrip_equivalence(conn, path):
    text_result = check(path)
    assert text_result.ok

    report = import_beancount(conn, path)
    assert report.ok, [str(e) for e in report.errors]
    assert report.status == "imported"

    directives, options, errors = store.load_directives(conn)
    assert not errors
    db_result = book(directives)
    assert not db_result.errors, [str(e) for e in db_result.errors]
    assert _inventory_state(db_result) == _inventory_state(text_result.book)
    # options survive too (operating_currency etc.)
    for name, values in text_result.load.options.items():
        assert sorted(options.get(name, [])) == sorted(values)


def test_transaction_crud(conn):
    open_a = model.Open(
        date=datetime.date(2026, 1, 1),
        meta={},
        pos=None,
        account="Assets:Cash:Wallet",
    )
    open_b = model.Open(
        date=datetime.date(2026, 1, 1),
        meta={},
        pos=None,
        account="Expenses:Food",
    )
    store.upsert_account(conn, open_a)
    store.upsert_account(conn, open_b)

    txn = model.Transaction(
        date=datetime.date(2026, 1, 5),
        meta={"note": "lunch"},
        pos=None,
        narration="noodles",
        tags=frozenset({"food"}),
        postings=(
            model.Posting(
                "Expenses:Food",
                model.Amount(Decimal("42.00"), "HKD"),
            ),
            model.Posting(
                "Assets:Cash:Wallet",
                model.Amount(Decimal("-42.00"), "HKD"),
            ),
        ),
    )
    txn_id = insert_id = store.insert_transaction(conn, txn, source="web")
    conn.commit()

    directives, _options, _errors = store.load_directives(conn)
    loaded = [d for d in directives if isinstance(d, model.Transaction)]
    assert len(loaded) == 1
    assert loaded[0].narration == "noodles"
    assert loaded[0].tags == frozenset({"food"})
    assert loaded[0].meta == {"note": "lunch"}
    assert loaded[0].pos.file == "db:transactions"
    assert loaded[0].pos.line == insert_id
    assert loaded[0].postings[0].units.number == Decimal("42.00")

    updated = model.Transaction(
        date=txn.date,
        meta={},
        pos=None,
        narration="noodles (fixed)",
        postings=txn.postings,
    )
    store.update_transaction(conn, txn_id, updated)
    conn.commit()
    directives, _, _ = store.load_directives(conn)
    loaded = [d for d in directives if isinstance(d, model.Transaction)]
    assert loaded[0].narration == "noodles (fixed)"

    store.delete_transaction(conn, txn_id)
    conn.commit()
    directives, _, _ = store.load_directives(conn)
    assert not [d for d in directives if isinstance(d, model.Transaction)]
    # postings cascade with their transaction
    assert conn.execute("SELECT COUNT(*) AS n FROM postings").fetchone()["n"] == 0


def test_meta_type_inference_roundtrip(conn):
    raw = {
        "a_string": "hello",
        "a_number": Decimal("12.50"),
        "a_date": datetime.date(2026, 3, 2),
        "an_amount": model.Amount(Decimal("5"), "USD"),
        "a_bool": True,
    }
    encoded = store.meta_to_json(raw)
    decoded = store.json_to_meta(encoded)
    assert decoded == raw


def test_elided_posting_roundtrips_as_elided(conn):
    txn = model.Transaction(
        date=datetime.date(2026, 1, 5),
        meta={},
        pos=None,
        narration="salary",
        postings=(
            model.Posting(
                "Assets:Cash:Wallet",
                model.Amount(Decimal("100.00"), "USD"),
            ),
            model.Posting("Income:Salary:Acme"),  # elided
        ),
    )
    store.insert_transaction(conn, txn)
    conn.commit()
    directives, _, _ = store.load_directives(conn)
    loaded = [d for d in directives if isinstance(d, model.Transaction)][0]
    assert loaded.postings[1].units is None
