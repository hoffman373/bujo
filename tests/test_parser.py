import datetime as dt

import pytest

from bujo import BujoError, parse
from bujo.model import (
    CustomCollection,
    DailyLog,
    FutureLog,
    Group,
    Index,
    Key,
    Kind,
    MonthlyLog,
    Ref,
    Signifier,
    State,
    Tag,
)


def first(src):
    return parse(src).collections[0]


def test_metadata_before_collections():
    doc = parse("title: Field Notes\nauthor: D\n\nday 2026-09-05:\n  . thing\n")
    assert doc.meta == {"title": "Field Notes", "author": "D"}


def test_metadata_after_a_collection_is_an_error():
    with pytest.raises(BujoError) as exc:
        parse("day 2026-09-05:\n  . a\ntitle: Late\n")
    assert "before the first collection" in str(exc.value)


@pytest.mark.parametrize(
    "marker,kind,state",
    [
        (".", Kind.TASK, State.OPEN),
        ("x", Kind.TASK, State.DONE),
        ("X", Kind.TASK, State.DONE),
        (">", Kind.TASK, State.MIGRATED),
        ("<", Kind.TASK, State.SCHEDULED),
        ("~", Kind.TASK, State.CANCELLED),
        ("o", Kind.EVENT, None),
        ("-", Kind.NOTE, None),
    ],
)
def test_every_marker(marker, kind, state):
    entry = first(f"day 2026-09-05:\n  {marker} text\n").items[0]
    assert (entry.kind, entry.state) == (kind, state)


def test_signifiers_stack_and_precede_the_marker():
    entry = first("day 2026-09-05:\n  *!. urgent idea\n").items[0]
    assert entry.signifiers == [Signifier.PRIORITY, Signifier.INSPIRATION]
    assert entry.text == "urgent idea"


def test_bare_signifier_is_a_note():
    entry = first("day 2026-09-05:\n  ! an idea\n").items[0]
    assert entry.kind is Kind.NOTE
    assert entry.signifiers == [Signifier.INSPIRATION]
    assert entry.text == "an idea"


def test_prose_starting_with_a_signifier_character_is_not_a_bullet():
    entry = first("day 2026-09-05:\n  - real note\n    !important, keep\n").items[0]
    assert entry.text == "real note !important, keep"


def test_indentation_nests():
    day = first("day 2026-09-05:\n  . parent\n    . child\n      . grandchild\n  . sibling\n")
    assert len(day.items) == 2
    assert day.items[0].children[0].children[0].text == "grandchild"


def test_dedent_returns_to_the_right_parent():
    day = first("day 2026-09-05:\n  . a\n    . a1\n      . a2\n    . a3\n")
    a = day.items[0]
    assert [c.text for c in a.children] == ["a1", "a3"]


def test_continuation_joins_the_previous_bullet():
    entry = first("day 2026-09-05:\n  - one\n    two #tag\n").items[0]
    assert entry.text == "one two #tag"
    assert any(isinstance(s, Tag) for s in entry.spans)


def test_continuation_without_a_bullet_is_an_error():
    with pytest.raises(BujoError) as exc:
        parse("day 2026-09-05:\n    dangling text\n")
    assert "expected a bullet" in str(exc.value)


def test_event_time_is_lifted_out_of_the_text():
    entry = first("day 2026-09-05:\n  o 09:30-10:00 Standup\n").items[0]
    assert entry.time == "09:30–10:00"
    assert entry.text == "Standup"


def test_migration_target():
    entry = first("day 2026-09-05:\n  > Manual -> 2026-10\n").items[0]
    assert (entry.target, entry.text) == ("2026-10", "Manual")


def test_target_on_a_plain_task_is_an_error():
    with pytest.raises(BujoError) as exc:
        parse("day 2026-09-05:\n  . Manual -> 2026-10\n")
    assert "migrated" in str(exc.value)


def test_empty_bullet_is_an_error():
    with pytest.raises(BujoError) as exc:
        parse("day 2026-09-05:\n  .\n")
    assert "no text" in str(exc.value)


def test_inline_spans():
    entry = first("day 2026-09-05:\n  . Call @mum re [[Reading List]] #family\n").items[0]
    kinds = [type(s).__name__ for s in entry.spans]
    assert "Context" in kinds and "Ref" in kinds and "Tag" in kinds
    assert entry.text == "Call @mum re [[Reading List]] #family"


def test_groups_are_collection_level_sections():
    coll = first('collection "Books":\n  Fiction:\n    . A\n    . B\n  Technical:\n    . C\n')
    assert isinstance(coll, CustomCollection)
    assert [type(i).__name__ for i in coll.items] == ["Group", "Group"]
    assert [g.title for g in coll.items] == ["Fiction", "Technical"]
    assert len(coll.items[0].entries) == 2


def test_collection_headers():
    doc = parse(
        'index:\nkey:\nfuture 2026-10 .. 2027-01:\nmonth 2026-09:\n'
        'day 2026-09-05 "rain":\n  . x\ncollection "Books":\n  . y\n'
    )
    assert [type(c).__name__ for c in doc.collections] == [
        "Index", "Key", "FutureLog", "MonthlyLog", "DailyLog", "CustomCollection",
    ]
    day = doc.collections[4]
    assert isinstance(day, DailyLog) and day.date == dt.date(2026, 9, 5)
    assert day.heading == "rain"
    assert isinstance(doc.collections[3], MonthlyLog)
    assert isinstance(doc.collections[0], Index) and isinstance(doc.collections[1], Key)


def test_future_log_range_expands():
    log = first("future 2026-11 .. 2027-02:\n")
    assert isinstance(log, FutureLog)
    assert log.months() == [(2026, 11), (2026, 12), (2027, 1), (2027, 2)]


@pytest.mark.parametrize(
    "src,message",
    [
        ("day 2026-9-5:\n", "YYYY-MM-DD"),
        ("day 2026-02-30:\n  . x\n", "invalid date"),
        ("month 2026-13:\n", "YYYY-MM"),
        ("future 2026-10:\n", "month range"),
        ("future 2027-03 .. 2026-10:\n", "backwards"),
        ("collection:\n", "needs a name"),
        ("nonsense 1:\n", "expected a collection header"),
        (". orphan\n", "expected a collection header"),
    ],
)
def test_header_errors(src, message):
    with pytest.raises(BujoError) as exc:
        parse(src)
    assert message in str(exc.value)


def test_all_errors_are_reported_at_once():
    with pytest.raises(BujoError) as exc:
        parse("day bad:\n  . ok\nmonth also-bad:\n")
    assert len(exc.value.diagnostics) == 2


def test_diagnostics_carry_position_and_source():
    with pytest.raises(BujoError) as exc:
        parse("day 2026-09-05:\n  . a\n  . b -> nowhere\n")
    diag = exc.value.diagnostics[0]
    assert diag.line == 3 and "-> nowhere" in diag.source_line


def test_comments_and_blank_lines_are_ignored():
    day = first("day 2026-09-05:\n  // a comment\n\n  . real\n")
    assert len(day.items) == 1


def test_tabs_indent_like_spaces():
    day = first("day 2026-09-05:\n\t. parent\n\t\t. child\n")
    assert day.items[0].children[0].text == "child"


@pytest.mark.parametrize(
    "text,time,rest",
    [
        ("09:30 Standup", "09:30", "Standup"),
        ("9:30 Standup", "9:30", "Standup"),
        ("3:45pm Doctor", "3:45pm", "Doctor"),
        ("0930 Standup", "09:30", "Standup"),          # bare 24-hour
        ("1545 Doctor", "15:45", "Doctor"),
        ("2359 Late one", "23:59", "Late one"),
        ("0930-1015 Standup", "09:30–10:15", "Standup"),
        ("09:30-1015 Standup", "09:30–10:15", "Standup"),
    ],
)
def test_event_times(text, time, rest):
    entry = first(f"day 2026-09-05:\n  o {text}\n").items[0]
    assert (entry.time, entry.text) == (time, rest)


@pytest.mark.parametrize(
    "text",
    [
        "2400 Not a time",     # hour out of range
        "2360 Nor this",       # minute out of range
        "155 Too short",
        "15455 Too long",
        "2026-09-09 Anniversary",  # a date is not a time
        "1545",                # a time with nothing to say
    ],
)
def test_things_that_are_not_event_times(text):
    entry = first(f"day 2026-09-05:\n  o {text}\n").items[0]
    assert entry.time is None
    assert entry.text == text


def test_a_leading_bare_year_reads_as_a_time():
    """The documented cost of the bare 24-hour form; a year belongs elsewhere
    in the line."""
    entry = first("day 2026-09-05:\n  o 2026 retrospective\n").items[0]
    assert entry.time == "20:26"


# -- date pins --------------------------------------------------------------

def test_a_pin_attaches_a_bullet_to_a_day_of_the_month():
    month = first("month 2026-09:\n  o 09: 1545 Doctor\n  . 12: Pay the water bill\n")
    assert [(e.day, e.time, e.text) for e in month.items] == [
        (9, "15:45", "Doctor"),
        (12, None, "Pay the water bill"),
    ]


def test_a_time_is_not_mistaken_for_a_pin():
    """`09:30` has no space after the colon, which is what tells them apart."""
    entry = first("month 2026-09:\n  o 09:30 Standup\n").items[0]
    assert (entry.day, entry.time, entry.text) == (None, "09:30", "Standup")


def test_unpinned_bullets_are_left_alone():
    entry = first("month 2026-09:\n  . Replace the pump seal\n").items[0]
    assert entry.day is None


def test_a_pin_outside_a_monthly_log_stays_as_text():
    for src in ("day 2026-09-05:\n  . 12: not a pin\n",
                'collection "X":\n  . 12: not a pin\n'):
        entry = first(src).items[0]
        assert entry.day is None
        assert entry.text == "12: not a pin"


@pytest.mark.parametrize("day", ["0", "31", "99"])
def test_a_pin_outside_the_month_is_an_error(day):
    with pytest.raises(BujoError) as exc:
        parse(f"month 2026-09:\n  . {day}: nope\n")
    assert "has no day" in str(exc.value)
    assert "between 1 and 30" in str(exc.value)


def test_the_bullet_survives_a_bad_pin():
    """The pin is dropped, not the entry -- one mistake should not eat a task."""
    try:
        parse("month 2026-02:\n  . 30: Leap too far\n")
    except BujoError as exc:
        assert len(exc.diagnostics) == 1
