"""Importers: routes real-world records into the authoritative store.

- ``beancount_import``: .beancount journals (historical data, bridge
  output, anything beancount-shaped) — the text format is interchange now,
  not the source of truth.
- ``table_import``: spreadsheet-shaped entry (CSV always; XLSX when
  openpyxl is installed) using the row template documented in the module.

Both are batch-idempotent: a batch is keyed by filename, re-importing
identical content is a no-op, and changed content requires an explicit
``replace=True`` (which drops the old batch's rows first).
"""

from .beancount_import import import_beancount, import_directives  # noqa: F401
from .table_import import import_table, parse_table  # noqa: F401
