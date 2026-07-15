"""Line tokenizer.

The grammar is line-oriented: a physical line is tokenized independently and
the parser decides what the token sequence means. Comments (``;`` to end of
line) are stripped here; strings may contain ``;``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(
    r"""
      (?P<WS>[ \t]+)
    | (?P<COMMENT>;.*)
    | (?P<DATE>\d{4}-\d{2}-\d{2})(?!\d)
    | (?P<NUMBER>[-+]?(?:\d[\d,]*(?:\.\d*)?|\.\d+))
    | (?P<STRING>"(?:[^"\\]|\\.)*")
    | (?P<LLBRACE>\{\{)
    | (?P<RRBRACE>\}\})
    | (?P<LBRACE>\{)
    | (?P<RBRACE>\})
    | (?P<ATAT>@@)
    | (?P<AT>@)
    | (?P<TILDE>~)
    | (?P<COMMA>,)
    | (?P<TAG>\#[A-Za-z0-9\-_/.]+)
    | (?P<LINK>\^[A-Za-z0-9\-_/.]+)
    | (?P<ACCOUNT>[A-Z][A-Za-z0-9\-]*(?::[A-Z0-9][A-Za-z0-9\-]*)+)
    | (?P<CURRENCY>[A-Z][A-Z0-9'._\-]*)
    | (?P<KEY>[a-z][a-zA-Z0-9\-_]*(?=:))
    | (?P<KEYWORD>[a-z][a-z0-9_]*)
    | (?P<FLAG>[*!])
    | (?P<COLON>:)
    """,
    re.VERBOSE,
)

_STRING_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    column: int  # 0-based offset in the line


class LexError(Exception):
    def __init__(self, message: str, column: int):
        super().__init__(message)
        self.column = column


def unquote(raw: str) -> str:
    """Decode a STRING token's text (including the surrounding quotes)."""
    body = raw[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_STRING_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tokenize(line: str) -> list[Token]:
    """Tokenize one physical line; comments and whitespace are dropped.

    Raises LexError on a character no token matches.
    """
    tokens: list[Token] = []
    pos = 0
    while pos < len(line):
        m = _TOKEN_RE.match(line, pos)
        if m is None:
            raise LexError(f"unexpected character {line[pos]!r}", pos)
        kind = m.lastgroup or ""
        if kind == "COMMENT":
            break
        if kind != "WS":
            tokens.append(Token(kind, m.group(), pos))
        pos = m.end()
    return tokens
