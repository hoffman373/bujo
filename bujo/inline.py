"""Inline markup inside a bullet's text.

Three constructs, all borrowed from how people actually annotate a journal:

  ``#tag``          a topic label
  ``@context``      a person, place or situation
  ``[[Collection]]`` a *thread* -- a pointer to another collection
"""

from __future__ import annotations

import re

from .model import Context, Ref, Span, Tag, Text

_INLINE = re.compile(
    r"""
      \[\[(?P<ref>[^\]\n]+)\]\]        # [[Reading List]]
    | (?<![\w#])\#(?P<tag>[\w][\w/-]*) # #health
    | (?<![\w@])@(?P<ctx>[\w][\w/.-]*) # @office
    """,
    re.VERBOSE,
)

#: A clock reading: 9:30, 09:30, 9:30pm, or bare 24-hour 0930. The bare form
#: spells out its own valid range, so 2560 stays text.
_CLOCK = r"(?:\d{1,2}:\d{2}(?:\s*[ap]m)?|[01]\d[0-5]\d|2[0-3][0-5]\d)"
_TIME = re.compile(
    rf"^(?P<time>{_CLOCK})(?:\s*[-–—]\s*(?P<end>{_CLOCK}))?\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_TARGET = re.compile(r"\s*(?:->|→)\s*(?P<target>[^\s].*?)\s*$")


def split_target(text: str) -> tuple[str, str | None]:
    """Peel a trailing ``-> destination`` off a migrated/scheduled task."""
    m = _TARGET.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group("target")


def split_time(text: str) -> tuple[str, str | None]:
    """Peel a leading time, or time range, off an event.

    Accepts ``09:30``, ``9:30pm`` and the bare 24-hour ``0930``, singly or as a
    range. Everything is normalised to ``HH:MM`` so a journal reads the same
    however it was typed.

    The bare form is inherently ambiguous with a four-digit year: an event
    beginning ``2026`` reads as 20:26. Put a year anywhere but the front.
    """
    m = _TIME.match(text)
    if not m:
        return text, None
    time = _clock(m.group("time"))
    if m.group("end"):
        time = f"{time}–{_clock(m.group('end'))}"
    return m.group("rest"), time


def _clock(text: str) -> str:
    """Normalise one clock reading to ``HH:MM``, or ``H:MMpm`` as written."""
    text = text.replace(" ", "")
    return f"{text[:2]}:{text[2:]}" if text.isdigit() else text


def parse_inline(text: str) -> list[Span]:
    """Split raw bullet text into literal runs, tags, contexts and refs."""
    spans: list[Span] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            spans.append(Text(text[pos : m.start()]))
        if m.group("ref") is not None:
            spans.append(Ref(m.group("ref").strip()))
        elif m.group("tag") is not None:
            spans.append(Tag(m.group("tag")))
        else:
            spans.append(Context(m.group("ctx")))
        pos = m.end()
    if pos < len(text):
        spans.append(Text(text[pos:]))
    return spans
