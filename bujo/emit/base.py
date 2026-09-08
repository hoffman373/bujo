"""Helpers shared by the output backends."""

from __future__ import annotations

import calendar
import re

from ..model import Collection, Document, FutureLog, MonthlyLog

_SLUG_STRIP = re.compile(r"[^\w\s-]")



def link_map(doc: Document) -> dict[str, Collection]:
    """Map every name a ``[[ref]]`` might use onto its collection.

    Each collection registers its title plus whatever short names it answers
    to, so ``[[Reading List]]``, ``[[2026-09-05]]`` and ``[[September 2026]]``
    all resolve. First one wins, so an earlier collection keeps a shared alias.
    """
    out: dict[str, Collection] = {}
    for collection in doc.collections:
        for alias in collection.aliases():
            out.setdefault(alias.casefold(), collection)
    return out


def unique(names: list[str], start: int = 2) -> list[str]:
    """Disambiguate repeated names by numbering the repeats.

    A journal may hold the same collection twice -- a day written up in the
    source and the blank page generated for that same day, say -- and two
    collections sharing a label makes every cross-reference to either resolve
    to whichever came last.
    """
    seen: dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name}-{count + start - 1}")
    return out


def anchor(text: str) -> str:
    """GitHub-style heading anchor: fold case, drop punctuation, spaces to dashes.

    Runs of spaces are *not* collapsed -- GitHub replaces each one with its own
    dash, so a stripped ``·`` leaves a double dash behind, and links only work
    if we do the same.
    """
    return _SLUG_STRIP.sub("", text.casefold()).strip().replace(" ", "-")


def month_days(year: int, month: int) -> list[tuple[int, str]]:
    """``[(1, 'Tue'), (2, 'Wed'), ...]`` for a monthly-log date column."""
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    first = calendar.weekday(year, month, 1)
    count = calendar.monthrange(year, month)[1]
    return [(day, names[(first + day - 1) % 7]) for day in range(1, count + 1)]


def meta_flag(doc: Document, key: str, default: bool) -> bool:
    """Read an on/off metadata key, falling back to the backend's default."""
    value = doc.meta.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("on", "yes", "true", "1")


def wants_calendar(doc: Document, default: bool) -> bool:
    return meta_flag(doc, "calendar", default)


def is_spread(collection: Collection) -> bool:
    """True for logs whose paper form is a two-page spread with a date column."""
    return isinstance(collection, (MonthlyLog, FutureLog))
