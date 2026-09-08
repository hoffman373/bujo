"""Markdown backend.

Tasks become GitHub task-list items so they stay checkable in a repo; the
states GitHub has no checkbox for keep their journal notation inside the
brackets (``[>]``, ``[<]``, ``[~]``), which reads correctly either way.
"""

from __future__ import annotations

from ..model import (
    MONTHS,
    Collection,
    Context,
    Document,
    Entry,
    FutureLog,
    Group,
    Index,
    Key,
    Kind,
    MonthlyLog,
    Ref,
    Signifier,
    Span,
    State,
    Tag,
    Text,
)
from .base import anchor, link_map, month_days, unique, wants_calendar

_STATE_BOX = {
    State.OPEN: "[ ]",
    State.DONE: "[x]",
    State.MIGRATED: "[>]",
    State.SCHEDULED: "[<]",
    State.CANCELLED: "[~]",
}

_SIGNIFIER_CHAR = {
    Signifier.PRIORITY: "*",
    Signifier.INSPIRATION: "!",
    Signifier.EXPLORE: "?",
}

EVENT_GLYPH = "○"

#: Rows of the generated Key section: (source notation, rendering, meaning).
LEGEND = [
    (".", "`[ ]`", "Task"),
    ("x", "`[x]`", "Task complete"),
    (">", "`[>]`", "Task migrated forward"),
    ("<", "`[<]`", "Task scheduled into the Future Log"),
    ("~", "`[~]`", "Task no longer relevant"),
    ("o", EVENT_GLYPH, "Event"),
    ("-", "plain item", "Note"),
    ("*", "`*`", "Priority"),
    ("!", "`!`", "Inspiration"),
    ("?", "`?`", "Explore / research"),
]

_ESCAPE = "\\`*_[]<>"


def emit(
    doc: Document,
    *,
    calendar: bool | None = None,
    front_matter: bool = False,
    **_ignored,
) -> str:
    return _Markdown(doc, calendar=calendar, front_matter=front_matter).render()


class _Markdown:
    def __init__(self, doc: Document, *, calendar: bool | None, front_matter: bool):
        self.doc = doc
        self.links = link_map(doc)
        # GitHub numbers repeated headings from -1, so match that.
        self.anchors = dict(
            zip(
                (id(c) for c in doc.collections),
                unique([anchor(c.title) for c in doc.collections], start=1),
            )
        )
        self.calendar = wants_calendar(doc, False) if calendar is None else calendar
        self.front_matter = front_matter
        self.out: list[str] = []

    def render(self) -> str:
        if self.front_matter and self.doc.meta:
            self.out.append("---")
            self.out.extend(f"{k}: {v}" for k, v in self.doc.meta.items())
            self.out.append("---")
            self.out.append("")

        meta = self.doc.meta
        if meta.get("title"):
            self.out.append(f"# {meta['title']}")
            byline = " · ".join(meta[k] for k in ("subtitle", "author", "date") if meta.get(k))
            if byline:
                self.out.append("")
                self.out.append(f"*{byline}*")
            self.out.append("")

        for collection in self.doc.collections:
            self._collection(collection)

        return _collapse(self.out)

    # -- collections -------------------------------------------------------

    def _collection(self, collection: Collection) -> None:
        self.out.append(f"## {collection.title}")
        self.out.append("")

        if isinstance(collection, Index):
            self._index()
        elif isinstance(collection, Key):
            self._key()
        elif isinstance(collection, FutureLog):
            self._future(collection)
        else:
            if isinstance(collection, MonthlyLog) and self.calendar:
                self._calendar(collection)
            self._items(collection.items, level=3)
        self.out.append("")

    def _items(self, items, level: int) -> None:
        pending: list[Entry] = []
        for item in items:
            if isinstance(item, Group):
                self._flush(pending)
                self.out.append(f"{'#' * level} {item.title}")
                self.out.append("")
                self._entries(item.entries, 0)
                self.out.append("")
            else:
                pending.append(item)
        self._flush(pending)

    def _flush(self, pending: list[Entry]) -> None:
        if pending:
            self._entries(list(pending), 0)
            self.out.append("")
            pending.clear()

    def _entries(self, entries: list[Entry], depth: int) -> None:
        for entry in entries:
            self.out.append(f"{'  ' * depth}- {self._bullet(entry)}")
            self._entries(entry.children, depth + 1)

    # -- one bullet --------------------------------------------------------

    def _bullet(self, entry: Entry) -> str:
        if entry.kind is Kind.TASK:
            marker = _STATE_BOX[entry.state or State.OPEN]
        elif entry.kind is Kind.EVENT:
            marker = EVENT_GLYPH
        else:
            marker = ""  # a note is just a plain list item

        parts = [marker]
        if entry.day:
            parts.append(f"**{entry.day:02d}**")
        if entry.signifiers:
            parts.append("`" + "".join(_SIGNIFIER_CHAR[s] for s in entry.signifiers) + "`")
        if entry.time:
            parts.append(f"**{entry.time}**")

        text = "".join(self._span(s) for s in entry.spans).strip()
        if entry.state is State.CANCELLED:
            text = f"~~{text}~~"
        parts.append(text)

        if entry.target:
            parts.append(f"→ *{esc(entry.target)}*")
        return " ".join(p for p in parts if p)

    def _span(self, span: Span) -> str:
        match span:
            case Text(value=v):
                return esc(v)
            case Tag(name=n):
                return f"`#{n}`"
            case Context(name=n):
                return f"`@{n}`"
            case Ref(target=t):
                target = self.links.get(t.casefold())
                if target is None:
                    return f"*{esc(t)}*"
                return f"[{esc(t)}](#{self.anchors[id(target)]})"
        raise AssertionError(f"unhandled span {span!r}")  # pragma: no cover

    # -- generated collections --------------------------------------------

    def _index(self) -> None:
        for collection in self.doc.collections:
            if isinstance(collection, Index):
                continue
            self.out.append(
                f"- [{collection.title}](#{self.anchors[id(collection)]})"
            )

    def _key(self) -> None:
        self.out.append("| Source | Rendering | Meaning |")
        self.out.append("| --- | --- | --- |")
        for source, rendering, meaning in LEGEND:
            self.out.append(f"| `{source}` | {rendering} | {meaning} |")

    def _future(self, collection: FutureLog) -> None:
        by_month = {}
        loose: list[Entry] = []
        for item in collection.items:
            if isinstance(item, Group):
                by_month[item.title.strip().casefold()] = item.entries
            else:
                loose.append(item)

        if loose:
            self._entries(loose, 0)
            self.out.append("")

        for year, month in collection.months():
            heading = f"{MONTHS[month - 1]} {year}"
            keys = (f"{year}-{month:02d}", heading.casefold(), MONTHS[month - 1].casefold())
            entries = next((by_month.pop(k) for k in keys if k in by_month), [])
            self.out.append(f"### {heading}")
            self.out.append("")
            if entries:
                self._entries(entries, 0)
            else:
                self.out.append("*(nothing scheduled)*")
            self.out.append("")

        for title, entries in by_month.items():
            self.out.append(f"### {title}")
            self.out.append("")
            self._entries(entries, 0)
            self.out.append("")

    def _calendar(self, collection: MonthlyLog) -> None:
        self.out.append("| Day | | Day | |")
        self.out.append("| ---: | --- | ---: | --- |")
        days = month_days(collection.year, collection.month)
        half = (len(days) + 1) // 2
        left, right = days[:half], days[half:] + [(0, "")] * (half - len(days[half:]))
        for (d1, n1), (d2, n2) in zip(left, right):
            second = f"{d2:02d} | {n2}" if d2 else " | "
            self.out.append(f"| {d1:02d} | {n1} | {second} |")
        self.out.append("")


def _collapse(lines: list[str]) -> str:
    """Join lines, squeezing runs of blank lines down to one."""
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def esc(text: str) -> str:
    """Escape Markdown's inline metacharacters."""
    return "".join("\\" + ch if ch in _ESCAPE else ch for ch in text)
