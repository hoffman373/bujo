# bujo

A small domain specific language for [bullet journaling](https://bulletjournal.com/),
and a compiler that turns it into **LaTeX**, **Markdown** or **JSON**.

You write rapid-logging notation more or less the way you'd write it on paper:

```
title: Field Notes
author: J. Doe

index:
key:

future 2026-10 .. 2027-03:
  2026-10:
    o Conference in Berlin, 12th–15th
    . Renew passport

day 2026-09-05 "and it rained":
  < Renew passport -> 2026-10
  *. Ship the compiler #work
    x Write the lexer
    ~ Hand-roll a PEG grammar
    > Finish the manual -> 2026-09-08
  o 09:30–10:00 Standup with @team
  ! Idea: emit an ICS file too, so events land in a calendar #ideas
  - Nesting works because indentation is the whole grammar

collection "Reading List":
  Fiction:
    x The Cartographer's Regret — Nell Auberon
    . Vellum and Ash — J. M. Rooke
```

…and get back a typeset journal, or a Markdown file whose tasks stay checkable
on GitHub.

## Install

Pure Python 3.11+, no runtime dependencies.

```sh
python3 -m venv .venv && .venv/bin/pip install -e .   # provides the `bujo` command
python3 -m bujo --help                                # or run it from the source tree
```

A virtual environment because recent Debian and Ubuntu refuse `pip install`
into the system Python. To put `bujo` on your PATH afterwards, link it:
`ln -s "$PWD/.venv/bin/bujo" ~/.local/bin/bujo`.

`bujo pdf` additionally needs a TeX installation. Everything it loads is in
TeX Live: `geometry`, `graphicx`, `array`, `enumitem`, `pifont`, `ulem`,
`xcolor`, `titlesec`, `longtable` and `hyperref` always; `tikz` and `eso-pic`
for the dot grid; `pdfpages` for `--booklet`.

## Use

```sh
bujo journal.bujo                       # LaTeX to stdout
bujo compile journal.bujo -f markdown -o journal.md
bujo compile journal.bujo --fragment    # body only, to \input elsewhere
bujo pdf journal.bujo -o journal.pdf    # runs pdflatex twice, so the index gets pages
bujo pdf journal.bujo --dots            # on a 5mm grid of light grey dots
bujo pdf journal.bujo --mono            # every colour as black, for a laser printer
bujo check journal.bujo                 # parse only, report every error
bujo stats journal.bujo                 # counts by state, for a migration review
```

And to print a week of it as a notebook:

```sh
bujo pdf journal.bujo --layout weekly                    # this week, one page per sheet
bujo pdf journal.bujo --layout weekly --week 2026-09-14  # some other week
bujo pdf journal.bujo --layout weekly --booklet          # imposed two-up, ready to fold
bujo pdf journal.bujo --layout weekly --booklet --flip long-edge   # for a tumbling duplexer
```

```
$ bujo stats examples/september.bujo
collections  7
tasks        21
events       5
notes        6

  open       10
  done       6
  migrated   2
  scheduled  1
  cancelled  2

completion   33%

tags
  #work      2
  #family    1
  #ideas     1
  #health    1
```

Or use it as a library:

```python
from bujo import parse, emit

doc = parse(open("journal.bujo").read())
print(emit(doc, "markdown"))

for entry in doc.entries():
    if entry.state and entry.state.value == "open":
        print(entry.text)
```

## Notation

```
  .  task              *  priority        #tag        topic
  x  done              !  inspiration     @context    person / place
  >  migrated          ?  explore         [[Name]]    thread to a collection
  <  scheduled
  ~  irrelevant        o  event           ->          where a task moved
                       -  note
```

Signifiers go to the left of the marker and stack (`*!. both of those`); a
signifier on its own is shorthand for a note. Indentation nests, and an
indented line with no marker continues the bullet above it.

Inside a `month`, a bullet can be pinned to a day — `o 09: 1545 Doctor` — which
puts it on that row of the monthly date column and at the top of that day's
page in the weekly notebook.

Collections are `day`, `month`, `future`, `collection`, plus two the compiler
fills in for you: `index` (a linked table of contents, with page numbers in
LaTeX) and `key` (the legend above, generated so it can never drift from what
the compiler actually emits).

Full reference: [`docs/language.md`](docs/language.md).

## Output

**LaTeX.** A standalone `article` that builds with plain `pdflatex`. `--mono`
prints every colour as black, for a laser printer that has only the one — the
hierarchy survives on size and typeface. `--dots`
prints the page on a 5mm grid of light grey dots, the way a bullet journal
notebook is ruled; it is a single PDF tiling pattern rather than a few thousand
circles, and `dot-spacing`, `dot-size` and `dot-color` metadata retune it. Every
glyph is a `\newcommand` in the preamble — redefine `\bujoTask`, `\bujoDone`
and friends to change the notation across the whole journal without touching
the generated body. The body itself is written in bullet macros —
`\task[priority]{...}`, `\migrated[to=2026-10]{...}`, `\event[at=09:30]{...}` —
so it can be read and edited by hand rather than being a write-only blob. A Monthly Log gets the date column of a paper spread, with
pinned bullets on their own day's row; a Future Log draws every month in its
range, including the empty ones, because that is half of what a future log is
for.

**Weekly notebook.** `--layout weekly` builds the journal as paper instead of
a report: 5.5 × 8.5 in pages (half a Letter sheet, folded on the long edge)
with a two-sided margin — a narrow gutter that meets its neighbour at the fold,
and the wide margin spent on the outside edges where a printer actually clips —
collections reordered Index → Key → Future Log → Monthly → collections →
written-up days, each on its own page, and then a blank dotted page per day of
the coming week with the date at the top. Printed pages stay clean; only the
pages you write on are ruled. The page count is padded to a multiple of four so
the stack folds into a signature. `--booklet` does the imposition too: each
Letter sheet gets two journal pages in signature order, so printing double
sided and folding down the middle gives you the notebook. Match `--flip` to how
your printer turns the sheet over — if the backs come out upside down, rebuild
with the other value.

**Markdown.** Tasks become GitHub task-list items, so `- [ ]` and `- [x]` stay
checkable in a repo. The three states GitHub has no checkbox for keep their
journal notation inside the brackets — `[>]`, `[<]`, `[~]` — which reads
correctly whether or not anything renders it. Cancelled tasks are struck
through, refs become anchor links, and a date pin prints as a bold day number
since there is no date column to put it in.

**JSON.** The parsed tree, for anything else you want to do with it.

## Layout

```
bujo/
  lexer.py       line oriented; records indentation, peels signifiers and markers
  parser.py      tokens -> AST, with error recovery so one bad header
                 doesn't cascade into a page of complaints
  inline.py      #tags, @contexts, [[refs]], event times, -> targets
  model.py       the AST, and the vocabulary: Kind, State, Signifier
  notebook.py    the weekly layout, and print production: reorder, writing
                 pages, half-Letter paper, two-up imposition
  errors.py      diagnostics with line, column, source and a hint
  emit/
    latex.py     standalone or fragment
    markdown.py  GitHub flavoured
    jsonout.py   the AST
  cli.py         compile | check | stats | pdf
docs/language.md   the full language reference
examples/september.bujo
tests/
```

## Tests

```sh
.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
```

160 tests, covering the grammar, both text backends, the CLI, and — when
`pdflatex` is present — that the generated LaTeX really compiles, and that a
weekly notebook comes out half-Letter with a page count that folds, and that
`--booklet` really does put two of those pages on every sheet.
