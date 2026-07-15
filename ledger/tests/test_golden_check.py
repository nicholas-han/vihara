"""Every golden file must load, book and validate cleanly end-to-end."""

from pathlib import Path

import pytest

from ledger.validate import check

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.beancount"))


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_golden_checks_clean(path: Path):
    result = check(path)
    assert result.ok, [str(e) for e in result.errors]
    assert result.book.booked  # every golden file has transactions
