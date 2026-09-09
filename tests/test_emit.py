import json
import shutil
import subprocess

import pytest

from bujo import emit, parse

SRC = """\
title: Field Notes
author: D

index:
key:

future 2026-10 .. 2026-12:
  2026-10:
    < Renew passport -> before travel

month 2026-09:
  . Monthly thing

day 2026-09-05 "rain":
  *. Ship it #work
    x Sub task
    ~ Dropped idea
    > Manual -> 2026-10
  o 09:30 Standup with @team
  ! Idea about [[Reading List]]
  - 100% of $5 & <angles> #a_b

collection "Reading List":
  Fiction:
    x The Cartographer's Regret
"""


@pytest.fixture(scope="module")
def doc():
    return parse(SRC)


# -- LaTeX -----------------------------------------------------------------

def test_latex_is_standalone_by_default(doc):
    tex = emit(doc, "latex")
    assert tex.startswith("\\documentclass")
    assert "\\begin{document}" in tex and tex.rstrip().endswith("\\end{document}")


def test_latex_fragment_has_no_preamble(doc):
    tex = emit(doc, "latex", standalone=False)
    assert "\\documentclass" not in tex and r"\bujocollection{Index}" in tex


def test_latex_escapes_special_characters(doc):
    tex = emit(doc, "latex")
    assert r"100\% of \$5 \& \textless{}angles\textgreater{}" in tex
    assert r"\bujoTag{a\_b}" in tex


def test_latex_markers_and_signifiers(doc):
    tex = emit(doc, "latex")
    assert r"\task[priority]{Ship it \bujoTag{work}}" in tex
    assert r"\done{Sub task}" in tex
    assert r"\dropped{Dropped idea}" in tex
    assert r"\event[at=09:30]{Standup with \bujoContext{team}}" in tex
    assert r"\migrated[to=2026-10]{Manual}" in tex


def test_latex_refs_become_hyperlinks(doc):
    assert r"\hyperref[bujo:reading-list]" in emit(doc, "latex")


def test_latex_unresolved_ref_falls_back_to_italics():
    tex = emit(parse("day 2026-09-05:\n  - see [[Nowhere]]\n"), "latex", standalone=False)
    assert r"\textit{Nowhere}" in tex and "hyperref" not in tex


def test_latex_future_log_draws_empty_months(doc):
    tex = emit(doc, "latex")
    for month in ("October 2026", "November 2026", "December 2026"):
        assert f"\\bujogroup{{{month}}}" in tex
    assert "(nothing scheduled)" in tex


def test_latex_calendar_is_optional(doc):
    assert "01 & Tue &" in emit(doc, "latex", calendar=True)
    assert "01 & Tue &" not in emit(doc, "latex", calendar=False)


def test_latex_calendar_does_not_consume_the_entries(doc):
    once = emit(doc, "latex", calendar=True)
    assert once == emit(doc, "latex", calendar=True)
    assert once.count("Monthly thing") == 1


def test_calendar_meta_overrides_the_default():
    src = "calendar: off\n\nmonth 2026-09:\n  . x\n"
    assert r"\begin{longtable}" not in emit(parse(src), "latex")


# -- Markdown ---------------------------------------------------------------

def test_markdown_task_states(doc):
    md = emit(doc, "markdown")
    assert "- [ ] `*` Ship it `#work`" in md
    assert "  - [x] Sub task" in md
    assert "  - [~] ~~Dropped idea~~" in md
    assert "  - [>] Manual → *2026-10*" in md


def test_markdown_events_and_notes(doc):
    md = emit(doc, "markdown")
    assert "- ○ **09:30** Standup with `@team`" in md
    assert "- `!` Idea about [Reading List](#reading-list)" in md


def test_markdown_escapes_metacharacters(doc):
    assert r"100% of $5 & \<angles\>" in emit(doc, "markdown")


def test_markdown_index_links_every_other_collection(doc):
    md = emit(doc, "markdown")
    assert "- [Key](#key)" in md
    assert "- [Reading List](#reading-list)" in md
    assert md.count("- [Index](#index)") == 0


def test_markdown_anchors_match_github_double_dash_rule(doc):
    md = emit(doc, "markdown")
    assert "(#2026-09-05--saturday--rain)" in md


def test_markdown_front_matter_is_opt_in(doc):
    assert not emit(doc, "markdown").startswith("---")
    assert emit(doc, "markdown", front_matter=True).startswith("---\ntitle: Field Notes")


def test_markdown_has_no_double_blank_lines(doc):
    assert "\n\n\n" not in emit(doc, "markdown")


# -- JSON -------------------------------------------------------------------

def test_json_round_trips_the_tree(doc):
    data = json.loads(emit(doc, "json"))
    assert data["meta"]["title"] == "Field Notes"
    day = next(c for c in data["collections"] if c["type"] == "DailyLog")
    assert day["date"] == "2026-09-05" and day["heading"] == "rain"
    task = day["items"][0]
    assert task["signifiers"] == ["priority"]
    assert [c["state"] for c in task["children"]] == ["done", "cancelled", "migrated"]


def test_unknown_format_is_rejected(doc):
    with pytest.raises(ValueError, match="unknown format"):
        emit(doc, "postscript")


# -- the generated LaTeX actually builds ------------------------------------

@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_generated_latex_compiles(doc, tmp_path):
    (tmp_path / "j.tex").write_text(emit(doc, "latex"), encoding="utf-8")
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "j.tex"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert (tmp_path / "j.pdf").exists()


# -- threading --------------------------------------------------------------

@pytest.mark.parametrize("ref", ["Reading List", "reading list", "2026-09-05", "September 2026"])
def test_refs_resolve_by_alias(ref):
    src = SRC + f'\nday 2026-09-07:\n  - see [[{ref}]]\n'
    assert "](#" in emit(parse(src), "markdown").splitlines()[-1]


# -- dot grid ---------------------------------------------------------------

def test_dot_grid_is_off_by_default(doc):
    assert "bujodots" not in emit(doc, "latex")


def test_dot_grid_defaults_to_5mm_light_grey(doc):
    tex = emit(doc, "latex", dots=True)
    assert r"\setlength{\bujoDotSpacing}{5mm}" in tex
    assert r"\newcommand{\bujoDotColor}{black!30}" in tex
    assert r"\setlength{\bujoDotRadius}{0.16mm}" in tex
    assert "pattern=bujodots" in tex


def test_dot_grid_metadata_enables_and_configures_it():
    src = "dots: on\ndot-spacing: 4mm\ndot-size: 0.2mm\ndot-color: gray!50\n\nday 2026-09-05:\n  . a\n"
    tex = emit(parse(src), "latex")
    assert r"\setlength{\bujoDotSpacing}{4mm}" in tex
    assert r"\setlength{\bujoDotRadius}{0.2mm}" in tex
    assert r"\newcommand{\bujoDotColor}{gray!50}" in tex


def test_explicit_flag_overrides_the_metadata():
    src = "dots: on\n\nday 2026-09-05:\n  . a\n"
    assert "bujodots" not in emit(parse(src), "latex", dots=False)


def test_dot_grid_is_a_preamble_feature(doc):
    assert "bujodots" not in emit(doc, "latex", standalone=False, dots=True)


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_dotted_latex_compiles(doc, tmp_path):
    (tmp_path / "d.tex").write_text(emit(doc, "latex", dots=True), encoding="utf-8")
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "d.tex"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]


# -- page geometry ----------------------------------------------------------

def _geometry_options(doc):
    line = next(l for l in emit(doc, "latex").splitlines() if l.endswith("{geometry}"))
    return line[line.index("[") + 1 : line.rindex("]")]


def test_margin_alone_is_symmetric(doc):
    assert _geometry_options(doc) == "a4paper,margin=22mm"


def test_naming_inner_switches_to_a_two_sided_page():
    src = "papersize: letterpaper\nmargin: 0.625in\ninner: 0.375in\n\nday 2026-09-05:\n  . a\n"
    assert _geometry_options(parse(src)) == (
        "letterpaper,twoside,inner=0.375in,outer=0.625in,top=0.625in,bottom=0.625in"
    )


def test_the_side_left_out_falls_back_to_margin():
    src = "margin: 20mm\nouter: 30mm\n\nday 2026-09-05:\n  . a\n"
    assert "inner=20mm,outer=30mm" in _geometry_options(parse(src))


# -- mono, and unique labels ------------------------------------------------

def test_colours_survive_by_default(doc):
    tex = emit(doc, "latex")
    assert r"\definecolor{bujoaccent}{HTML}{9C4221}" in tex
    assert r"\newcommand{\bujoWeekend}[1]{\textcolor{bujomuted}{#1}}" in tex


def test_mono_prints_every_colour_black(doc):
    tex = emit(doc, "latex", mono=True)
    for name in ("bujoink", "bujomuted", "bujoaccent"):
        assert rf"\definecolor{{{name}}}{{HTML}}{{000000}}" in tex
    # weekends lose their grey, so they lean instead
    assert r"\newcommand{\bujoWeekend}[1]{\textit{#1}}" in tex


def test_mono_metadata_enables_it():
    assert "{HTML}{000000}" in emit(parse("mono: on\n\nday 2026-09-05:\n  . a\n"), "latex")


def test_repeated_collections_get_distinct_labels():
    src = "index:\nday 2026-09-05:\n  . written up\nday 2026-09-05:\n  . again\n"
    tex = emit(parse(src), "latex")
    assert r"\bujocollection{2026-09-05 · Saturday}{day-2026-09-05}" in tex
    assert r"\bujocollection{2026-09-05 · Saturday}{day-2026-09-05-2}" in tex
    # ...and the index points at the second one, not twice at the first
    assert r"\bujoindexentry{2026-09-05 · Saturday}{day-2026-09-05-2}" in tex


def test_repeated_headings_get_github_style_anchors():
    src = "index:\nday 2026-09-05:\n  . a\nday 2026-09-05:\n  . b\n"
    md = emit(parse(src), "markdown")
    assert "(#2026-09-05--saturday)" in md
    assert "(#2026-09-05--saturday-1)" in md


# -- pinned monthly entries -------------------------------------------------

PINNED = """\
month 2026-09:
  o 09: 1545 Doctor
  . 09: Bring the referral
  . Unpinned task
"""


def test_the_date_column_carries_its_pinned_entries():
    tex = emit(parse(PINNED), "latex", calendar=True)
    assert r"09 & Wed & \event*[at=15:45]{Doctor}" in tex
    # two on one day stack inside the cell
    assert r"\newline \task*{Bring the referral}" in tex
    # ...and the row does not repeat the date the column already shows
    assert "day=09" not in tex


def test_a_month_uses_longtable_so_its_rows_can_break():
    tex = emit(parse(PINNED), "latex", calendar=True)
    assert r"\begin{longtable}" in tex and r"\begin{tabular}" not in tex


def test_unpinned_entries_fall_below_the_date_column():
    tex = emit(parse(PINNED), "latex", calendar=True)
    assert tex.index(r"\end{longtable}") < tex.index("Unpinned task")


def test_without_a_date_column_a_pin_prints_on_the_bullet():
    tex = emit(parse(PINNED), "latex", calendar=False)
    assert r"\event[day=09,at=15:45]{Doctor}" in tex
    assert r"\begin{longtable}" not in tex


def test_markdown_prints_the_pin_since_it_has_no_date_column():
    md = emit(parse(PINNED), "markdown")
    assert "- ○ **09** **15:45** Doctor" in md
    assert "- [ ] **09** Bring the referral" in md


# -- the hand-writable macro layer ------------------------------------------

def test_the_body_is_written_in_bullet_macros(doc):
    """The point of the layer: the body should be editable without knowing how
    a marker is assembled."""
    tex = emit(doc, "latex", standalone=False)
    assert r"\item[" not in tex
    assert r"\section*" not in tex and r"\subsection*" not in tex


def test_starred_bullets_render_without_a_list_item():
    tex = emit(parse(PINNED), "latex", calendar=True)
    assert r"\event*[at=15:45]{Doctor}" in tex


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_an_option_left_out_prints_nothing(tmp_path):
    """A regression test for a bug the markup alone could not show.

    The option macros are compared against \\@empty to decide whether to print
    a time or a migration arrow. \\newcommand makes a macro \\long, and \\ifx
    compares that prefix too, so a \\long empty macro never tested equal and
    every bullet printed a bare arrow. It only appeared once compiled.
    """
    src = "day 2026-09-05:\n  . A plain task\n  - A plain note\n"
    (tmp_path / "p.tex").write_text(emit(parse(src), "latex"), encoding="utf-8")
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "p.tex"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]

    text = subprocess.run(
        ["pdftotext", str(tmp_path / "p.pdf"), "-"], capture_output=True, text=True
    ).stdout
    assert "A plain task" in text
    assert "→" not in text and "→" not in text
