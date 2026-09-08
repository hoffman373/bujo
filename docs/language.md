# The bujo language

A journal is a plain text file. It has two parts: metadata at the top, then a
run of collections. Everything is line oriented, and indentation is the only
nesting mechanism — the same rule a paper journal follows.

```
title: Field Notes            <- metadata
author: Your Name

day 2026-09-05:               <- a collection header
  *. Ship the compiler #work  <- a bullet
    x Write the lexer         <- nested under it
```

Blank lines are ignored. A line whose first non-space characters are `//` is a
comment.

## Metadata

Metadata is `key: value`, one per line, and must appear **before** the first
collection header. Keys are free-form; these are the ones the backends read:

| Key | Used by | Meaning |
| --- | --- | --- |
| `title` | both | Document title |
| `subtitle`, `author`, `date` | both | Byline under the title |
| `papersize` | LaTeX | `geometry` paper size, default `a4paper` |
| `margin` | LaTeX | Page margin, default `22mm` |
| `fontsize` | LaTeX | Class option, default `11pt` |
| `calendar` | both | `on`/`off` — draw the date column on monthly logs |
| `inner` | LaTeX | Gutter margin; naming it switches to a two-sided page |
| `outer` | LaTeX | Outside margin; whichever of the two is omitted falls back to `margin` |
| `mono` | LaTeX | `on`/`off` — print every colour as black, default off |
| `dots` | LaTeX | `on`/`off` — print a dot grid behind the page, default off |
| `dot-spacing` | LaTeX | Grid pitch, default `5mm` |
| `dot-size` | LaTeX | Dot radius, default `0.16mm` |
| `dot-color` | LaTeX | Any `xcolor` expression, default `black!30` |

Unknown keys are kept in the AST (and in Markdown front matter) and otherwise
ignored, so you can carry your own fields.

## Collections

Every bullet lives in a collection. A header sits at column zero and ends with
a colon; its contents are indented beneath it.

| Header | Meaning |
| --- | --- |
| `day YYYY-MM-DD ["heading"]:` | A Daily Log |
| `month YYYY-MM ["heading"]:` | A Monthly Log |
| `future YYYY-MM .. YYYY-MM:` | A Future Log spanning that inclusive month range |
| `collection "Name":` | Any custom collection |
| `index:` | Placeholder — the compiler generates the table of contents |
| `key:` | Placeholder — the compiler generates the legend of symbols |

`index` and `key` take no body. `index` becomes a linked contents list (with
page numbers in LaTeX); `key` becomes the symbol table.

### Groups

Inside a collection, a line that is just `Title:` opens a sub-section:

```
collection "Reading List":
  Fiction:
    x The Cartographer's Regret — Nell Auberon
  Technical:
    . The Little Typer
```

Groups are always direct children of their collection; they do not nest.

In a Future Log, a group titled `2026-10`, `October` or `October 2026` fills in
that month. Months in the range with no group still get a heading, because an
empty month is part of what a Future Log shows you.

## Bullets

A bullet is `[signifiers] marker text`. The marker must be followed by a space
or end the line.

| Marker | Bullet | Meaning |
| --- | --- | --- |
| `.` | Task | Something to do |
| `x` | Task | Done |
| `>` | Task | Migrated forward, usually into the next Monthly Log |
| `<` | Task | Scheduled out into the Future Log |
| `~` | Task | No longer relevant — struck through, not deleted |
| `o` | Event | Something that happened, or will |
| `-` | Note | A fact, an idea, an observation |

### Signifiers

Signifiers go to the *left* of the marker, and stack:

| Signifier | Meaning |
| --- | --- |
| `*` | Priority |
| `!` | Inspiration |
| `?` | Explore / research further |

```
*. Cut the release
*!. Both of those
!  An idea               <- a signifier on its own means a note
```

A signifier only counts as one when a marker, another signifier, or a space
follows it, so ordinary prose like `!important` is left alone.

### Nesting and continuations

Indent a bullet further than the one above it to nest it. Indent a line that is
*not* a bullet, and it continues the previous bullet's text:

```
- Nesting works because indentation is the whole grammar;
  a line with no bullet just continues the one above it
```

Tabs count as four columns.

### Date pins

Inside a `month` block, a bullet may lead with a day of the month. It then
prints on that day's row of the monthly date column, and — in the weekly
notebook — at the head of that day's writing page, so an appointment entered
once turns up where you need it without being retyped:

```
month 2026-09:
  o 09: 1545 Doctor @clinic
  . 12: Pay the water bill
  . Replace the pump seal            <- unpinned, falls below the date column
```

The space after the colon is what separates a pin from a time: `09: 1545` pins
to the 9th at 15:45, while `09:30` is simply half past nine. A day outside the
month is an error, and pins are only read inside `month` blocks — elsewhere
`12: something` is ordinary text.

### Times and migration targets

An event whose text starts with a clock reading has it lifted out and rendered
separately. Three forms are accepted — `09:30`, `3:45pm`, and the bare 24-hour
`0930` — singly or as a range, and all are normalised to `HH:MM`:

```
o 09:30-10:00 Standup
o 1545 Doctor @clinic
```

The bare form is ambiguous with a four-digit year: an event starting `2026`
reads as 20:26. Anything out of range (`2400`, `2360`) stays as text, and a
date like `2026-09-09` is never mistaken for one.

A migrated or scheduled task may name where it went, with `->` or `→`. Using it
on any other kind of task is an error — the arrow means "this moved".

```
> Write the manual -> 2026-10
< Renew passport   -> before travel
```

## Inline markup

| Syntax | Meaning | LaTeX | Markdown |
| --- | --- | --- | --- |
| `#tag` | Topic label | coloured small caps | code span |
| `@context` | Person, place, situation | grey small caps | code span |
| `[[Name]]` | *Thread* to another collection | `\hyperref` | anchor link |

A `[[ref]]` resolves case-insensitively against each collection's title plus
its short aliases: a Daily Log also answers to its ISO date (`[[2026-09-05]]`),
a Monthly Log to `[[2026-09]]` and `[[September 2026]]`, a Future Log to
`[[Future Log]]`. An unresolved ref renders as italic text rather than
failing — collections get written before they exist.

## Errors

Every problem in a file is reported in one pass, with the offending line and a
caret:

```
journal.bujo:3:1: error: only migrated (>) and scheduled (<) tasks take a '-> destination'
     3 |   . Manual -> 2026-10
       | ^
  hint: use `>` to migrate the task or drop the arrow
```

## Notebook layouts

`--layout weekly` rebuilds the document as a foldable paper notebook rather
than a report. It is a transform over the parsed journal, so it works from the
same source file as an ordinary build:

```sh
bujo pdf journal.bujo --layout weekly --week 2026-09-09 -o week.pdf
```

* Pages are **5.5 × 8.5 in** — half a Letter sheet, folded on the long edge.
  `--paper` takes any `geometry` spec if you fold something else.
* Margins are two-sided: a `0.375in` gutter, and `margin` on the outside. Two
  facing pages put their gutters together at the fold, in the middle of the
  sheet, where no printer clips — so the wide margin is spent only on the
  edges that need it. Set `inner`/`outer` in the file to change either.
* Collections are reordered front to back the way a Bullet Journal is ordered:
  Index, Key, Future Log, Monthly Logs, custom collections, then the Daily Logs
  you have already written up, in date order.
* Each collection starts on its own page.
* After them comes **one blank page per day of the week**, carrying just its
  date, ruled with dots. `--blanks remaining` skips the days already written
  up; `--week-start sunday` shifts the week.
* The printed pages carry **no dots** — the grid is for the pages you write on.
  `--no-dots` removes it there too, `--dots` adds it everywhere.
* The page count is padded to a multiple of four with spare dotted pages, so
  the stack folds into a signature.

`--week` takes any date in the target week and defaults to today.

### Printing it

`--booklet` does the imposition itself, so you do not have to trust a print
dialog:

```sh
bujo pdf journal.bujo --layout weekly --booklet -o week.pdf
```

Each Letter sheet then carries two journal pages, ordered so that printing
double sided and folding the stack down the middle puts them back in reading
order. `--sheet` takes any `geometry` spec if you are folding something other
than Letter.

`--flip` has to match how your printer turns the sheet over:

| | |
| --- | --- |
| `--flip short-edge` (default) | The back is printed the same way up as the front. |
| `--flip long-edge` | Every back sheet is rotated half a turn, which is what a tumbling duplexer needs. |

Drivers disagree about whether "long edge" is measured against the paper or
against the printed image, and the sheets here are landscape, so do not trust
the label — trust the symptom. **If the backs come out upside down, and their
two pages on the wrong halves, rebuild with the other value.** Both faults have
the same cause: a half turn is also a left-right swap.

Without `--booklet` the pages come out one per sheet in reading order, which is
what you want if your printer's own *Booklet* mode is doing the imposition.
