"""AST for the bullet journal DSL.

The vocabulary follows Ryder Carroll's Bullet Journal method:

  * three bullet families -- Task, Event, Note
  * tasks carry a *state* (open, done, migrated, scheduled, cancelled)
  * bullets may carry *signifiers* (priority, inspiration, explore)
  * bullets live inside *collections* -- Index, Future Log, Monthly Log,
    Daily Log, or a custom collection
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    """The three bullet families of rapid logging."""

    TASK = "task"
    EVENT = "event"
    NOTE = "note"


class State(str, Enum):
    """Task lifecycle. Only meaningful for ``Kind.TASK``."""

    OPEN = "open"
    DONE = "done"
    MIGRATED = "migrated"      # moved forward, usually to the next Monthly Log
    SCHEDULED = "scheduled"    # moved out to the Future Log
    CANCELLED = "cancelled"    # struck through, no longer relevant


class Signifier(str, Enum):
    """Marks written to the left of a bullet to add context."""

    PRIORITY = "priority"          # *
    INSPIRATION = "inspiration"    # !
    EXPLORE = "explore"            # ?


#: Source character -> signifier.
SIGNIFIER_CHARS = {"*": Signifier.PRIORITY, "!": Signifier.INSPIRATION, "?": Signifier.EXPLORE}

#: Source marker -> (kind, state).
MARKERS: dict[str, tuple[Kind, State | None]] = {
    ".": (Kind.TASK, State.OPEN),
    "x": (Kind.TASK, State.DONE),
    "X": (Kind.TASK, State.DONE),
    ">": (Kind.TASK, State.MIGRATED),
    "<": (Kind.TASK, State.SCHEDULED),
    "~": (Kind.TASK, State.CANCELLED),
    "o": (Kind.EVENT, None),
    "O": (Kind.EVENT, None),
    "-": (Kind.NOTE, None),
}


# --------------------------------------------------------------------------
# inline spans
# --------------------------------------------------------------------------

@dataclass
class Text:
    """A run of literal text."""

    value: str


@dataclass
class Tag:
    """``#tag`` -- a topic label."""

    name: str


@dataclass
class Context:
    """``@context`` -- a person, place or situation."""

    name: str


@dataclass
class Ref:
    """``[[Collection]]`` -- a thread to another collection."""

    target: str


Span = Text | Tag | Context | Ref


# --------------------------------------------------------------------------
# entries
# --------------------------------------------------------------------------

@dataclass
class Entry:
    """One rapid-logged bullet, plus anything nested beneath it."""

    kind: Kind
    state: State | None
    spans: list[Span]
    signifiers: list[Signifier] = field(default_factory=list)
    time: str | None = None            # "09:30" pulled off the front of an event
    target: str | None = None          # "-> 2026-10" destination of a migration
    day: int | None = None             # "09:" day of the month, in a Monthly Log
    children: list["Entry"] = field(default_factory=list)
    line: int = 0

    @property
    def text(self) -> str:
        """The entry's text with inline markup flattened back to source form."""
        out = []
        for span in self.spans:
            match span:
                case Text(value=v):
                    out.append(v)
                case Tag(name=n):
                    out.append(f"#{n}")
                case Context(name=n):
                    out.append(f"@{n}")
                case Ref(target=t):
                    out.append(f"[[{t}]]")
        return "".join(out)

    def walk(self):
        """Yield this entry and every descendant, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Group:
    """A titled sub-section inside a collection (``Fiction:``)."""

    title: str
    entries: list[Entry] = field(default_factory=list)
    line: int = 0


Item = Entry | Group


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------

@dataclass
class Collection:
    """Base class for every top-level block."""

    items: list[Item] = field(default_factory=list)
    line: int = 0

    @property
    def title(self) -> str:  # pragma: no cover - overridden everywhere
        return "Collection"

    @property
    def slug(self) -> str:
        keep = [c.lower() if c.isalnum() else "-" for c in self.title]
        return "".join(keep).strip("-")

    def aliases(self) -> list[str]:
        """Every name a ``[[ref]]`` may use to reach this collection."""
        return [self.title]

    def entries(self):
        """Yield every entry in this collection, including nested ones."""
        for item in self.items:
            if isinstance(item, Group):
                for entry in item.entries:
                    yield from entry.walk()
            else:
                yield from item.walk()


@dataclass
class DailyLog(Collection):
    date: _dt.date = _dt.date.min
    heading: str | None = None
    #: True for a page generated to be written on by hand, not compiled from
    #: source. It carries its date and nothing else.
    blank: bool = False

    @property
    def title(self) -> str:
        base = f"{self.date.isoformat()} · {WEEKDAYS[self.date.weekday()]}"
        return f"{base} — {self.heading}" if self.heading else base

    @property
    def slug(self) -> str:
        return f"day-{self.date.isoformat()}"

    def aliases(self) -> list[str]:
        return [self.title, self.date.isoformat()]


@dataclass
class MonthlyLog(Collection):
    year: int = 0
    month: int = 1
    heading: str | None = None

    @property
    def title(self) -> str:
        base = f"{MONTHS[self.month - 1]} {self.year}"
        return f"{base} — {self.heading}" if self.heading else base

    @property
    def slug(self) -> str:
        return f"month-{self.year}-{self.month:02d}"

    def aliases(self) -> list[str]:
        return [
            self.title,
            f"{self.year}-{self.month:02d}",
            f"{MONTHS[self.month - 1]} {self.year}",
        ]


@dataclass
class FutureLog(Collection):
    start: tuple[int, int] = (0, 1)   # (year, month)
    end: tuple[int, int] = (0, 1)

    @property
    def title(self) -> str:
        sy, sm = self.start
        ey, em = self.end
        return f"Future Log · {MONTHS[sm - 1]} {sy} – {MONTHS[em - 1]} {ey}"

    @property
    def slug(self) -> str:
        return f"future-{self.start[0]}-{self.start[1]:02d}-{self.end[0]}-{self.end[1]:02d}"

    def aliases(self) -> list[str]:
        return [self.title, "Future Log"]

    def months(self) -> list[tuple[int, int]]:
        """Every (year, month) pair the range spans, inclusive."""
        out, (y, m) = [], self.start
        while (y, m) <= self.end:
            out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


@dataclass
class CustomCollection(Collection):
    name: str = ""

    @property
    def title(self) -> str:
        return self.name


@dataclass
class Index(Collection):
    """A placeholder the emitters expand into a table of contents."""

    name: str = "Index"

    @property
    def title(self) -> str:
        return self.name


@dataclass
class Key(Collection):
    """A placeholder the emitters expand into the legend of bullets."""

    name: str = "Key"

    @property
    def title(self) -> str:
        return self.name


@dataclass
class Document:
    meta: dict[str, str] = field(default_factory=dict)
    collections: list[Collection] = field(default_factory=list)

    def entries(self):
        for collection in self.collections:
            yield from collection.entries()


MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
