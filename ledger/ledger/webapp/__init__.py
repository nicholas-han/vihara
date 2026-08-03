"""Built-in web app: browse and enter journal entries.

Zero-dependency (http.server + sqlite3). Run with ``python -m ledger web``.
The app is a viewer/editor over the authoritative store; every write goes
through the same validation pipeline as the CLI (full rebook per request —
cheap at personal scale, see docs/40-pipeline-and-index.md).
"""
