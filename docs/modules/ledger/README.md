# ledger

> Documentation location: repository `docs/`. Source code remains in `ledger`. Run module-relative commands from the source `ledger/` directory; commands explicitly marked repository-root remain rooted there.

This package contains two separate ledger domains. The sections below describe **generic personal bookkeeping**. **Investment Ledger** lives in `ledger/investment/` and owns Accounting Ledger, Position Ledger, canonical SQLite storage, atomic commands, imports and validation. It depends on `instrument_manager`; its catalog startup uses the IM C++ binding. Portfolio Manager supplies analysis, valuation and the English Web/API.

The investment database defaults to `state/holdings.sqlite3` in the Vihara repo and is authoritative, not rebuildable from legacy CSVs. Investment corrections use Reversal; generic journal editing and snapshots below do not apply to it. See the [Holdings runbook](../../projects/portfolio-holdings/RUNBOOK.md) and [module boundaries](../../projects/portfolio-holdings/MODULE_BOUNDARIES.md).

Double-entry bookkeeping for all personal financial activity. The
authoritative record is a SQLite database of structured journal entries
(in the private `vihara-data` repo); beancount text is an interchange
format — history imports from it, and the store exports back to
deterministic, bean-check-legal text so fava stays a free secondary
viewer. The generic bookkeeping implementation uses the standard library; the
`beancount` package appears only as a dev extra powering the CI
compatibility gate (openpyxl, if present, enables XLSX import).

Status: v3 (DB-canonical, ADR-10) supersedes the v2 text-canonical
journal, which superseded the `ledger-v1` MySQL prototype.

## Quick start

```bash
export VIHARA_DATA_DIR=~/git/vihara-data

python -m ledger init-db
python -m ledger import-beancount old-journal.beancount   # historical data
python -m ledger import-table 2026-spending.csv           # spreadsheet entry
python -m ledger web                        # browse + enter at :8899

python -m ledger check                      # book + report every error
python -m ledger bal Assets:Broker          # balances (--at DATE, --full)
python -m ledger holdings                   # lots held at cost

# journal-derived checkpoints; canonical booking starts at the latest one
python -m ledger snapshot create 2026-07-01 --from-booked
python -m ledger snapshot verify 1          # journal vs snapshot diff

python -m ledger export-beancount --out mirror.beancount  # fava/diff mirror
python -m ledger rebuild-index              # refresh build/ledger.sqlite3
```

One-off migration of the ledger-v1 MySQL data: run
`scripts/migrate_v1.py` (see the script header) to produce journal text,
then `import-beancount` it.

## Reading map

| Doc | Contents |
|---|---|
| [00-vision-and-scope](00-vision-and-scope.md) | mission, scope, module relationships |
| [10-syntax-subset](10-syntax-subset.md) | import/export grammar |
| [20-model-and-booking](20-model-and-booking.md) | lots, weights, tolerances, booking methods |
| [30-account-taxonomy](30-account-taxonomy.md) | chart of accounts + v1 migration map |
| [40-pipeline-and-index](40-pipeline-and-index.md) | pipeline, derived SQLite index, config |
| [50-store-webapp-snapshots](50-store-webapp-snapshots.md) | authoritative store, importers, snapshots, web app |
| [90-roadmap](90-roadmap.md) | done / next / deferred |
| [decisions](decisions.md) | ADR log |
| [open-questions](open-questions.md) | Q1–Q5 |

## Layout

```
ledger/
├── ledger/            the package (core/ parser/ store/ importers/
│                      webapp/ index/ + pipeline modules)
├── scripts/           migrate_v1.py
├── tests/             pytest suite + golden journals (tests/golden/)
└── # documentation: docs/modules/ledger/ at repository root
```
