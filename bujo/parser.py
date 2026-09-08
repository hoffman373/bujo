"""Turns a token stream into a :class:`~bujo.model.Document`."""

from __future__ import annotations

import calendar
import datetime as _dt
import re

from .errors import BujoError, Diagnostic
from .inline import parse_inline, split_target, split_time
from .lexer import Tok, Token, lex
from .model import (
    MARKERS,
    MONTHS,
    SIGNIFIER_CHARS,
    Collection,
    CustomCollection,
    DailyLog,
    Document,
    Entry,
    FutureLog,
    Group,
    Index,
    Key,
    Kind,
    MonthlyLog,
    State,
    Text,
)

#: "09: " at the front of a bullet in a Monthly Log pins it to that date. The
#: space after the colon is what keeps it clear of a time like "09:30".
_PIN = re.compile(r"^(?P<day>\d{1,2}):\s+(?P<rest>.+)$")

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_RANGE = re.compile(r"^(?P<a>\d{4}-\d{2})\s*(?:\.\.|-{2,}|→|to)\s*(?P<b>\d{4}-\d{2})$")
_QUOTED = re.compile(r'^"(?P<q>[^"]*)"|^\'(?P<s>[^\']*)\'')

#: States that make a ``-> destination`` meaningful.
_TARGETABLE = (State.MIGRATED, State.SCHEDULED)


def parse(source: str, filename: str = "<input>") -> Document:
    """Parse DSL source. Raises :class:`BujoError` with every problem found."""
    lexed = lex(source)
    p = _Parser(lexed.tokens, lexed.diagnostics, lexed.lines)
    doc = p.run()
    if p.diagnostics:
        raise BujoError(p.diagnostics, filename)
    return doc


class _Parser:
    def __init__(self, tokens: list[Token], diagnostics: list[Diagnostic], lines: list[str]):
        self.tokens = tokens
        self.diagnostics = diagnostics
        self.lines = lines
        self.doc = Document()
        self.collection: Collection | None = None
        # (indent, list-to-append-to) innermost last
        self.stack: list[tuple[int, list]] = []
        self.last_entry: Entry | None = None

    # -- driver ------------------------------------------------------------

    def run(self) -> Document:
        for token in self.tokens:
            match token.type:
                case Tok.META:
                    self._meta(token)
                case Tok.BLOCK:
                    self._block(token)
                case Tok.GROUP:
                    self._group(token)
                case Tok.BULLET:
                    self._bullet(token)
                case Tok.CONT:
                    self._continuation(token)
        return self.doc

    def _error(self, token: Token, message: str, hint: str = "", column: int = 1) -> None:
        self.diagnostics.append(
            Diagnostic(token.line, column, message, hint, token.raw.rstrip())
        )

    # -- top level ---------------------------------------------------------

    def _meta(self, token: Token) -> None:
        if self.collection is not None:
            self._error(
                token,
                "metadata must appear before the first collection",
                hint=f"move '{token.key}:' to the top of the file",
            )
            return
        self.doc.meta[token.key] = token.value

    def _block(self, token: Token) -> None:
        arg = token.value.strip()
        builder = {
            "day": self._day,
            "month": self._month,
            "future": self._future,
            "collection": self._collection,
            "index": lambda t, a: Index(name=_unquote(a) or "Index", line=t.line),
            "key": lambda t, a: Key(name=_unquote(a) or "Key", line=t.line),
        }[token.key]

        collection = builder(token, arg)
        if collection is None:
            # The header was bad and already reported. Open a throwaway
            # collection anyway so its bullets do not cascade into more errors.
            self.collection = CustomCollection(name="<invalid>", line=token.line)
            self.stack = [(-1, self.collection.items)]
            self.last_entry = None
            return

        self.doc.collections.append(collection)
        self.collection = collection
        self.stack = [(-1, collection.items)]
        self.last_entry = None

    def _day(self, token: Token, arg: str) -> Collection | None:
        head, rest = _split_arg(arg)
        m = _DATE.match(head)
        if not m:
            self._error(token, f"'day' needs a YYYY-MM-DD date, got {head!r}", "e.g. day 2026-09-05:")
            return None
        try:
            date = _dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError as exc:
            self._error(token, f"invalid date {head!r}: {exc}")
            return None
        return DailyLog(date=date, heading=_unquote(rest) or None, line=token.line)

    def _month(self, token: Token, arg: str) -> Collection | None:
        head, rest = _split_arg(arg)
        m = _MONTH.match(head)
        if not m or not 1 <= int(m[2]) <= 12:
            self._error(token, f"'month' needs a YYYY-MM date, got {head!r}", "e.g. month 2026-09:")
            return None
        return MonthlyLog(
            year=int(m[1]), month=int(m[2]), heading=_unquote(rest) or None, line=token.line
        )

    def _future(self, token: Token, arg: str) -> Collection | None:
        m = _RANGE.match(arg)
        if not m:
            self._error(
                token,
                f"'future' needs a month range, got {arg!r}",
                "e.g. future 2026-10 .. 2027-03:",
            )
            return None
        start = _ym(m.group("a"))
        end = _ym(m.group("b"))
        if start > end:
            self._error(token, "future log range runs backwards")
            return None
        if start[0] < 1 or not (1 <= start[1] <= 12 and 1 <= end[1] <= 12):
            self._error(token, f"invalid month in range {arg!r}")
            return None
        return FutureLog(start=start, end=end, line=token.line)

    def _collection(self, token: Token, arg: str) -> Collection | None:
        name = _unquote(arg)
        if not name:
            self._error(token, "'collection' needs a name", 'e.g. collection "Reading List":')
            return None
        return CustomCollection(name=name, line=token.line)

    # -- collection bodies -------------------------------------------------

    def _require_collection(self, token: Token) -> bool:
        if self.collection is None:
            self._error(
                token,
                "bullet appears outside a collection",
                hint="open one first, e.g. `day 2026-09-05:`",
            )
            return False
        return True

    def _unwind(self, indent: int) -> list:
        """Pop the indent stack until the innermost frame is a valid parent."""
        while len(self.stack) > 1 and indent <= self.stack[-1][0]:
            self.stack.pop()
        return self.stack[-1][1]

    def _group(self, token: Token) -> None:
        if not self._require_collection(token):
            return
        group = Group(title=token.value.strip(), line=token.line)
        # Groups are only ever direct children of a collection.
        self.stack = [self.stack[0]]
        self.stack[0][1].append(group)
        self.stack.append((token.indent, group.entries))
        self.last_entry = None

    def _bullet(self, token: Token) -> None:
        if not self._require_collection(token):
            return

        kind, state = MARKERS[token.marker]
        signifiers = [SIGNIFIER_CHARS[c] for c in token.signifiers]

        text = token.text
        target = None
        time = None
        day = None
        if isinstance(self.collection, MonthlyLog):
            text, day = self._pin(token, text)
        if kind is Kind.TASK:
            text, target = split_target(text)
            if target and state not in _TARGETABLE:
                self._error(
                    token,
                    "only migrated (>) and scheduled (<) tasks take a '-> destination'",
                    hint="use `>` to migrate the task or drop the arrow",
                )
        elif kind is Kind.EVENT:
            text, time = split_time(text)

        if not text.strip():
            self._error(token, f"bullet '{token.marker}' has no text")

        entry = Entry(
            kind=kind,
            state=state,
            spans=parse_inline(text),
            signifiers=signifiers,
            time=time,
            target=target,
            day=day,
            line=token.line,
        )

        parent = self._unwind(token.indent)
        parent.append(entry)
        self.stack.append((token.indent, entry.children))
        self.last_entry = entry

    def _pin(self, token: Token, text: str) -> tuple[str, int | None]:
        """Peel a ``09:`` day-of-month pin off a bullet in a Monthly Log."""
        m = _PIN.match(text)
        if not m:
            return text, None
        day = int(m.group("day"))
        month = self.collection
        assert isinstance(month, MonthlyLog)
        last = calendar.monthrange(month.year, month.month)[1]
        if not 1 <= day <= last:
            self._error(
                token,
                f"{MONTHS[month.month - 1]} {month.year} has no day {day}",
                hint=f"pick a day between 1 and {last}",
            )
            return m.group("rest"), None
        return m.group("rest"), day

    def _continuation(self, token: Token) -> None:
        if self.last_entry is None:
            self._error(
                token,
                f"expected a bullet, found plain text {token.text!r}",
                hint="start the line with one of . x > < ~ o -  (or indent it under a bullet to "
                "continue that bullet's text)",
            )
            return
        spans = self.last_entry.spans
        extra = parse_inline(token.text)
        if spans and isinstance(spans[-1], Text) and extra and isinstance(extra[0], Text):
            spans[-1] = Text(spans[-1].value.rstrip() + " " + extra[0].value)
            spans.extend(extra[1:])
        else:
            spans.append(Text(" "))
            spans.extend(extra)


# -- helpers ---------------------------------------------------------------

def _ym(text: str) -> tuple[int, int]:
    year, month = text.split("-")
    return int(year), int(month)


def _unquote(text: str) -> str:
    text = text.strip()
    m = _QUOTED.match(text)
    if m:
        return (m.group("q") if m.group("q") is not None else m.group("s")).strip()
    return text


def _split_arg(arg: str) -> tuple[str, str]:
    """Split ``2026-09-05 "Deploy day"`` into its date and its optional title."""
    parts = arg.split(None, 1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""
