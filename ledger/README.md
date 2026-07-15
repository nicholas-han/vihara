# ledger

Double-entry bookkeeping for all personal financial activity, over a
beancount-compatible plain-text journal. Text is the source of truth
(in the private `vihara-data` repo); SQLite is a derived, disposable index.
Implemented from scratch — zero runtime dependencies; the `beancount`
package appears only as a dev extra powering the CI compatibility gate.

Status: v2 (this module) supersedes the `ledger-v1` MySQL prototype;
historical data migrates via `scripts/migrate_v1.py`.

## Quick start

```bash
export VIHARA_DATA_DIR=~/git/vihara-data

python -m ledger check                      # parse + book + report errors
python -m ledger bal Assets:Broker          # balances (optionally --at DATE)
python -m ledger register Expenses:Food --year 2026
python -m ledger holdings                   # lots held at cost
python -m ledger rebuild-index              # refresh build/ledger.sqlite3

# one-off migration of the ledger-v1 data (branch archived after the v2 merge):
git show archive/ledger-v1:ledger/tables/DML_accounting.sql > /tmp/dml.sql
python ledger/scripts/migrate_v1.py /tmp/dml.sql $VIHARA_DATA_DIR/ledger/journal
```

Browsing UI: run fava (read-only) against `$VIHARA_DATA_DIR/ledger/main.beancount`.

## Reading map

| Doc | Contents |
|---|---|
| [00-vision-and-scope](docs/00-vision-and-scope.md) | mission, v1 scope, module relationships |
| [10-syntax-subset](docs/10-syntax-subset.md) | exact grammar supported |
| [20-model-and-booking](docs/20-model-and-booking.md) | lots, weights, tolerances, booking methods |
| [30-account-taxonomy](docs/30-account-taxonomy.md) | chart of accounts + v1 migration map |
| [40-pipeline-and-index](docs/40-pipeline-and-index.md) | pipeline, SQLite index, config |
| [90-roadmap](docs/90-roadmap.md) | done / next / deferred |
| [decisions](docs/decisions.md) | ADR log |
| [open-questions](docs/open-questions.md) | Q1–Q5 |

## Layout

```
ledger/
├── ledger/            the package (core/ parser/ index/ + pipeline modules)
├── scripts/           migrate_v1.py
├── tests/             pytest suite + golden journals (tests/golden/)
└── docs/
```
