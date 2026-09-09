"""LaTeX backend.

Produces a document that compiles with plain ``pdflatex``. Every glyph is a
``\newcommand`` in the preamble, so a reader who wants different symbols
redefines them instead of editing the generated body.
"""

from __future__ import annotations

from dataclasses import replace

from ..model import (
    MONTHS,
    Collection,
    Context,
    DailyLog,
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
from .base import link_map, meta_flag, month_days, unique, wants_calendar

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}

#: Bullet macro per task state; events and notes have one each.
_STATE_MACRO = {
    State.OPEN: "task",
    State.DONE: "done",
    State.MIGRATED: "migrated",
    State.SCHEDULED: "scheduled",
    State.CANCELLED: "dropped",
}

#: Signifiers are named options rather than punctuation, so a hand-written
#: `\task[priority]{...}` says what it means.
_SIGNIFIER_KEY = {
    Signifier.PRIORITY: "priority",
    Signifier.INSPIRATION: "idea",
    Signifier.EXPLORE: "explore",
}

#: Colours, and what is left of them when the target is a mono laser printer.
#: Everything keeps its size and typeface, so the hierarchy survives the loss.
PALETTE = {
    False: {"ink": "1A1A1A", "muted": "6B6B6B", "accent": "9C4221",
            "weekend": r"\textcolor{bujomuted}{#1}"},
    True: {"ink": "000000", "muted": "000000", "accent": "000000",
           "weekend": r"\textit{#1}"},
}

#: Rows of the generated Key page: (macro, source notation, meaning).
LEGEND = [
    (r"\bujoTask", ".", "Task"),
    (r"\bujoDone", "x", "Task complete"),
    (r"\bujoMigrated", ">", "Task migrated forward"),
    (r"\bujoScheduled", "<", "Task scheduled into the Future Log"),
    (r"\bujoCancelled", "\\textasciitilde{}", r"\sout{Task no longer relevant}"),
    (r"\bujoEvent", "o", "Event"),
    (r"\bujoNote", "-", "Note"),
    (r"\bujoPriority", "*", "Priority"),
    (r"\bujoInspiration", "!", "Inspiration"),
    (r"\bujoExplore", "?", "Explore / research"),
]

PREAMBLE = r"""\documentclass[%(fontsize)s]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[%(geometry)s]{geometry}
\usepackage{graphicx}
\usepackage{array}
\usepackage{enumitem}
\usepackage{pifont}
\usepackage[normalem]{ulem}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage{longtable}
\usepackage[hidelinks]{hyperref}

%% ---- palette -------------------------------------------------------------
\definecolor{bujoink}{HTML}{%(ink)s}
\definecolor{bujomuted}{HTML}{%(muted)s}
\definecolor{bujoaccent}{HTML}{%(accent)s}

%% ---- bullets and signifiers ---------------------------------------------
%% Redefine any of these to change the notation across the whole journal.
\newcommand{\bujoTask}{\raisebox{0.2ex}{\scalebox{0.8}{$\bullet$}}}
\newcommand{\bujoDone}{\ding{53}}
\newcommand{\bujoMigrated}{\textbf{\textgreater}}
\newcommand{\bujoScheduled}{\textbf{\textless}}
\newcommand{\bujoCancelled}{\bujoTask}
\newcommand{\bujoEvent}{\raisebox{0.2ex}{\scalebox{0.8}{$\circ$}}}
\newcommand{\bujoNote}{\textendash}
\newcommand{\bujoPriority}{\textbf{*}}
\newcommand{\bujoInspiration}{\textbf{!}}
\newcommand{\bujoExplore}{\textbf{?}}

%% ---- inline markup -------------------------------------------------------
\newcommand{\bujoTag}[1]{{\small\textsf{\textcolor{bujoaccent}{\##1}}}}
\newcommand{\bujoContext}[1]{{\small\textsf{\textcolor{bujomuted}{@#1}}}}
\newcommand{\bujoTime}[1]{{\footnotesize\textsf{\textcolor{bujomuted}{#1}}}\hspace{0.4em}}
\newcommand{\bujoTarget}[1]{{\footnotesize\textcolor{bujomuted}{\textrightarrow~#1}}}
\newcommand{\bujoDay}[1]{{\footnotesize\sffamily\bfseries #1}}
\newcommand{\bujoSig}[1]{\llap{#1\hspace{0.45em}}}
%%%% Weekends in the monthly date column. With one ink there is no lighter
%%%% grey to fall back on, so they lean instead.
\newcommand{\bujoWeekend}[1]{%(weekend)s}

%% ---- layout --------------------------------------------------------------
\newlist{bujoitems}{itemize}{6}
\setlist[bujoitems]{label={},leftmargin=1.6em,labelsep=0.55em,labelwidth=1em,
                    itemsep=1.5pt,topsep=3pt,parsep=0pt,partopsep=0pt}

\titleformat{\section}{\large\bfseries\sffamily}{}{0pt}{}[\vspace{-0.6em}\rule{\linewidth}{0.4pt}]
\titleformat{\subsection}{\normalsize\bfseries\sffamily\color{bujomuted}}{}{0pt}{}
\titlespacing*{\section}{0pt}{1.6em}{0.8em}
\titlespacing*{\subsection}{0pt}{1.0em}{0.4em}

\setlength{\parindent}{0pt}
\color{bujoink}

%%%% ---- writing bullets by hand ---------------------------------------------
%%%% Every bullet is \<kind>[<options>]{<text>}, so this file can be edited, or
%%%% written from scratch, without knowing how the markers are put together:
%%%%
%%%%   \task{Ship the compiler}          \event[at=09:30]{Standup}
%%%%   \done{Write the lexer}            \note{Indentation is the grammar}
%%%%   \dropped{Hand-roll a PEG}         \task[priority]{Cut the release}
%%%%   \migrated[to=2026-10]{Manual}     \scheduled[to=2027-01]{Passport}
%%%%
%%%% Options: priority, idea, explore; to=<where a task went>, at=<a time>,
%%%% day=<day of the month>. Starred forms (\task*) render without a list item,
%%%% for a table cell.
\usepackage{keyval}
\makeatletter
%%%% \def, not \newcommand: \newcommand makes a macro \long, and \ifx compares
%%%% that prefix too, so a \long empty macro never tests equal to \@empty.
\def\bujo@sig{}
\def\bujo@to{}
\def\bujo@at{}
\def\bujo@day{}
\def\bujo@marker{}
\def\bujo@strike{}
\newcommand{\bujo@addsig}[1]{%%
  \expandafter\def\expandafter\bujo@sig\expandafter{\bujo@sig#1}}
\define@key{bujo}{priority}[]{\bujo@addsig{\bujoPriority}}
\define@key{bujo}{idea}[]{\bujo@addsig{\bujoInspiration}}
\define@key{bujo}{explore}[]{\bujo@addsig{\bujoExplore}}
\define@key{bujo}{to}{\def\bujo@to{#1}}
\define@key{bujo}{at}{\def\bujo@at{#1}}
\define@key{bujo}{day}{\def\bujo@day{#1}}
\newcommand{\bujo@setup}[1]{%%
  \def\bujo@sig{}\def\bujo@to{}\def\bujo@at{}\def\bujo@day{}%%
  \setkeys{bujo}{#1}}
\newcommand{\bujo@label}{%%
  \ifx\bujo@sig\@empty\else\bujoSig{\bujo@sig}\fi\bujo@marker}
\newcommand{\bujo@body}[1]{%%
  \ifx\bujo@day\@empty\else\bujoDay{\bujo@day}~\fi%%
  \ifx\bujo@at\@empty\else\bujoTime{\bujo@at}\fi%%
  \bujo@strike{#1}%%
  \ifx\bujo@to\@empty\else~\bujoTarget{\bujo@to}\fi}
\newcommand{\bujo@item@}[2][]{\bujo@setup{#1}\item[\bujo@label]\bujo@body{#2}}
\newcommand{\bujo@inline@}[2][]{\bujo@setup{#1}\bujo@label~\bujo@body{#2}}
\newcommand{\bujo@item}[2]{\def\bujo@marker{#1}\def\bujo@strike{#2}\bujo@item@}
\newcommand{\bujo@inline}[2]{\def\bujo@marker{#1}\def\bujo@strike{#2}\bujo@inline@}
\newcommand{\bujo@kind}[2]{%% #1 marker, #2 how the text is wrapped
  \@ifstar{\bujo@inline{#1}{#2}}{\bujo@item{#1}{#2}}}
\newcommand{\task}{\bujo@kind{\bujoTask}{\@firstofone}}
\newcommand{\done}{\bujo@kind{\bujoDone}{\@firstofone}}
\newcommand{\migrated}{\bujo@kind{\bujoMigrated}{\@firstofone}}
\newcommand{\scheduled}{\bujo@kind{\bujoScheduled}{\@firstofone}}
\newcommand{\dropped}{\bujo@kind{\bujoCancelled}{\sout}}
\newcommand{\event}{\bujo@kind{\bujoEvent}{\@firstofone}}
\newcommand{\note}{\bujo@kind{\bujoNote}{\@firstofone}}
\makeatother

%%%% A collection heading, and a titled sub-section inside one.
\newcommand{\bujocollection}[2]{%%
  \section*{#1}\addcontentsline{toc}{section}{#1}\label{bujo:#2}}
\newcommand{\bujogroup}[1]{\subsection*{#1}}

%%%% One line of the generated index: a title, a leader, and its page.
\newcommand{\bujoindexentry}[2]{%%
  \item[\bujoNote] \hyperref[bujo:#2]{#1}\dotfill\pageref{bujo:#2}}
"""

DOT_GRID = r"""
%%%% ---- dot grid ------------------------------------------------------------
%%%% A PDF tiling pattern, so a page of dots costs one object rather than
%%%% several thousand circles. Redefine \bujoDotSpacing to change the pitch.
\usepackage{tikz}
\usetikzlibrary{patterns}
\usepackage{eso-pic}

\newlength{\bujoDotSpacing}\setlength{\bujoDotSpacing}{%(spacing)s}
\newlength{\bujoDotRadius}\setlength{\bujoDotRadius}{%(radius)s}
\newlength{\bujoDotHalf}\setlength{\bujoDotHalf}{0.5\bujoDotSpacing}
\newcommand{\bujoDotColor}{%(color)s}

\pgfdeclarepatternformonly{bujodots}%%
  {\pgfpointorigin}%%
  {\pgfpoint{\bujoDotSpacing}{\bujoDotSpacing}}%%
  {\pgfpoint{\bujoDotSpacing}{\bujoDotSpacing}}%%
  {\pgfpathcircle{\pgfpoint{\bujoDotHalf}{\bujoDotHalf}}{\bujoDotRadius}\pgfusepath{fill}}

\newcommand{\bujoDotGrid}{%%
  \begin{tikzpicture}[remember picture,overlay]
    \fill[pattern=bujodots,pattern color=\bujoDotColor]
      (current page.south west) rectangle (current page.north east);
  \end{tikzpicture}}

%%%% Dots on this page only -- issue it right after a \clearpage.
\newcommand{\bujoDotThisPage}{\AddToShipoutPictureBG*{\bujoDotGrid}}
"""

#: Applied on top of DOT_GRID when every page should carry the grid.
DOT_ALL_PAGES = "\n\\AddToShipoutPictureBG{\\bujoDotGrid}\n"

#: Pad the document out to a whole signature, so it folds into a booklet.
SIGNATURE = r"""
%%%% ---- signature padding ---------------------------------------------------
%%%% A folded booklet needs a page count divisible by four. Any shortfall
%%%% becomes spare dotted pages at the back.
\newcount\bujoPages
\newcount\bujoWhole
\newcommand{\bujoPadToSignature}{%%
  \clearpage
  \loop
    \bujoPages=\value{page}\advance\bujoPages by -1
    \bujoWhole=\bujoPages
    \divide\bujoWhole by 4
    \multiply\bujoWhole by 4
    \ifnum\bujoWhole<\bujoPages
      %(dots)s\null\clearpage
  \repeat}
\AtEndDocument{\bujoPadToSignature}
"""


def emit(
    doc: Document,
    *,
    standalone: bool = True,
    calendar: bool | None = None,
    dots: bool | None = None,
    blank_dots: bool = True,
    page_breaks: bool = False,
    signature: bool = False,
    mono: bool | None = None,
    **_ignored,
) -> str:
    """Render *doc* as LaTeX.

    ``dots`` puts the grid on every page. ``blank_dots`` puts it on generated
    blank pages only, which is what a notebook wants: room to write is dotted,
    printed text is not. ``page_breaks`` starts each collection on a fresh
    page, and ``signature`` pads the result out to a multiple of four pages.
    ``mono`` prints every colour as black, for a printer that has only the one.
    """
    return _Latex(
        doc,
        standalone=standalone,
        calendar=calendar,
        dots=dots,
        blank_dots=blank_dots,
        page_breaks=page_breaks,
        signature=signature,
        mono=mono,
    ).render()


class _Latex:
    def __init__(
        self,
        doc: Document,
        *,
        standalone: bool,
        calendar: bool | None,
        dots: bool | None,
        blank_dots: bool = True,
        page_breaks: bool = False,
        signature: bool = False,
        mono: bool | None = None,
    ):
        self.doc = doc
        self.standalone = standalone
        self.links = link_map(doc)
        self.labels = dict(
            zip(
                (id(c) for c in doc.collections),
                unique([c.slug for c in doc.collections]),
            )
        )
        self.calendar = wants_calendar(doc, True) if calendar is None else calendar
        self.dots = meta_flag(doc, "dots", False) if dots is None else dots
        self.mono = meta_flag(doc, "mono", False) if mono is None else mono
        self.blank_dots = blank_dots
        self.page_breaks = page_breaks
        self.signature = signature
        self.blanks = [
            c for c in doc.collections if isinstance(c, DailyLog) and c.blank
        ]
        self.first = True
        self.out: list[str] = []

    @property
    def needs_dot_pattern(self) -> bool:
        return self.dots or (self.blank_dots and bool(self.blanks))

    # -- driver ------------------------------------------------------------

    def render(self) -> str:
        if self.standalone:
            self.out.append(self._preamble())
            self.out.append(r"\begin{document}")
            self._front_matter()
        for collection in self.doc.collections:
            self._collection(collection)
        if self.standalone:
            self.out.append(r"\end{document}")
        return "\n".join(self.out).rstrip() + "\n"

    def _preamble(self) -> str:
        meta = self.doc.meta
        preamble = PREAMBLE % {
            "fontsize": meta.get("fontsize", "11pt"),
            "geometry": _geometry(meta),
            **PALETTE[self.mono],
        }
        if self.needs_dot_pattern:
            preamble += DOT_GRID % {
                "spacing": meta.get("dot-spacing", "5mm"),
                "radius": meta.get("dot-size", "0.16mm"),
                "color": meta.get("dot-color", "black!30"),
            }
            if self.dots:
                preamble += DOT_ALL_PAGES
        if self.signature:
            pad = r"\bujoDotThisPage" if self.needs_dot_pattern and self.blank_dots else ""
            preamble += SIGNATURE % {"dots": pad}
        return preamble

    def _front_matter(self) -> None:
        meta = self.doc.meta
        if not meta.get("title"):
            return
        self.out.append(r"\begin{center}")
        self.out.append(rf"  {{\LARGE\sffamily\bfseries {esc(meta['title'])}}}\\[0.4em]")
        byline = " · ".join(
            esc(meta[k]) for k in ("subtitle", "author", "date") if meta.get(k)
        )
        if byline:
            self.out.append(rf"  {{\sffamily\color{{bujomuted}} {byline}}}")
        self.out.append(r"\end{center}")
        self.out.append(r"\vspace{1em}")

    # -- collections -------------------------------------------------------

    def _collection(self, collection: Collection) -> None:
        blank = isinstance(collection, DailyLog) and collection.blank

        self.out.append("")
        if (self.page_breaks or blank) and not self.first:
            self.out.append(r"\clearpage")
        if blank and self.blank_dots:
            # Must follow the \clearpage: it attaches to the next page shipped.
            self.out.append(r"\bujoDotThisPage")
        self.first = False

        self.out.append(
            rf"\bujocollection{{{esc(collection.title)}}}{{{self.labels[id(collection)]}}}"
        )

        if blank:
            # Anything pinned to this date from the Monthly Log prints at the
            # top; the rest of the page is left to write on.
            self._items(collection.items)
            self.out.append(r"\vspace*{\fill}")
            return
        if isinstance(collection, Index):
            self._index()
            return
        if isinstance(collection, Key):
            self._key()
            return
        if isinstance(collection, FutureLog):
            self._future(collection)
            return
        if isinstance(collection, MonthlyLog) and self.calendar:
            self._calendar(collection)
        else:
            self._items(collection.items)

    def _items(self, items) -> None:
        pending: list[Entry] = []
        for item in items:
            if isinstance(item, Group):
                self._flush(pending)
                self.out.append(rf"\bujogroup{{{esc(item.title)}}}")
                self._entries(item.entries)
            else:
                pending.append(item)
        self._flush(pending)

    def _flush(self, pending: list[Entry]) -> None:
        if pending:
            self._entries(list(pending))
            pending.clear()

    def _entries(self, entries: list[Entry], depth: int = 0) -> None:
        if not entries:
            return
        pad = "  " * depth
        self.out.append(rf"{pad}\begin{{bujoitems}}")
        for entry in entries:
            self.out.append(f"{pad}  {self._bullet(entry)}")
            self._entries(entry.children, depth + 1)
        self.out.append(rf"{pad}\end{{bujoitems}}")

    # -- one bullet --------------------------------------------------------

    def _bullet(self, entry: Entry, *, inline: bool = False) -> str:
        """One bullet, as the hand-writable macro for its kind.

        ``inline`` picks the starred form, which renders without a list item --
        what a date-column cell needs.
        """
        if entry.kind is Kind.TASK:
            name = _STATE_MACRO[entry.state or State.OPEN]
        elif entry.kind is Kind.EVENT:
            name = "event"
        else:
            name = "note"

        options = [_SIGNIFIER_KEY[s] for s in entry.signifiers]
        if entry.day:
            options.append(f"day={entry.day:02d}")
        if entry.time:
            options.append(f"at={esc(entry.time)}")
        if entry.target:
            options.append(f"to={esc(entry.target)}")

        text = "".join(self._span(s) for s in entry.spans).strip()
        star = "*" if inline else ""
        keys = f"[{','.join(options)}]" if options else ""
        return rf"\{name}{star}{keys}{{{text}}}"

    def _span(self, span: Span) -> str:
        match span:
            case Text(value=v):
                return esc(v)
            case Tag(name=n):
                return rf"\bujoTag{{{esc(n)}}}"
            case Context(name=n):
                return rf"\bujoContext{{{esc(n)}}}"
            case Ref(target=t):
                target = self.links.get(t.casefold())
                if target is None:
                    return rf"\textit{{{esc(t)}}}"
                label = self.labels[id(target)]
                return rf"\hyperref[bujo:{label}]{{\textit{{{esc(t)}}}}}"
        raise AssertionError(f"unhandled span {span!r}")  # pragma: no cover

    # -- generated collections --------------------------------------------

    def _index(self) -> None:
        self.out.append(r"\begin{bujoitems}")
        for collection in self.doc.collections:
            if isinstance(collection, Index):
                continue
            label = self.labels[id(collection)]
            self.out.append(
                rf"  \bujoindexentry{{{esc(collection.title)}}}{{{label}}}"
            )
        self.out.append(r"\end{bujoitems}")

    def _key(self) -> None:
        self.out.append(r"\begin{tabular}{@{}c@{\hspace{1.2em}}l@{\hspace{1.2em}}l@{}}")
        self.out.append(
            r"  \textbf{\sffamily\small Symbol} & \textbf{\sffamily\small Source} "
            r"& \textbf{\sffamily\small Meaning} \\[0.3em]"
        )
        for macro, source, meaning in LEGEND:
            self.out.append(rf"  {macro} & \texttt{{{source}}} & {meaning} \\")
        self.out.append(r"\end{tabular}")

    def _future(self, collection: FutureLog) -> None:
        """Render every month in the range, even the empty ones.

        A Future Log is a pre-drawn grid: the empty months are the point.
        """
        by_month = {}
        loose: list[Entry] = []
        for item in collection.items:
            if isinstance(item, Group):
                by_month[item.title.strip().casefold()] = item.entries
            else:
                loose.append(item)

        if loose:
            self._entries(loose)

        for year, month in collection.months():
            heading = f"{MONTHS[month - 1]} {year}"
            keys = (f"{year}-{month:02d}", heading.casefold(), MONTHS[month - 1].casefold())
            entries = next((by_month.pop(k) for k in keys if k in by_month), [])
            self.out.append(rf"\bujogroup{{{esc(heading)}}}")
            if entries:
                self._entries(entries)
            else:
                self.out.append(r"{\color{bujomuted}\small\itshape (nothing scheduled)}")

        for title, entries in by_month.items():  # groups outside the declared range
            self.out.append(rf"\bujogroup{{{esc(title)}}}")
            self._entries(entries)

    def _calendar(self, collection: MonthlyLog) -> None:
        """The date column of a monthly-log spread.

        Every day of the month gets a row, and a bullet pinned with ``09:``
        lands on it. Anything unpinned falls below the table, which is what the
        facing task page of a paper spread is for.
        """
        pinned: dict[int, list[Entry]] = {}
        loose: list = []
        for item in collection.items:
            if isinstance(item, Entry) and item.day:
                pinned.setdefault(item.day, []).append(item)
            else:
                loose.append(item)

        # longtable, not tabular: a month is 28-31 unbreakable rows, which on a
        # small page is taller than the text block and would spill off it.
        # The size goes on the table, not the columns: the row strut takes the
        # font in force when the row starts, so setting it per column leaves
        # every row as tall as the body text and a month stops fitting a page.
        self.out.append(
            r"{\footnotesize\setlength{\tabcolsep}{0pt}"
            r"\renewcommand{\arraystretch}{1.25}"
            r"\setlength{\LTpre}{0pt}\setlength{\LTpost}{0pt}"
        )
        self.out.append(
            r"\begin{longtable}{@{}>{\sffamily}r@{\hspace{0.5em}}"
            r">{\sffamily}l@{\hspace{1em}}"
            r"p{\dimexpr\linewidth-5em\relax}@{}}"
        )
        for day, name in month_days(collection.year, collection.month):
            cell = r"\newline ".join(
                # the row already names the day, so the pin is not repeated
                self._bullet(replace(entry, day=None), inline=True)
                for entry in pinned.get(day, [])
            )
            number, weekday = f"{day:02d}", name
            if name in ("Sat", "Sun"):
                number, weekday = rf"\bujoWeekend{{{number}}}", rf"\bujoWeekend{{{weekday}}}"
            self.out.append(rf"{number} & {weekday} & {cell}\\")
        self.out.append(r"\end{longtable}}")

        if loose:
            self.out.append(r"\vspace{1em}")
            self._items(loose)

def _geometry(meta: dict[str, str]) -> str:
    """Build the ``geometry`` option list.

    ``margin`` is the baseline on all four sides. Naming ``inner`` or ``outer``
    switches to a two-sided page whose gutter and outside edge differ, which is
    what a folded booklet wants: the fold in the middle of a sheet needs no
    clearance, while the outside edge is where a printer stops printing.
    Whichever of the two is left out falls back to ``margin``.
    """
    paper = meta.get("papersize", "a4paper")
    margin = meta.get("margin", "22mm")
    inner, outer = meta.get("inner"), meta.get("outer")
    if not (inner or outer):
        return f"{paper},margin={margin}"
    return ",".join(
        [
            paper,
            "twoside",
            f"inner={inner or margin}",
            f"outer={outer or margin}",
            f"top={margin}",
            f"bottom={margin}",
        ]
    )


def esc(text: str) -> str:
    """Escape LaTeX's ten special characters."""
    return "".join(_ESCAPES.get(ch, ch) for ch in text)
