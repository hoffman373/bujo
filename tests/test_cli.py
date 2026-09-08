import json
import re
import shutil
import subprocess

import pytest

from bujo.cli import main

SRC = 'title: T\n\nindex:\nday 2026-09-05:\n  . a #tag\n  x b\n  o 09:00 c\n'


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "j.bujo"
    path.write_text(SRC, encoding="utf-8")
    return path


def test_check_reports_ok(journal, capsys):
    assert main(["check", str(journal)]) == 0
    assert "ok — 2 collections, 3 entries" in capsys.readouterr().out


def test_check_reports_errors_and_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.bujo"
    bad.write_text("day nope:\n", encoding="utf-8")
    assert main(["check", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err


def test_missing_file_is_reported(tmp_path, capsys):
    assert main(["check", str(tmp_path / "absent.bujo")]) == 1
    assert "bujo:" in capsys.readouterr().err


def test_compile_writes_to_stdout(journal, capsys):
    assert main(["compile", str(journal), "-f", "markdown"]) == 0
    assert "- [x] b" in capsys.readouterr().out


def test_compile_writes_to_a_file(journal, tmp_path):
    out = tmp_path / "out.tex"
    assert main(["compile", str(journal), "-o", str(out)]) == 0
    assert out.read_text().startswith("\\documentclass")


def test_bare_path_defaults_to_compile(journal, capsys):
    assert main([str(journal)]) == 0
    assert capsys.readouterr().out.startswith("\\documentclass")


def test_format_json(journal, capsys):
    assert main([str(journal), "-f", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["meta"] == {"title": "T"}


def test_stats(journal, capsys):
    assert main(["stats", str(journal)]) == 0
    out = capsys.readouterr().out
    assert "tasks        2" in out and "#tag" in out and "completion   50%" in out


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_pdf_builds_a_document(journal, tmp_path, capsys):
    out = tmp_path / "j.pdf"
    assert main(["pdf", str(journal), "-o", str(out), "--keep-tex"]) == 0
    assert out.exists() and out.stat().st_size > 1000
    assert (tmp_path / "j.tex").exists()


def test_pdf_reports_a_missing_engine(journal, capsys):
    assert main(["pdf", str(journal), "--engine", "definitely-not-a-tex-engine"]) == 1
    assert "not found on PATH" in capsys.readouterr().err


def test_dots_flag(journal, capsys):
    assert main([str(journal), "--dots"]) == 0
    assert "pattern=bujodots" in capsys.readouterr().out


def test_dots_with_fragment_warns(journal, capsys):
    assert main([str(journal), "--dots", "--fragment"]) == 0
    captured = capsys.readouterr()
    assert "ignored with --fragment" in captured.err
    assert "bujodots" not in captured.out


def test_weekly_layout_reorders_and_adds_writing_pages(journal, capsys):
    assert main([str(journal), "--layout", "weekly", "--week", "2026-09-09"]) == 0
    out = capsys.readouterr().out
    assert "paperwidth=5.5in,paperheight=8.5in" in out
    assert out.count(r"\bujoDotThisPage") == 7 + 2  # 7 pages, the macro, the padding
    assert out.index(r"\section*{Index}") < out.index(r"\section*{2026-09-07 · Monday}")


def test_weekly_no_dots_leaves_the_writing_pages_plain(journal, capsys):
    assert main([str(journal), "--layout", "weekly", "--no-dots"]) == 0
    assert "bujodots" not in capsys.readouterr().out


def test_bad_week_date_is_rejected(journal, capsys):
    with pytest.raises(SystemExit):
        main([str(journal), "--layout", "weekly", "--week", "next tuesday"])
    assert "YYYY-MM-DD" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_booklet_prints_two_journal_pages_per_sheet(journal, tmp_path):
    plain, folded = tmp_path / "p.pdf", tmp_path / "f.pdf"
    assert main(["pdf", str(journal), "--layout", "weekly", "-o", str(plain)]) == 0
    assert main(
        ["pdf", str(journal), "--layout", "weekly", "--booklet", "-o", str(folded)]
    ) == 0

    assert _pages(plain) == _pages(folded) * 2
    assert "792 x 612 pts" in _info(folded)   # Letter, landscape
    assert "396 x 612 pts" in _info(plain)    # half Letter, portrait


@pytest.mark.skipif(
    shutil.which("pdflatex") is None or shutil.which("pdftoppm") is None,
    reason="needs pdflatex and poppler",
)
def test_long_edge_flip_rotates_the_back_sheets(journal, tmp_path):
    short, long_ = tmp_path / "s.pdf", tmp_path / "l.pdf"
    base = ["pdf", str(journal), "--layout", "weekly", "--booklet", "--week", "2026-09-09"]
    assert main([*base, "-o", str(short)]) == 0
    assert main([*base, "--flip", "long-edge", "-o", str(long_)]) == 0

    # Same sheets either way -- what changes is how the backs are laid down.
    # That the fronts are left alone is covered by test_tumble_rotates_only_
    # the_back_of_each_sheet; here we check the change reaches the PDF.
    assert _pages(short) == _pages(long_)
    assert "792 x 612 pts" in _info(long_).replace("791.998", "792").replace("611.998", "612")
    assert _render(short, 2) != _render(long_, 2)


def _render(pdf, page):
    """The page as a bitmap. Text extraction normalises rotation away, so the
    only honest way to see a half-turn is to look at the pixels."""
    out = pdf.parent / f"{pdf.stem}-{page}"
    subprocess.run(
        ["pdftoppm", "-r", "40", "-png", "-f", str(page), "-l", str(page),
         str(pdf), str(out)],
        check=True, capture_output=True,
    )
    return next(pdf.parent.glob(f"{out.name}*.png")).read_bytes()


def _info(pdf):
    return subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout


def _pages(pdf):
    return int(next(l for l in _info(pdf).splitlines() if l.startswith("Pages")).split()[1])


@pytest.mark.skipif(
    shutil.which("pdflatex") is None or shutil.which("pdftotext") is None,
    reason="needs pdflatex and poppler",
)
def test_folded_pages_put_their_wide_margin_on_the_outside(tmp_path):
    """Odd pages are rectos and even pages versos once folded, so the narrow
    gutter has to swap sides with the parity."""
    source = tmp_path / "m.bujo"
    source.write_text(
        "margin: 0.625in\ninner: 0.375in\n\nindex:\nday 2026-09-09:\n  . a\n",
        encoding="utf-8",
    )
    out = tmp_path / "n.pdf"
    assert main(["pdf", str(source), "--layout", "weekly", "-o", str(out)]) == 0

    recto, verso = _left_edge(out, 1), _left_edge(out, 2)
    assert recto == pytest.approx(0.375 * 72, abs=1)  # gutter, meets the fold
    assert verso == pytest.approx(0.625 * 72, abs=1)  # outside, clears the printer


def _left_edge(pdf, page):
    """Leftmost text position on a page, in points."""
    bbox = subprocess.run(
        ["pdftotext", "-bbox", "-f", str(page), "-l", str(page), str(pdf), "-"],
        capture_output=True, text=True,
    ).stdout
    return min(float(x) for x in re.findall(r'xMin="([0-9.]+)"', bbox))
