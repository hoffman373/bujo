"""Command line front end: ``bujo compile|check|stats|pdf``."""

from __future__ import annotations

import argparse
import collections
import datetime
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from . import __version__
from .emit import EMITTERS, EXTENSIONS, emit
from .errors import BujoError
from .model import Kind, State
from .notebook import (
    FLIPS,
    HALF_LETTER,
    LETTER_SHEET,
    WEEK_STARTS,
    booklet,
    tumble,
    weekly,
)
from .parser import parse


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bujo",
        description="Compile bullet journal source into LaTeX, Markdown or JSON.",
    )
    ap.add_argument("--version", action="version", version=f"bujo {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    compile_ = sub.add_parser("compile", help="compile a journal")
    compile_.add_argument("source", type=pathlib.Path)
    compile_.add_argument(
        "-f", "--format", default="latex", choices=sorted(EMITTERS), help="output format"
    )
    compile_.add_argument(
        "-o", "--output", type=pathlib.Path, help="output file (default: stdout)"
    )
    compile_.add_argument(
        "--fragment",
        action="store_true",
        help="LaTeX only: emit the body without a preamble, for \\input into your own document",
    )
    _add_calendar_flags(compile_)
    _add_dot_flags(compile_)
    _add_layout_flags(compile_)
    _add_mono_flag(compile_)
    compile_.add_argument(
        "--front-matter",
        action="store_true",
        help="Markdown only: emit metadata as YAML front matter",
    )

    check = sub.add_parser("check", help="parse without producing output")
    check.add_argument("source", type=pathlib.Path)

    stats = sub.add_parser("stats", help="summarise the journal, for a migration review")
    stats.add_argument("source", type=pathlib.Path)

    pdf = sub.add_parser("pdf", help="compile to LaTeX and run pdflatex on it")
    pdf.add_argument("source", type=pathlib.Path)
    pdf.add_argument("-o", "--output", type=pathlib.Path, help="output .pdf (default: alongside)")
    pdf.add_argument("--engine", default="pdflatex", help="TeX engine to run")
    pdf.add_argument("--keep-tex", action="store_true", help="keep the intermediate .tex")
    pdf.add_argument(
        "--booklet", action="store_true",
        help="impose the pages two-up in signature order, ready to print "
             "double sided and fold down the middle",
    )
    pdf.add_argument(
        "--sheet", default=LETTER_SHEET, metavar="SPEC",
        help=f"geometry options for the printed sheet (default: {LETTER_SHEET})",
    )
    pdf.add_argument(
        "--flip", choices=FLIPS, default="short-edge",
        help="which edge the printer turns the sheet over on. If the backs "
             "come out upside down and their two pages swapped, use the other one",
    )
    _add_calendar_flags(pdf)
    _add_dot_flags(pdf)
    _add_layout_flags(pdf)
    _add_mono_flag(pdf)

    return ap


def _add_mono_flag(sub: argparse.ArgumentParser) -> None:
    group = sub.add_mutually_exclusive_group()
    group.add_argument(
        "--mono", dest="mono", action="store_true", default=None,
        help="print every colour as black, for a printer that has only the one",
    )
    group.add_argument(
        "--color", "--colour", dest="mono", action="store_false",
        help="keep the colours even if the file asks for mono",
    )


def _add_layout_flags(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--layout", choices=("journal", "weekly"), default="journal",
        help="'weekly' builds a foldable notebook: half-Letter pages, one "
             "collection per page, and a blank dotted page for every day of the week",
    )
    sub.add_argument(
        "--week", type=_date, metavar="YYYY-MM-DD",
        help="any date in the week to build (default: today)",
    )
    sub.add_argument(
        "--week-start", choices=sorted(WEEK_STARTS), default="monday",
        help="which day the week starts on (default: monday)",
    )
    sub.add_argument(
        "--blanks", choices=("all", "remaining"), default="all",
        help="a writing page for every day, or only for days not yet written up",
    )
    sub.add_argument(
        "--paper", default=HALF_LETTER, metavar="SPEC",
        help=f"geometry paper options for the notebook (default: {HALF_LETTER})",
    )


def _date(text: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {text!r}") from None


def _add_dot_flags(sub: argparse.ArgumentParser) -> None:
    group = sub.add_mutually_exclusive_group()
    group.add_argument(
        "--dots", dest="dots", action="store_true", default=None,
        help="LaTeX only: print a 5mm grid of light grey dots behind the page",
    )
    group.add_argument(
        "--no-dots", dest="dots", action="store_false",
        help="suppress the dot grid even if the file asks for one",
    )


def _add_calendar_flags(sub: argparse.ArgumentParser) -> None:
    group = sub.add_mutually_exclusive_group()
    group.add_argument(
        "--calendar", dest="calendar", action="store_true", default=None,
        help="draw the date column on monthly logs (LaTeX default)",
    )
    group.add_argument(
        "--no-calendar", dest="calendar", action="store_false",
        help="omit the date column on monthly logs",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Convenience: `bujo journal.bujo` means `bujo compile journal.bujo`.
    if argv and argv[0] not in ("-h", "--help", "--version") and not argv[0].startswith("-"):
        if argv[0] not in ("compile", "check", "stats", "pdf"):
            argv.insert(0, "compile")

    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except BujoError as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"bujo: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    doc = parse(args.source.read_text(encoding="utf-8"), str(args.source))
    if getattr(args, "layout", "journal") == "weekly":
        doc = weekly(
            doc,
            args.week,
            start=args.week_start,
            blanks=args.blanks,
            paper=args.paper,
        )

    match args.command:
        case "check":
            print(
                f"{args.source}: ok — {len(doc.collections)} collections, "
                f"{sum(1 for _ in doc.entries())} entries"
            )
            return 0
        case "stats":
            _stats(doc)
            return 0
        case "compile":
            if args.dots and args.fragment:
                print(
                    "bujo: warning: --dots needs the preamble, so it is ignored "
                    "with --fragment",
                    file=sys.stderr,
                )
            text = emit(
                doc,
                args.format,
                standalone=not args.fragment,
                calendar=args.calendar,
                front_matter=args.front_matter,
                **_layout_options(args),
            )
            if args.output:
                args.output.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            return 0
        case "pdf":
            return _pdf(doc, args)

    raise AssertionError(args.command)  # pragma: no cover


def _layout_options(args: argparse.Namespace) -> dict:
    """Backend options implied by --layout and the dot flags.

    ``--no-dots`` suppresses the grid everywhere, including the writing pages;
    ``--dots`` puts it on the printed pages too, which the weekly layout
    otherwise leaves clean.
    """
    weekly_layout = args.layout == "weekly"
    return {
        "dots": args.dots,
        "blank_dots": args.dots is not False,
        "page_breaks": weekly_layout,
        "signature": weekly_layout,
        "mono": args.mono,
    }


def _stats(doc) -> None:
    kinds: collections.Counter = collections.Counter()
    states: collections.Counter = collections.Counter()
    tags: collections.Counter = collections.Counter()
    for entry in doc.entries():
        kinds[entry.kind] += 1
        if entry.state:
            states[entry.state] += 1
        for span in entry.spans:
            if type(span).__name__ == "Tag":
                tags[span.name] += 1

    print(f"collections  {len(doc.collections)}")
    for kind in Kind:
        print(f"{kind.value + 's':<13}{kinds[kind]}")
    if states:
        print()
        for state in State:
            print(f"  {state.value:<11}{states[state]}")
        open_tasks = states[State.OPEN]
        done = states[State.DONE]
        closed = done + states[State.CANCELLED]
        if open_tasks + closed:
            print(f"\ncompletion   {done / (open_tasks + closed) * 100:.0f}%")
    if tags:
        print("\ntags")
        for name, count in tags.most_common():
            print(f"  #{name:<10}{count}")


def _pdf(doc, args: argparse.Namespace) -> int:
    engine = shutil.which(args.engine)
    if engine is None:
        print(f"bujo: {args.engine} not found on PATH", file=sys.stderr)
        return 1

    tex = emit(doc, "latex", standalone=True, calendar=args.calendar, **_layout_options(args))
    stem = args.source.stem
    output = args.output or args.source.with_suffix(".pdf")

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        (work / f"{stem}.tex").write_text(tex, encoding="utf-8")
        # Twice: the Index needs page numbers resolved from the .aux file.
        if _run_tex(engine, work, stem, passes=2) is None:
            return 1

        result = f"{stem}.pdf"
        if args.booklet:
            (work / "booklet.tex").write_text(
                booklet(result, args.sheet), encoding="utf-8"
            )
            log = _run_tex(engine, work, "booklet")
            if log is None:
                return 1
            result = "booklet.pdf"

            if args.flip == "long-edge":
                sheets = _page_count(log)
                if sheets is None:
                    print(
                        "bujo: could not read the sheet count out of the TeX log, "
                        "so the back sheets were left unrotated",
                        file=sys.stderr,
                    )
                    return 1
                (work / "tumble.tex").write_text(
                    tumble(result, sheets, args.sheet), encoding="utf-8"
                )
                if _run_tex(engine, work, "tumble") is None:
                    return 1
                result = "tumble.pdf"

        shutil.copy(work / result, output)
        if args.keep_tex:
            shutil.copy(work / f"{stem}.tex", output.with_suffix(".tex"))

    if args.booklet:
        note = f" (two-up, fold down the middle; {args.flip} duplex)"
    else:
        note = ""
    print(f"wrote {output}{note}")
    return 0


def _run_tex(engine: str, work: pathlib.Path, stem: str, passes: int = 1) -> str | None:
    """Run the engine, returning its log on success and None on failure."""
    proc = None
    for _ in range(passes):
        proc = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error", f"{stem}.tex"],
            cwd=work,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(_tex_error(proc.stdout))
            return None
    return proc.stdout if proc else ""


def _page_count(log: str) -> int | None:
    """Pull the page count out of TeX's "Output written on ... (N pages" line."""
    match = re.search(r"Output written on \S+ \((\d+) pages?", log)
    return int(match.group(1)) if match else None


def _tex_error(log: str) -> str:
    """Show the interesting tail of a TeX log rather than all of it."""
    lines = log.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("!")), max(0, len(lines) - 20))
    return "\n".join(lines[start : start + 20]) + "\n"
