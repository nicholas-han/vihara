"""SQLite online backup: preserve all facts and IDs; never overwrite a destination."""

from pathlib import Path
import sqlite3
from ..errors import LedgerError
from ..validation import validate
from .store import Store


def backup(store, destination):
    destination = Path(destination).expanduser().resolve()
    validate(store)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.open("xb").close()
    except FileExistsError:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Backup destination already exists; choose a new filename.",
        ) from None
    try:
        with store.read() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        validate(Store(destination, store.catalog))
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)
