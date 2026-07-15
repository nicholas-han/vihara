"""Compatibility gate: beancount itself must accept our journal files.

Runs only when the beancount package (a dev extra) is installed. The
average.beancount golden is excluded by design: our AVERAGE_POOL semantics
for booking "NONE" are engine-specific (see docs/20-model-and-booking.md).
"""

from pathlib import Path

import pytest

beancount_loader = pytest.importorskip("beancount.loader")

GOLDEN_DIR = Path(__file__).parent / "golden"
COMPAT_FILES = ["basic.beancount", "trading.beancount"]


@pytest.mark.parametrize("name", COMPAT_FILES)
def test_beancount_accepts_golden(name: str):
    entries, errors, _ = beancount_loader.load_file(str(GOLDEN_DIR / name))
    assert not errors, [str(e) for e in errors]
    assert entries
