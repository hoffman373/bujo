import datetime as dt
import re
import shutil
import subprocess

import pytest

from bujo import emit, parse
from bujo.model import DailyLog
from bujo.notebook import HALF_LETTER, booklet, tumble, week_of, weekly

SRC = """\
title: Field Notes
papersize: a4paper

index:
key:
collection "Reading List":
  . A book
future 2026-10 .. 2026-11:
  2026-10:
    . Renew passport
month 2026-09:
  . Monthly thing
day 2026-09-09:
  . Midweek thing
day 2026-09-07:
  . Monday thing
"""

WEDNESDAY = dt.date(2026, 9, 9)


@pytest.fixture
def notebook():
    return weekly(parse(SRC), WEDNESDAY)


# -- the week ---------------------------------------------------------------

def test_week_runs_monday_to_sunday():
    days = week_of(WEDNESDAY)
    assert days[0] == dt.date(2026, 9, 7) and days[-1] == dt.date(2026, 9, 13)
    assert len(days) == 7


def test_week_can_start_on_sunday():
    days = week_of(WEDNESDAY, "sunday")
    assert days[0] == dt.date(2026, 9, 6) and days[-1] == dt.date(2026, 9, 12)


def test_any_day_of_the_week_selects_the_same_week():
    assert week_of(dt.date(2026, 9, 7)) == week_of(dt.date(2026, 9, 13))


def test_unknown_week_start_is_rejected():
    with pytest.raises(ValueError, match="unknown week start"):
        week_of(WEDNESDAY, "caturday")


def test_week_defaults_to_today():
    nb = weekly(parse(SRC))
    blanks = [c.date for c in nb.collections if getattr(c, "blank", False)]
    assert dt.date.today() in blanks


# -- ordering ---------------------------------------------------------------

def test_collections_are_ordered_front_to_back(notebook):
    assert [type(c).__name__ for c in notebook.collections[:5]] == [
        "Index", "Key", "FutureLog", "MonthlyLog", "CustomCollection",
    ]


def test_written_days_come_before_the_blanks_and_are_sorted(notebook):
    days = [c for c in notebook.collections if isinstance(c, DailyLog)]
    assert [d.date.day for d in days] == [7, 9, 7, 8, 9, 10, 11, 12, 13]
    assert [d.blank for d in days[:2]] == [False, False]
    assert all(d.blank for d in days[2:])


def test_a_blank_page_per_day_by_default(notebook):
    assert sum(1 for c in notebook.collections if getattr(c, "blank", False)) == 7


def test_blanks_remaining_skips_days_already_written_up():
    nb = weekly(parse(SRC), WEDNESDAY, blanks="remaining")
    blanks = [c.date.day for c in nb.collections if getattr(c, "blank", False)]
    assert blanks == [8, 10, 11, 12, 13]


def test_invalid_blanks_mode_is_rejected():
    with pytest.raises(ValueError, match="blanks must be"):
        weekly(parse(SRC), WEDNESDAY, blanks="some")


def test_blank_pages_carry_only_their_date(notebook):
    blank = next(c for c in notebook.collections if getattr(c, "blank", False))
    assert blank.items == []
    assert blank.title == "2026-09-07 · Monday"


def test_the_source_document_is_not_mutated():
    doc = parse(SRC)
    weekly(doc, WEDNESDAY)
    assert doc.meta["papersize"] == "a4paper"
    assert not any(getattr(c, "blank", False) for c in doc.collections)


# -- paper ------------------------------------------------------------------

def test_paper_size_overrides_the_file(notebook):
    assert notebook.meta["papersize"] == HALF_LETTER == "paperwidth=5.5in,paperheight=8.5in"


def test_paper_size_can_be_chosen():
    nb = weekly(parse(SRC), WEDNESDAY, paper="a6paper")
    assert nb.meta["papersize"] == "a6paper"


def test_margin_from_the_file_is_kept():
    nb = weekly(parse("margin: 20mm\n\nday 2026-09-09:\n  . a\n"), WEDNESDAY)
    assert nb.meta["margin"] == "20mm"


# -- rendering --------------------------------------------------------------

def _collection(tex, label):
    """Where the collection with this label opens.

    Not just a search for the label: the generated index mentions it too, and
    earlier in the file.
    """
    m = re.search(r"\\bujocollection\{[^}]*\}\{" + re.escape(label) + r"\}", tex)
    assert m, f"no collection labelled {label}"
    return m.start()


def _blank_pages(notebook):
    return [c for c in notebook.collections if getattr(c, "blank", False)]


def _weekly_tex(notebook, **options):
    return emit(notebook, "latex", page_breaks=True, signature=True, **options)


def _body(notebook, **options):
    """The document body only -- the preamble defines macros that use the
    same names, and counting those would prove nothing."""
    tex = _weekly_tex(notebook, **options)
    return tex[tex.index(r"\begin{document}") :]


def test_only_blank_pages_get_dots(notebook):
    # never document-wide, so every printed page stays clean
    assert "\\AddToShipoutPictureBG{\\bujoDotGrid}" not in _weekly_tex(notebook)

    lines = _body(notebook).splitlines()
    dotted = [lines[i + 1] for i, line in enumerate(lines) if line == r"\bujoDotThisPage"]
    # compare titles, not labels: a writing page for a day already written up
    # gets a numbered label so the two do not collide
    titles = {line.split("}{")[0].removeprefix(r"\bujocollection{") for line in dotted}
    assert titles == {c.title for c in _blank_pages(notebook)}
    assert len(dotted) == 7


def test_blank_pages_start_on_a_fresh_page_after_the_dots(notebook):
    # The order matters: \bujoDotThisPage attaches to the next page shipped.
    assert (
        "\\clearpage\n\\bujoDotThisPage\n\\bujocollection{2026-09-08 · Tuesday}"
        in _weekly_tex(notebook)
    )


def test_blank_pages_are_empty_below_the_date(notebook):
    tex = _weekly_tex(notebook)
    after = tex[_collection(tex, "day-2026-09-13") :]
    assert after.split("\n")[1] == r"\vspace*{\fill}"
    assert "bujoitems" not in after


def test_every_collection_starts_a_page(notebook):
    assert _body(notebook).count(r"\clearpage") == len(notebook.collections) - 1


def test_signature_padding_is_requested(notebook):
    assert r"\AtEndDocument{\bujoPadToSignature}" in _weekly_tex(notebook)


def test_padding_pages_are_dotted_too(notebook):
    tex = _weekly_tex(notebook)
    padding = tex[tex.index(r"\newcommand{\bujoPadToSignature}") :]
    assert r"\bujoDotThisPage\null\clearpage" in padding


def test_no_dots_leaves_the_writing_pages_clean(notebook):
    tex = _weekly_tex(notebook, dots=False, blank_dots=False)
    assert "bujodots" not in tex


def test_dots_everywhere_is_still_possible(notebook):
    tex = _weekly_tex(notebook, dots=True)
    assert "\\AddToShipoutPictureBG{\\bujoDotGrid}" in tex


def test_markdown_shows_the_blank_days_as_empty_headings(notebook):
    md = emit(notebook, "markdown")
    assert "## 2026-09-13 · Sunday" in md
    assert md.index("## 2026-09-07 · Monday") < md.index("## 2026-09-08 · Tuesday")


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_the_notebook_compiles_to_a_whole_signature(notebook, tmp_path):
    (tmp_path / "n.tex").write_text(_weekly_tex(notebook), encoding="utf-8")
    for _ in range(2):
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "n.tex"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout[-3000:]

    info = subprocess.run(
        ["pdfinfo", str(tmp_path / "n.pdf")], capture_output=True, text=True
    ).stdout
    pages = int(next(l for l in info.splitlines() if l.startswith("Pages")).split()[1])
    assert pages % 4 == 0, f"{pages} pages will not fold into a booklet"
    assert "396 x 612 pts" in info  # 5.5in x 8.5in, half a Letter sheet


# -- booklet imposition -----------------------------------------------------

def test_booklet_wrapper_imposes_two_up_in_signature_order():
    tex = booklet("week.pdf")
    assert r"\includepdf[pages=-,booklet,nup=2x1,noautoscale]{week.pdf}" in tex
    assert r"\usepackage[letterpaper,landscape,margin=0pt]{geometry}" in tex


def test_booklet_sheet_is_configurable():
    assert "a4paper,landscape" in booklet("w.pdf", "a4paper,landscape,margin=0pt")


def test_tumble_rotates_only_the_back_of_each_sheet():
    lines = [l for l in tumble("w.pdf", 6).splitlines() if l.startswith(r"\includepdf")]
    assert len(lines) == 6
    assert [i for i, l in enumerate(lines, 1) if "angle=180" in l] == [2, 4, 6]
    assert lines[0] == r"\includepdf[pages={1},noautoscale]{w.pdf}"
    assert lines[1] == r"\includepdf[pages={2},noautoscale,angle=180]{w.pdf}"


def test_tumble_needs_at_least_one_sheet():
    with pytest.raises(ValueError, match="at least one sheet"):
        tumble("w.pdf", 0)


# -- folded margins ---------------------------------------------------------

def test_the_notebook_gutter_is_tighter_than_the_outside_edge(notebook):
    assert notebook.meta["inner"] == "0.375in"
    assert "outer" not in notebook.meta  # falls back to margin, the wide side


def test_an_explicit_gutter_in_the_file_wins():
    nb = weekly(parse("inner: 0.5in\n\nday 2026-09-09:\n  . a\n"), WEDNESDAY)
    assert nb.meta["inner"] == "0.5in"


# -- pinned entries reaching their day --------------------------------------

PINNED_SRC = """\
month 2026-09:
  o 09: 1545 Doctor @clinic
  . 12: Pay the water bill
  . Unpinned task
month 2026-10:
  o 09: Not this month
"""


def test_a_pinned_entry_heads_the_page_for_its_day():
    nb = weekly(parse(PINNED_SRC), WEDNESDAY)
    pages = {c.date.day: c for c in nb.collections if getattr(c, "blank", False)}
    assert [e.text for e in pages[9].items] == ["Doctor @clinic"]
    assert [e.text for e in pages[12].items] == ["Pay the water bill"]
    assert pages[8].items == []          # nothing pinned to the 8th
    assert pages[10].items == []


def test_only_the_matching_month_contributes():
    nb = weekly(parse(PINNED_SRC), WEDNESDAY)
    pages = {c.date.day: c for c in nb.collections if getattr(c, "blank", False)}
    assert all(e.text != "Not this month" for e in pages[9].items)


def test_the_copy_drops_its_pin_because_the_heading_says_the_date():
    nb = weekly(parse(PINNED_SRC), WEDNESDAY)
    page = next(c for c in nb.collections if getattr(c, "blank", False) and c.date.day == 9)
    assert page.items[0].day is None


def test_the_monthly_spread_keeps_its_copy():
    doc = parse(PINNED_SRC)
    weekly(doc, WEDNESDAY)
    month = doc.collections[0]
    assert [e.day for e in month.items] == [9, 12, None]


def test_a_writing_page_with_fixtures_still_gets_its_dots_and_space():
    nb = weekly(parse(PINNED_SRC), WEDNESDAY)
    tex = emit(nb, "latex", page_breaks=True, signature=True)
    start = _collection(tex, "day-2026-09-09")
    block = tex[start:]
    assert r"\bujoDotThisPage" in tex[:start]
    assert "Doctor" in block.split(r"\vspace*{\fill}")[0]
