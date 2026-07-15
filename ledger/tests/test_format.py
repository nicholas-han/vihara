"""Printer tests: fixpoint stability and reparse equivalence on golden files."""

from pathlib import Path

import pytest

from ledger.core import model
from ledger.format import format_directives
from ledger.parser.parser import parse_string

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.beancount"))


def _directives(text: str):
    parsed = parse_string(text)
    assert not parsed.errors, [str(e) for e in parsed.errors]
    return [i for i in parsed.items if isinstance(i, model.Directive)]


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_format_fixpoint(path: Path):
    """format(parse(format(parse(x)))) == format(parse(x)) — the canonical
    form is stable, which the bridge generator's idempotency relies on."""
    once = format_directives(_directives(path.read_text()))
    twice = format_directives(_directives(once))
    assert once == twice


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_reparse_preserves_semantics(path: Path):
    """Directives survive a print/reparse round trip (positions aside)."""
    original = _directives(path.read_text())
    reparsed = _directives(format_directives(original))
    assert len(original) == len(reparsed)
    for a, b in zip(original, reparsed):
        assert type(a) is type(b)
        assert a.date == b.date
        if isinstance(a, model.Transaction):
            assert a.narration == b.narration
            assert a.payee == b.payee
            assert a.tags == b.tags and a.links == b.links
            assert a.meta == b.meta
            assert len(a.postings) == len(b.postings)
            for pa, pb in zip(a.postings, b.postings):
                assert pa == pb
