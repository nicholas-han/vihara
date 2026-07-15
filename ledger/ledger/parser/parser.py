"""Recursive-descent parser over tokenized lines.

Produces a stream of directives (plus loader statements ``option`` /
``include``) and a list of errors. A malformed directive is reported and
skipped together with its indented block; parsing always continues.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ..core import model
from ..core.account import is_valid_account
from ..errors import LedgerError, Severity, SourcePos
from .lexer import LexError, Token, tokenize, unquote

ParsedItem = model.Directive | model.Option | model.Include


@dataclass
class ParsedFile:
    items: list[ParsedItem] = field(default_factory=list)
    errors: list[LedgerError] = field(default_factory=list)


def parse_string(text: str, filename: str = "<string>") -> ParsedFile:
    return _Parser(text, filename).parse()


def parse_file(path: str) -> ParsedFile:
    with open(path, encoding="utf-8") as f:
        return _Parser(f.read(), path).parse()


class _TokenCursor:
    """Sequential reader over one line's tokens."""

    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._i = 0

    def peek(self) -> Token | None:
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def next(self) -> Token | None:
        tok = self.peek()
        if tok is not None:
            self._i += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.next()
        if tok is None or tok.kind != kind:
            got = tok.kind if tok else "end of line"
            raise _ParseError(f"expected {kind}, got {got}")
        return tok

    def at_end(self) -> bool:
        return self._i >= len(self._tokens)


class _ParseError(Exception):
    pass


def _to_decimal(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - lexer prevents this
        raise _ParseError(f"invalid number {text!r}") from exc


def _to_date(text: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise _ParseError(f"invalid date {text!r}") from exc


class _Parser:
    def __init__(self, text: str, filename: str):
        self._lines = text.splitlines()
        self._filename = filename
        self._n = 0  # current line index
        self._out = ParsedFile()

    def _pos(self, line_index: int) -> SourcePos:
        return SourcePos(self._filename, line_index + 1)

    def _error(self, message: str, line_index: int) -> None:
        self._out.errors.append(
            LedgerError(Severity.ERROR, message, self._pos(line_index))
        )

    def parse(self) -> ParsedFile:
        while self._n < len(self._lines):
            line = self._lines[self._n]
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                self._n += 1
                continue
            if line[0] in " \t":
                self._error("indented line outside a directive", self._n)
                self._n += 1
                continue
            if line[0] == "*":  # org-mode section heading, ignored
                self._n += 1
                continue
            self._parse_top_level()
        return self._out

    # -- top level -------------------------------------------------------

    def _parse_top_level(self) -> None:
        line_index = self._n
        self._n += 1
        try:
            tokens = tokenize(self._lines[line_index])
        except LexError as exc:
            self._error(str(exc), line_index)
            self._skip_indented_block()
            return
        cur = _TokenCursor(tokens)
        head = cur.next()
        assert head is not None
        try:
            if head.kind == "DATE":
                self._parse_dated(_to_date(head.text), cur, line_index)
            elif head.kind == "KEYWORD" and head.text == "option":
                name = unquote(cur.expect("STRING").text)
                value = unquote(cur.expect("STRING").text)
                self._require_end(cur)
                self._out.items.append(model.Option(name, value, self._pos(line_index)))
            elif head.kind == "KEYWORD" and head.text == "include":
                filename = unquote(cur.expect("STRING").text)
                self._require_end(cur)
                self._out.items.append(model.Include(filename, self._pos(line_index)))
            else:
                raise _ParseError(f"unexpected {head.text!r} at start of line")
        except _ParseError as exc:
            self._error(str(exc), line_index)
            self._skip_indented_block()

    def _parse_dated(
        self, date: datetime.date, cur: _TokenCursor, line_index: int
    ) -> None:
        head = cur.next()
        if head is None:
            raise _ParseError("expected a directive type after the date")
        pos = self._pos(line_index)

        if head.kind == "FLAG" or (head.kind == "KEYWORD" and head.text == "txn"):
            flag = "*" if head.kind == "KEYWORD" else head.text
            self._parse_transaction(date, flag, cur, pos)
            return
        if head.kind != "KEYWORD":
            raise _ParseError(f"unknown directive {head.text!r}")

        if head.text == "open":
            account = self._expect_account(cur)
            currencies: list[str] = []
            while cur.peek() is not None and cur.peek().kind == "CURRENCY":
                currencies.append(self._expect_currency(cur))
                if cur.peek() is not None and cur.peek().kind == "COMMA":
                    cur.next()
            booking = None
            if cur.peek() is not None and cur.peek().kind == "STRING":
                booking = unquote(cur.next().text)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(
                model.Open(date, meta, pos, account, tuple(currencies), booking)
            )
        elif head.text == "close":
            account = self._expect_account(cur)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(model.Close(date, meta, pos, account))
        elif head.text == "commodity":
            currency = self._expect_currency(cur)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(model.Commodity(date, meta, pos, currency))
        elif head.text == "balance":
            account = self._expect_account(cur)
            number = _to_decimal(cur.expect("NUMBER").text)
            tolerance = None
            if cur.peek() is not None and cur.peek().kind == "TILDE":
                cur.next()
                tolerance = _to_decimal(cur.expect("NUMBER").text)
            currency = self._expect_currency(cur)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(
                model.Balance(
                    date, meta, pos, account, model.Amount(number, currency), tolerance
                )
            )
        elif head.text == "price":
            currency = self._expect_currency(cur)
            number = _to_decimal(cur.expect("NUMBER").text)
            quote = self._expect_currency(cur)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(
                model.Price(date, meta, pos, currency, model.Amount(number, quote))
            )
        elif head.text == "note":
            account = self._expect_account(cur)
            comment = unquote(cur.expect("STRING").text)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(model.Note(date, meta, pos, account, comment))
        elif head.text == "document":
            account = self._expect_account(cur)
            filename = unquote(cur.expect("STRING").text)
            self._require_end(cur)
            meta = self._collect_meta()
            self._out.items.append(model.Document(date, meta, pos, account, filename))
        else:
            raise _ParseError(f"unsupported directive {head.text!r}")

    # -- transactions ----------------------------------------------------

    def _parse_transaction(
        self, date: datetime.date, flag: str, cur: _TokenCursor, pos: SourcePos
    ) -> None:
        strings: list[str] = []
        while cur.peek() is not None and cur.peek().kind == "STRING":
            if len(strings) == 2:
                raise _ParseError("at most two strings (payee, narration) allowed")
            strings.append(unquote(cur.next().text))
        tags: set[str] = set()
        links: set[str] = set()
        while cur.peek() is not None:
            tok = cur.next()
            if tok.kind == "TAG":
                tags.add(tok.text[1:])
            elif tok.kind == "LINK":
                links.add(tok.text[1:])
            else:
                raise _ParseError(f"unexpected {tok.text!r} on transaction line")
        if len(strings) == 2:
            payee, narration = strings[0], strings[1]
        elif len(strings) == 1:
            payee, narration = None, strings[0]
        else:
            payee, narration = None, ""

        txn_meta: model.Meta = {}
        postings: list[model.Posting] = []
        posting_meta: model.Meta | None = None  # meta dict of the last posting

        for line_index, tokens in self._iter_indented_block():
            cur = _TokenCursor(tokens)
            first = cur.peek()
            if first is not None and first.kind == "KEY":
                key, value = self._parse_meta_line(cur)
                target = posting_meta if posting_meta is not None else txn_meta
                if key in target:
                    self._error(f"duplicate metadata key {key!r}", line_index)
                target[key] = value
                continue
            try:
                posting = self._parse_posting(cur)
            except _ParseError as exc:
                self._error(str(exc), line_index)
                posting_meta = None
                continue
            postings.append(posting)
            posting_meta = posting.meta

        self._out.items.append(
            model.Transaction(
                date,
                txn_meta,
                pos,
                flag,
                payee,
                narration,
                frozenset(tags),
                frozenset(links),
                tuple(postings),
            )
        )

    def _parse_posting(self, cur: _TokenCursor) -> model.Posting:
        flag = None
        if cur.peek() is not None and cur.peek().kind == "FLAG":
            flag = cur.next().text
        account = self._expect_account(cur)
        if cur.at_end():
            return model.Posting(account, flag=flag, meta={})

        number = _to_decimal(cur.expect("NUMBER").text)
        currency = self._expect_currency(cur)
        units = model.Amount(number, currency)

        cost = None
        tok = cur.peek()
        if tok is not None and tok.kind in ("LBRACE", "LLBRACE"):
            cost = self._parse_cost_spec(cur)

        price = None
        price_is_total = False
        tok = cur.peek()
        if tok is not None and tok.kind in ("AT", "ATAT"):
            price_is_total = tok.kind == "ATAT"
            cur.next()
            p_number = _to_decimal(cur.expect("NUMBER").text)
            p_currency = self._expect_currency(cur)
            price = model.Amount(p_number, p_currency)

        self._require_end(cur)
        return model.Posting(account, units, cost, price, price_is_total, flag, {})

    def _parse_cost_spec(self, cur: _TokenCursor) -> model.CostSpec:
        opener = cur.next()
        assert opener is not None
        is_total = opener.kind == "LLBRACE"
        closer = "RRBRACE" if is_total else "RBRACE"

        number: Decimal | None = None
        currency: str | None = None
        cost_date: datetime.date | None = None
        label: str | None = None

        while True:
            tok = cur.peek()
            if tok is None:
                raise _ParseError("unterminated cost spec")
            if tok.kind == closer:
                cur.next()
                break
            if tok.kind == "COMMA":
                cur.next()
                continue
            if tok.kind == "NUMBER":
                if number is not None:
                    raise _ParseError("duplicate cost amount")
                number = _to_decimal(cur.next().text)
                currency = self._expect_currency(cur)
            elif tok.kind == "DATE":
                if cost_date is not None:
                    raise _ParseError("duplicate cost date")
                cost_date = _to_date(cur.next().text)
            elif tok.kind == "STRING":
                if label is not None:
                    raise _ParseError("duplicate cost label")
                label = unquote(cur.next().text)
            else:
                raise _ParseError(f"unexpected {tok.text!r} in cost spec")

        return model.CostSpec(number, currency, cost_date, label, is_total)

    # -- metadata --------------------------------------------------------

    def _parse_meta_line(self, cur: _TokenCursor) -> tuple[str, model.MetaValue]:
        key = cur.expect("KEY").text
        cur.expect("COLON")
        tok = cur.next()
        if tok is None:
            return key, ""
        value: model.MetaValue
        if tok.kind == "STRING":
            value = unquote(tok.text)
        elif tok.kind == "DATE":
            value = _to_date(tok.text)
        elif tok.kind == "NUMBER":
            number = _to_decimal(tok.text)
            if cur.peek() is not None and cur.peek().kind == "CURRENCY":
                value = model.Amount(number, cur.next().text)
            else:
                value = number
        elif tok.kind == "CURRENCY":
            if tok.text in ("TRUE", "FALSE"):
                value = tok.text == "TRUE"
            else:
                value = tok.text
        elif tok.kind == "ACCOUNT":
            value = tok.text
        else:
            raise _ParseError(f"unsupported metadata value {tok.text!r}")
        self._require_end(cur)
        return key, value

    def _collect_meta(self) -> model.Meta:
        meta: model.Meta = {}
        for line_index, tokens in self._iter_indented_block():
            cur = _TokenCursor(tokens)
            first = cur.peek()
            if first is None or first.kind != "KEY":
                self._error("expected metadata (key: value)", line_index)
                continue
            try:
                key, value = self._parse_meta_line(cur)
            except _ParseError as exc:
                self._error(str(exc), line_index)
                continue
            if key in meta:
                self._error(f"duplicate metadata key {key!r}", line_index)
            meta[key] = value
        return meta

    # -- indented blocks -------------------------------------------------

    def _iter_indented_block(self):
        """Yield (line_index, tokens) for each indented line following the
        current position; consumes the block. Bad lines are reported and
        skipped."""
        while self._n < len(self._lines):
            line = self._lines[self._n]
            if not line.strip() or line.strip().startswith(";"):
                self._n += 1
                continue
            if line[0] not in " \t":
                return
            line_index = self._n
            self._n += 1
            try:
                tokens = tokenize(line)
            except LexError as exc:
                self._error(str(exc), line_index)
                continue
            if tokens:
                yield line_index, tokens

    def _skip_indented_block(self) -> None:
        for _ in self._iter_indented_block():
            pass

    # -- small helpers ---------------------------------------------------

    def _expect_account(self, cur: _TokenCursor) -> str:
        tok = cur.expect("ACCOUNT")
        if not is_valid_account(tok.text):
            raise _ParseError(
                f"invalid account {tok.text!r} (must be under "
                "Assets/Liabilities/Equity/Income/Expenses)"
            )
        return tok.text

    def _expect_currency(self, cur: _TokenCursor) -> str:
        tok = cur.expect("CURRENCY")
        if not model.is_valid_currency(tok.text):
            raise _ParseError(f"invalid currency {tok.text!r}")
        return tok.text

    def _require_end(self, cur: _TokenCursor) -> None:
        tok = cur.peek()
        if tok is not None:
            raise _ParseError(f"unexpected trailing {tok.text!r}")
