"""One-off migration: ledger-v1 MySQL seed data -> beancount journal files.

The old prototype (branch ``ledger-v1``) stored real personal transactions
2013-2021 in ``ledger/tables/DML_accounting.sql``. This script parses that
SQL as TEXT (no MySQL needed) and emits:

- ``<outdir>/accounts-legacy.beancount``  open directives for used accounts
- ``<outdir>/<year>.beancount``           one journal file per year

Usage:
    python ledger/scripts/migrate_v1.py DML_accounting.sql OUTDIR

Get the input from git without checking out the branch:
    git show ledger-v1:ledger/tables/DML_accounting.sql > /tmp/dml.sql

Conventions applied:
- debit -> positive amount, credit -> negative (beancount signs);
- datetime truncates to date, the time survives as ``time:`` metadata;
- location -> ``location:`` metadata; old Trx_ID -> ``legacy_trx_id:``;
- the static account map below is the v1 -> v2 chart-of-accounts decision
  (documented in docs/30-account-taxonomy.md).
"""

from __future__ import annotations

import datetime
import re
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledger.core import model  # noqa: E402
from ledger.errors import SourcePos  # noqa: E402
from ledger.format import format_directives  # noqa: E402

# Old auto-increment Acct_ID -> new account name.
ACCOUNT_MAP = {
    1: "Assets:Cash:Legacy",
    2: "Assets:Broker:Legacy:HeldForTrading",
    3: "Assets:Broker:Legacy:AvailableForSale",
    4: "Assets:Broker:Legacy:HeldToMaturity",
    5: "Assets:Receivable:Deposits",
    6: "Assets:RealEstate:Legacy",
    7: "Assets:Retirement:Legacy",
    8: "Liabilities:CreditCard:Legacy",
    9: "Liabilities:Loan:Legacy",
    10: "Liabilities:Sponsorship:Father",
    11: "Equity:Opening",
    12: "Income:Salary:Legacy",
    13: "Income:Investing:Legacy",
    14: "Expenses:Food",
    15: "Expenses:Housing:Rent",
    16: "Expenses:Utilities",
    17: "Expenses:Transport",
    18: "Expenses:Services",
    19: "Expenses:SelfCultivation",
    20: "Expenses:Trading:Fees",
    21: "Expenses:Treating",
    22: "Expenses:Event",
}

CURRENCY_MAP = {1: "CNY", 2: "USD", 3: "HKD", 4: "JPY", 5: "EUR", 6: "GBP"}

_POS = SourcePos("migrate_v1", 0)


def _parse_tuples(values_sql: str) -> list[list]:
    """Parse a SQL VALUES body into a list of field lists.

    Handles single-quoted strings with backslash escapes, numbers, NULL
    and DEFAULT keywords."""
    tuples: list[list] = []
    fields: list = []
    i, n = 0, len(values_sql)
    depth = 0
    token_start = None

    def close_token(end: int) -> None:
        nonlocal token_start
        if token_start is None:
            return
        raw = values_sql[token_start:end].strip()
        token_start = None
        if not raw:
            return
        upper = raw.upper()
        if upper == "NULL":
            fields.append(None)
        elif upper == "DEFAULT":
            fields.append("DEFAULT")
        else:
            fields.append(Decimal(raw))

    while i < n:
        ch = values_sql[i]
        if ch == "'":
            # string literal; clear the numeric token region so the
            # closing ',' / ')' does not re-parse the raw text
            token_start = None
            j = i + 1
            out: list[str] = []
            while j < n:
                if values_sql[j] == "\\" and j + 1 < n:
                    out.append(values_sql[j + 1])
                    j += 2
                elif values_sql[j] == "'" and j + 1 < n and values_sql[j + 1] == "'":
                    out.append("'")
                    j += 2
                elif values_sql[j] == "'":
                    break
                else:
                    out.append(values_sql[j])
                    j += 1
            fields.append("".join(out))
            i = j + 1
            continue
        if ch == "(":
            depth += 1
            token_start = i + 1
        elif ch == ")":
            close_token(i)
            depth -= 1
            if depth == 0:
                tuples.append(list(fields))
                fields.clear()
        elif ch == ",":
            if depth > 0:
                close_token(i)
                token_start = i + 1
        i += 1
    return tuples


def _extract_values(sql: str, table: str) -> str:
    match = re.search(
        rf"INSERT INTO `{table}`\s*\([^)]*\)\s*VALUES\s*(.*?);",
        sql,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"no INSERT INTO `{table}` found in the input")
    return match.group(1)


def migrate(sql: str) -> dict[str, list[model.Transaction]]:
    """Returns journal file stem -> transactions ('accounts-legacy' handled
    separately by the caller via used_accounts())."""
    txn_rows = _parse_tuples(_extract_values(sql, "Transaction"))
    entry_rows = _parse_tuples(_extract_values(sql, "TransactionJournalEntry"))

    entries_by_trx: dict[int, list] = defaultdict(list)
    for trx_id, acct_id, amount, dr_cr, currency_id in entry_rows:
        entries_by_trx[int(trx_id)].append((int(acct_id), amount, int(dr_cr),
                                            int(currency_id)))

    by_year: dict[str, list[model.Transaction]] = defaultdict(list)
    for trx_id, row in enumerate(txn_rows, start=1):
        dt_text, location, description = row
        dt = datetime.datetime.fromisoformat(str(dt_text))
        meta: model.Meta = {"legacy_trx_id": str(trx_id)}
        if dt.time() != datetime.time(0, 0):
            meta["time"] = dt.time().isoformat()
        if location:
            meta["location"] = str(location)

        postings = []
        for acct_id, amount, dr_cr, currency_id in entries_by_trx.get(trx_id, []):
            sign = 1 if dr_cr == 0 else -1
            postings.append(
                model.Posting(
                    ACCOUNT_MAP[acct_id],
                    model.Amount(sign * amount, CURRENCY_MAP[currency_id]),
                )
            )
        if not postings:
            print(f"warning: transaction {trx_id} has no journal entries, skipped")
            continue

        by_year[str(dt.year)].append(
            model.Transaction(
                dt.date(),
                meta,
                _POS,
                "*",
                None,
                str(description or ""),
                frozenset(),
                frozenset(),
                tuple(postings),
            )
        )

    for txns in by_year.values():
        txns.sort(key=lambda t: (t.date, int(t.meta["legacy_trx_id"])))
    return dict(by_year)


def used_accounts(by_year: dict[str, list[model.Transaction]]) -> list[model.Open]:
    """One open directive per used account, dated at its first use."""
    first_use: dict[str, datetime.date] = {}
    for txns in by_year.values():
        for txn in txns:
            for posting in txn.postings:
                d = first_use.get(posting.account)
                if d is None or txn.date < d:
                    first_use[posting.account] = txn.date
    return [
        model.Open(date, {}, _POS, account, (), None)
        for account, date in sorted(first_use.items())
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    sql = Path(argv[1]).read_text(encoding="utf-8")
    outdir = Path(argv[2])
    outdir.mkdir(parents=True, exist_ok=True)

    by_year = migrate(sql)
    opens = used_accounts(by_year)

    (outdir / "accounts-legacy.beancount").write_text(
        "; Migrated from ledger-v1 (MySQL prototype) by migrate_v1.py.\n"
        + format_directives(list(opens)),
        encoding="utf-8",
    )
    total = 0
    for year, txns in sorted(by_year.items()):
        (outdir / f"{year}.beancount").write_text(
            f"; Migrated from ledger-v1 (MySQL prototype), year {year}.\n"
            + format_directives(list(txns)),
            encoding="utf-8",
        )
        total += len(txns)
    print(
        f"migrated {total} transactions into {len(by_year)} year files "
        f"+ accounts-legacy.beancount under {outdir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
