"""Account names.

An account is a colon-separated path under one of five fixed English roots.
Components after the root start with an uppercase letter or digit (ASCII for
now; unicode components are an open question).
"""

from __future__ import annotations

import re

ROOTS = ("Assets", "Liabilities", "Equity", "Income", "Expenses")

_COMPONENT = r"[A-Z0-9][A-Za-z0-9\-]*"
ACCOUNT_RE = re.compile(rf"(?:{'|'.join(ROOTS)})(?::{_COMPONENT})+")


def is_valid_account(name: str) -> bool:
    return ACCOUNT_RE.fullmatch(name) is not None


def account_root(name: str) -> str:
    return name.split(":", 1)[0]


def account_parent(name: str) -> str | None:
    """Parent account, or None for a root."""
    head, sep, _ = name.rpartition(":")
    return head if sep else None


def is_under(name: str, prefix: str) -> bool:
    """True if ``name`` equals ``prefix`` or is a sub-account of it."""
    return name == prefix or name.startswith(prefix + ":")
