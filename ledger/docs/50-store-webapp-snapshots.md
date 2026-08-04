# 50 — Store, importers, snapshots, web app (v3)

v3 flips ADR-1: the SQLite database is the source of truth and beancount
text is an interchange format. The directive model and booking engine are
untouched — `store.load_directives` produces the same frozen dataclasses
the parser used to, and everything downstream of that seam is v2 code.

## Authoritative store

`$VIHARA_DATA_DIR/ledger/ledger.db` (`LEDGER_DB` overrides). Tables:

- `transactions` + `postings` — journal entries, one row per posting leg
  with full cost/price fields; `postings.number` NULL means elided
  (interpolated at booking, stored as entered);
- `accounts` (open/close merged into one row), `commodities`, `options`;
- `balance_assertions`, `prices`, `notes` (note + document);
- `import_batches` — batch bookkeeping for idempotent imports;
- `snapshots` + `snapshot_positions`;
- `meta` — schema version.

Conventions: all quantities are TEXT decimal strings (`Decimal(text)` on
read); metadata is JSON with values re-typed on load using the parser's
inference rules (date literal → date, number → Decimal, `NUMBER CUR` →
Amount, JSON booleans pass through). A string that *looks like* one of
those re-types on load — acceptable for a personal tool, documented here.
Directives loaded from the store carry `SourcePos("db:<table>", rowid)`,
so `LedgerError` keeps pointing at the offending record and the web app
can link straight to it.

Backup remains git: commit `ledger.db` in vihara-data (small, single
file), optionally alongside a committed `export-beancount --out` text
mirror for meaningful diffs.

## Entry paths

1. **Web app** — `python -m ledger web` (127.0.0.1:8899). Journal
   browsing with filters, transaction entry/edit/delete with validation,
   accounts, balances, holdings, snapshots, errors, import-by-paste,
   text export.
2. **Tables** — `import-table file.csv|.xlsx` (openpyxl optional, CSV is
   stdlib). Row template documented in
   `ledger/importers/table_import.py`: header row + one row per posting;
   a row with an empty date continues the previous transaction; `type`
   column also admits `balance` and `open` rows.
3. **Beancount** — `import-beancount file.beancount` (includes resolved).
   Existing history, ledger_bridge output, and anything beancount-shaped
   imports unchanged; the text format remains the bridge interchange until
   the bridge writes to the store directly.

Imports are batch-idempotent (ADR-12): re-import of identical content is
a no-op; changed content needs `--replace`. Every import (and `--dry-run`)
ends with a full-record check whose errors are the current work list.

## Snapshots (ADR-11)

    python -m ledger snapshot create 2026-07-01 --from-booked
    python -m ledger snapshot verify 1
    python -m ledger snapshot list | show 1 | delete 1

The journal is the source of truth; `--from-booked` derives the snapshot
from it, `verify` diffs a (possibly hand-edited) snapshot back against
booked journal state — the reported discrepancies enumerate exactly what
recorded history is still missing. Canonical booking = synthesized opening
transaction at the snapshot date + directives strictly after it;
`--full` books the complete record instead. Note `--from-booked` copies
*every* non-empty inventory including Income/Expenses running totals; a
hand-declared statement snapshot will normally list only assets/
liabilities, which also balances (Equity:Opening absorbs the difference)
— income statements then restart from zero at the snapshot.

## CLI summary (DB mode default, `--ledger` = legacy file mode)

    init-db | check | bal | register | holdings      [--full]
    import-beancount | import-table                  [--replace --dry-run]
    export-beancount [--out PATH] [--canonical]
    snapshot create|list|show|verify|delete
    web [--host] [--port]
    rebuild-index

The derived index (`build/ledger.sqlite3`, consumed by the bridge
reconciler) is unchanged and now sources from the store by default.
