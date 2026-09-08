"""Build a printable notebook out of a parsed journal.

The weekly notebook is a paper artefact, so its shape is driven by how it will
be made: pages half the size of a Letter sheet, ordered front to back the way a
Bullet Journal is ordered, and finishing with a blank dotted page per day for
the week you are about to live through.
"""

from __future__ import annotations

import datetime as _dt

from dataclasses import replace

from .model import (
    Collection,
    CustomCollection,
    DailyLog,
    Document,
    Entry,
    FutureLog,
    Index,
    Key,
    MonthlyLog,
)

#: Front-to-back order of a Bullet Journal: the reference pages, then the
#: planning horizons longest first, then the dailies.
ORDER = (Index, Key, FutureLog, MonthlyLog, CustomCollection, DailyLog)

WEEK_STARTS = {"monday": 0, "sunday": 6}

#: Half a Letter sheet, folded on the long edge.
HALF_LETTER = "paperwidth=5.5in,paperheight=8.5in"

#: The sheet those half-pages get printed two-up on.
LETTER_SHEET = "letterpaper,landscape,margin=0pt"

#: Inner margin of a folded page. The fold falls in the middle of a sheet, so
#: nothing is lost into a binding -- this is just breathing room at the crease.
GUTTER = "0.375in"

def week_of(day: _dt.date, start: str = "monday") -> list[_dt.date]:
    """The seven dates of the week containing *day*."""
    try:
        offset = WEEK_STARTS[start.lower()]
    except KeyError:
        raise ValueError(
            f"unknown week start {start!r}; choose from {', '.join(WEEK_STARTS)}"
        ) from None
    first = day - _dt.timedelta(days=(day.weekday() - offset) % 7)
    return [first + _dt.timedelta(days=n) for n in range(7)]


def weekly(
    doc: Document,
    day: _dt.date | None = None,
    *,
    start: str = "monday",
    blanks: str = "all",
    paper: str = HALF_LETTER,
) -> Document:
    """Return a new Document laid out as a weekly notebook.

    *day* is any date in the target week; it defaults to today. ``blanks``
    is ``"all"`` for a writing page per day of the week, or ``"remaining"``
    to skip the days already written up in the source.

    The page size is the layout's business, not the file's, so *paper* wins
    over any ``papersize`` metadata -- a journal written for A4 still folds.
    """
    if blanks not in ("all", "remaining"):
        raise ValueError(f"blanks must be 'all' or 'remaining', not {blanks!r}")

    days = week_of(day or _dt.date.today(), start)
    written = {c.date for c in doc.collections if isinstance(c, DailyLog)}

    meta = dict(doc.meta)
    meta["papersize"] = paper
    meta.setdefault("margin", "12mm")
    # The pages face each other once folded, so the gutter can be tighter than
    # the outside edge. `outer` is left alone: it falls back to `margin`.
    meta.setdefault("inner", GUTTER)

    pages = sorted(doc.collections, key=_sort_key)
    pages += [
        DailyLog(date=d, blank=True, items=pinned_on(doc, d))
        for d in days
        if blanks == "all" or d not in written
    ]
    return Document(meta=meta, collections=pages)


def pinned_on(doc: Document, day: _dt.date) -> list[Entry]:
    """Monthly-log bullets pinned to *day*, ready to head that day's page.

    They are copies, and they drop their pin: on the day's own page the
    heading already says the date. The originals stay on the monthly spread,
    the same way an appointment written on a paper month page gets copied into
    the daily log when the day comes round.
    """
    out = []
    for collection in doc.collections:
        if not isinstance(collection, MonthlyLog):
            continue
        if (collection.year, collection.month) != (day.year, day.month):
            continue
        out += [
            replace(item, day=None)
            for item in collection.items
            if isinstance(item, Entry) and item.day == day.day
        ]
    return out


def _sort_key(collection: Collection) -> tuple[int, str]:
    """Order by collection family, then by date within the dailies.

    Everything else keeps its source order, because Python's sort is stable.
    """
    for rank, family in enumerate(ORDER):
        if isinstance(collection, family):
            date = collection.date.isoformat() if isinstance(collection, DailyLog) else ""
            return rank, date
    return len(ORDER), ""


# ---------------------------------------------------------------------------
# Print production
# ---------------------------------------------------------------------------

BOOKLET = r"""\documentclass{article}
%% Imposition only: this document holds no content of its own. Each sheet
%% carries two journal pages, ordered so that folding the printed stack in
%% half down the middle puts them back in reading order. noautoscale places
%% them at exactly 100%%: the cell is already the page's own size, and letting
%% pdfpages fit them scales by a whisker for no reason.
\usepackage[%(sheet)s]{geometry}
\usepackage{pdfpages}
\pagestyle{empty}
\begin{document}
\includepdf[pages=-,booklet,nup=2x1,noautoscale]{%(pdf)s}
\end{document}
"""

TUMBLE = r"""\documentclass{article}
%% Turns the imposed sheets into what a long-edge duplex needs: the back of
%% every sheet rotated by half a turn. pdfpages cannot do this itself -- its
%% own flip-other-edge only reorders, and its rotation path is reachable only
%% at nup=1x1, which a booklet never is.
\usepackage[%(sheet)s]{geometry}
\usepackage{pdfpages}
\pagestyle{empty}
\begin{document}
%(pages)s
\end{document}
"""

#: Which edge the printer turns the sheet over on between sides. Drivers
#: disagree about whether the edge is measured against the paper or against
#: the printed image, so the honest test is the symptom: if the backs come out
#: upside down, build again with the other value.
FLIPS = ("short-edge", "long-edge")


def booklet(pdf: str, sheet: str = LETTER_SHEET) -> str:
    """A LaTeX document that imposes *pdf* two-up into folded signatures.

    ``pdfpages`` pads the page count out to a multiple of four itself, so this
    works on any PDF; the weekly layout just gets there first, with dotted
    spares instead of blank ones.

    The result assumes the sheets are turned over on their short edge.
    """
    return BOOKLET % {"sheet": sheet, "pdf": pdf}


def tumble(pdf: str, sheets: int, sheet: str = LETTER_SHEET) -> str:
    """Re-emit an imposed *pdf* for a printer that flips on the long edge.

    Turning a sheet about its long edge lands the back upside down, which also
    puts its two pages on the wrong halves. Rotating every back sheet by 180
    degrees corrects both at once.
    """
    if sheets < 1:
        raise ValueError(f"expected at least one sheet, got {sheets}")
    lines = []
    for page in range(1, sheets + 1):
        angle = ",angle=180" if page % 2 == 0 else ""
        lines.append(rf"\includepdf[pages={{{page}}},noautoscale{angle}]{{{pdf}}}")
    return TUMBLE % {"sheet": sheet, "pages": "\n".join(lines)}
