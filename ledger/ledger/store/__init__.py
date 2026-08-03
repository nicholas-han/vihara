"""Authoritative SQLite store — the source of truth for ledger v3.

The database replaces the plain-text journal as the canonical record.
Beancount text is demoted to an interchange format: real history imports
through ``ledger.importers``, and ``ledger.export_beancount`` renders the
database back to text for fava / bean-check / diffing.

``load_directives`` produces the same frozen ``core.model`` objects the
parser used to, so the booking engine is untouched by the flip.
"""

from .db import (  # noqa: F401
    SCHEMA_VERSION,
    connect,
    delete_transaction,
    init_schema,
    insert_directive,
    insert_transaction,
    load_directives,
    open_db,
    update_transaction,
)
