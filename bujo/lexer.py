"""Line-oriented lexer for the bullet journal DSL.

The language is whitespace sensitive: indentation nests bullets under their
parent, exactly the way a hand-written journal indents sub-tasks. So the lexer
works on whole lines and records each one's indentation column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from .errors import Diagnostic

TAB_WIDTH = 4

BLOCK_KEYWORDS = ("day", "month", "future", "collection", "index", "key")

_COMMENT = re.compile(r"^\s*//")
_BLOCK = re.compile(r"^(?P<kw>[a-z]+)\b\s*(?P<rest>.*?)\s*:?\s*$")
_META = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<value>.+?)\s*$")
_GROUP = re.compile(r"^(?P<title>.+?)\s*:\s*$")

SIGNIFIERS = "*!?"
MARKERS = ".xX><~oO-"


class Tok(Enum):
    META = auto()
    BLOCK = auto()
    GROUP = auto()
    BULLET = auto()
    CONT = auto()


@dataclass
class Token:
    type: Tok
    line: int
    indent: int
    raw: str
    # META: key/value.  BLOCK: key=keyword, value=arguments.  GROUP: value=title.
    key: str = ""
    value: str = ""
    # BULLET only
    signifiers: str = ""
    marker: str = ""
    text: str = ""


@dataclass
class LexResult:
    tokens: list[Token] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def indent_width(prefix: str) -> int:
    """Column of the first non-space character, with tabs expanded."""
    width = 0
    for ch in prefix:
        width += TAB_WIDTH - (width % TAB_WIDTH) if ch == "\t" else 1
    return width


def lex(source: str) -> LexResult:
    result = LexResult(lines=source.splitlines())

    for lineno, raw in enumerate(result.lines, start=1):
        if not raw.strip() or _COMMENT.match(raw):
            continue

        body = raw.rstrip()
        stripped = body.lstrip(" \t")
        indent = indent_width(body[: len(body) - len(stripped)])

        if indent == 0:
            token = _lex_toplevel(stripped, lineno, raw, result)
        else:
            token = _lex_body(stripped, lineno, indent, raw)

        if token is not None:
            result.tokens.append(token)

    return result


def _lex_toplevel(stripped: str, lineno: int, raw: str, result: LexResult) -> Token | None:
    first = stripped.split(None, 1)[0].rstrip(":").lower()
    if first in BLOCK_KEYWORDS:
        m = _BLOCK.match(stripped)
        assert m is not None  # the keyword match guarantees this
        return Token(Tok.BLOCK, lineno, 0, raw, key=first, value=m.group("rest"))

    m = _META.match(stripped)
    if m:
        return Token(Tok.META, lineno, 0, raw, key=m.group("key").lower(), value=m.group("value"))

    result.diagnostics.append(
        Diagnostic(
            lineno,
            1,
            f"expected a collection header or a metadata line, found {stripped.split()[0]!r}",
            hint=f"collection headers start with one of: {', '.join(BLOCK_KEYWORDS)}. "
            "Indent bullets under a header.",
            source_line=raw,
        )
    )
    return None


def _lex_body(stripped: str, lineno: int, indent: int, raw: str) -> Token:
    signifiers, marker, text = _split_bullet(stripped)
    if marker:
        return Token(Tok.BULLET, lineno, indent, raw,
                     signifiers=signifiers, marker=marker, text=text)

    m = _GROUP.match(stripped)
    if m:
        return Token(Tok.GROUP, lineno, indent, raw, value=m.group("title"))

    return Token(Tok.CONT, lineno, indent, raw, text=stripped)


def _split_bullet(line: str) -> tuple[str, str, str]:
    """Peel ``*!?`` signifiers and one bullet marker off the front of a line.

    Returns ``("", "", "")`` when the line is not a bullet at all. A signifier
    only counts when a marker, another signifier or a space follows it, so
    ordinary prose like ``!important`` is left alone. Signifiers with no marker
    are shorthand for a note, which is how ``! an idea`` is usually written.
    """
    signifiers = ""
    rest = line
    while rest and rest[0] in SIGNIFIERS:
        tail = rest[1:]
        if not (tail[:1] in ("", " ", "\t") or tail[0] in SIGNIFIERS + MARKERS):
            break
        signifiers += rest[0]
        rest = tail.lstrip(" \t")

    if rest[:1] in tuple(MARKERS) and (len(rest) == 1 or rest[1] in " \t"):
        return signifiers, rest[0], rest[1:].strip()
    if signifiers:
        return signifiers, "-", rest.strip()
    return "", "", ""
