"""Canonical printer: directives -> journal text.

The output is deterministic (same directives -> same bytes) and reparses to
the same directives; the generator in portfolio_manager relies on both
properties for idempotent regeneration. Formatting choices are fixed:
2-space posting indent, 2-space directive metadata, 4-space posting metadata,
numbers printed with their stored precision (Decimal keeps trailing zeros).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from .core import model


def format_number(number: Decimal) -> str:
    return format(number, "f")


def format_amount(amount: model.Amount) -> str:
    return f"{format_number(amount.number)} {amount.currency}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _quoted(text: str) -> str:
    return f'"{_escape(text)}"'


def _meta_value(value: model.MetaValue) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return _quoted(value)
    if isinstance(value, Decimal):
        return format_number(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, model.Amount):
        return format_amount(value)
    raise TypeError(f"unsupported metadata value {value!r}")


def _meta_lines(meta: model.Meta, indent: str) -> list[str]:
    return [f"{indent}{key}: {_meta_value(value)}" for key, value in meta.items()]


def _cost_spec(spec: model.CostSpec) -> str:
    parts: list[str] = []
    if spec.number is not None:
        parts.append(f"{format_number(spec.number)} {spec.currency}")
    if spec.date is not None:
        parts.append(spec.date.isoformat())
    if spec.label is not None:
        parts.append(_quoted(spec.label))
    body = ", ".join(parts)
    return f"{{{{{body}}}}}" if spec.is_total else f"{{{body}}}"


def _posting_line(posting: model.Posting) -> str:
    parts = ["  "]
    if posting.flag is not None:
        parts.append(f"{posting.flag} ")
    parts.append(posting.account)
    if posting.units is not None:
        parts.append(f"  {format_amount(posting.units)}")
        if posting.cost is not None:
            parts.append(f" {_cost_spec(posting.cost)}")
        if posting.price is not None:
            at = "@@" if posting.price_is_total else "@"
            parts.append(f" {at} {format_amount(posting.price)}")
    return "".join(parts)


def format_directive(directive: model.Directive) -> str:
    lines: list[str] = []
    date = directive.date.isoformat()

    if isinstance(directive, model.Transaction):
        head = [date, directive.flag]
        if directive.payee is not None:
            head.append(_quoted(directive.payee))
        if directive.payee is not None or directive.narration:
            head.append(_quoted(directive.narration))
        head.extend(f"#{tag}" for tag in sorted(directive.tags))
        head.extend(f"^{link}" for link in sorted(directive.links))
        lines.append(" ".join(head))
        lines.extend(_meta_lines(directive.meta, "  "))
        for posting in directive.postings:
            lines.append(_posting_line(posting))
            lines.extend(_meta_lines(posting.meta, "    "))
        return "\n".join(lines)

    if isinstance(directive, model.Open):
        head = f"{date} open {directive.account}"
        if directive.currencies:
            head += " " + ",".join(directive.currencies)
        if directive.booking is not None:
            head += f" {_quoted(directive.booking)}"
        lines.append(head)
    elif isinstance(directive, model.Close):
        lines.append(f"{date} close {directive.account}")
    elif isinstance(directive, model.Commodity):
        lines.append(f"{date} commodity {directive.currency}")
    elif isinstance(directive, model.Balance):
        tolerance = (
            f" ~ {format_number(directive.tolerance)}"
            if directive.tolerance is not None
            else ""
        )
        lines.append(
            f"{date} balance {directive.account} "
            f"{format_number(directive.amount.number)}{tolerance} "
            f"{directive.amount.currency}"
        )
    elif isinstance(directive, model.Price):
        lines.append(
            f"{date} price {directive.currency} {format_amount(directive.amount)}"
        )
    elif isinstance(directive, model.Note):
        lines.append(f"{date} note {directive.account} {_quoted(directive.comment)}")
    elif isinstance(directive, model.Document):
        lines.append(
            f"{date} document {directive.account} {_quoted(directive.filename)}"
        )
    else:  # pragma: no cover
        raise TypeError(f"unsupported directive {directive!r}")

    lines.extend(_meta_lines(directive.meta, "  "))
    return "\n".join(lines)


def format_directives(directives: list[model.Directive]) -> str:
    """Render a directive list as journal text (one blank line between
    transactions, none between adjacent non-transaction directives)."""
    chunks: list[str] = []
    previous_was_txn = False
    for directive in directives:
        is_txn = isinstance(directive, model.Transaction)
        if chunks and (is_txn or previous_was_txn):
            chunks.append("")
        chunks.append(format_directive(directive))
        previous_was_txn = is_txn
    return "\n".join(chunks) + "\n" if chunks else ""
