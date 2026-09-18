from __future__ import annotations

import copy
import pickle
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fmsave
from fmsave._errors import FmsaveError, ReaderCheckError, SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import InjuryStats
from fmsave.checks import INJURY_HISTORY_READER, GateResult, evaluate_injury_history
from fmsave.export import column_names
from fmsave.models.injuries import (
    InjuryCause,
    InjuryRecord,
    InjuryRecordKind,
    InjurySeverity,
    InjuryType,
)
from fmsave.models.players import Player
from fmsave.readers._common import (
    GAME_DB_SECTION,
    INJURY_MANAGER_SECTION,
    MISSING_REFERENCE,
)
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.injuries import (
    build_injury_records,
    find_injury_manager_layout,
    walk_injury_manager,
)
from fmsave.readers.player_scan import PlayerRecords
from fmsave.table import Table
from tests.fixtures.career import (
    ATHLETIC_UID,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_UID,
    PLAYER_A_UID,
    PLAYER_C_UID,
    SOUTHPORT_TEAM,
    SOUTHPORT_UID,
    career_fragment,
    career_injury_log_rows,
    career_injury_manager,
    career_injury_window_rows,
    career_typed_injury_rows,
)
from tests.fixtures.container import packed_date
from tests.fixtures.injuries import (
    INJURY_MANAGER_TAIL,
    injury_log_row_bytes,
    injury_manager_body,
    injury_typed_row_bytes,
)

GAME_DB_SCHEMA = 4000
INJURY_MANAGER_SCHEMA = 8
KIBIBYTE = 1024
FULL_SIZE_SECTION_BYTES = 2 * KIBIBYTE * KIBIBYTE
SMALL_SECTION_BYTES = 200 * KIBIBYTE
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_injury_manager_layout(INJURY_MANAGER_SCHEMA, "")
FILE_NAME = "career.bin"
CLOCK = date(2031, 3, 1)
# The career fragment's own rows, in the order `injury_history()` returns them.
FIRST_LOG_DATE = date(2030, 11, 2)
SECOND_LOG_DATE = date(2031, 2, 20)
THIRD_LOG_DATE = date(2031, 2, 25)
FIRST_TYPED_DATE = date(2031, 3, 5)
SECOND_TYPED_DATE = date(2031, 2, 24)
NAMED_TYPE_ID = 7
NAMED_TYPE = "Example Knock"
UNNAMED_TYPE_ID = 39
TIME_SLOT = 33
# A team Northbridge controls that another club fields, and the slot it takes after
# Northbridge's own two teams.
AFFILIATE_TEAM_ID = 70007
AFFILIATE_TEAM_SLOT = 2
# Every gate this reader carries, in the order it evaluates them.
GATE_NAMES = (
    "injury_log_minimum",
    "injury_log_lead_byte",
    "injury_log_dates",
    "injury_log_ascending",
    "injury_log_teams_resolved",
    "injury_log_recent_team_matches",
    "injury_typed_lead_byte",
    "injury_typed_dates_near_clock",
    "injury_typed_types_resolved",
)
# What the largest save measured counts, which is what the synthetic check cases start from.
MEASURED_LOG_ROWS = 128_866
MEASURED_LOG_STEPS = 128_865
MEASURED_TYPED_ROWS = 1_542
MEASURED_LIST_ENTRIES = (71, 1, 0)


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_stats(**overrides: int) -> InjuryStats:
    """Counts as the largest save measured reports them, before any override."""
    fields: dict[str, int] = {
        "section_bytes": FULL_SIZE_SECTION_BYTES,
        "window_a_rows": 3_186,
        "window_b_rows": 2_972,
        "log_rows": MEASURED_LOG_ROWS,
        "log_lead_ok": MEASURED_LOG_ROWS,
        "log_dates_ok": MEASURED_LOG_ROWS,
        "log_steps": MEASURED_LOG_STEPS,
        "log_ascending_steps": MEASURED_LOG_STEPS,
        "log_players_resolved": 124_234,
        "log_teams_resolved": 128_645,
        "recent_log_rows": 5_995,
        "recent_log_team_matches": 5_916,
        "typed_rows": MEASURED_TYPED_ROWS,
        "typed_lead_ok": MEASURED_TYPED_ROWS,
        "typed_dated": 1_524,
        "typed_dated_near_clock": 1_524,
        "typed_dated_over_a_week_old": 0,
        "typed_players_resolved": 1_540,
        "typed_types_resolved": 1_412,
        "type_table_entries": 93,
    }
    return InjuryStats(list_entries=MEASURED_LIST_ENTRIES, **(fields | overrides))


class CareerParts(NamedTuple):
    """The section and everything `build_injury_records` joins a row through."""

    section: bytes
    player_records: PlayerRecords
    players: Table[Player]
    club_index: ClubIndex
    injury_types: Table[InjuryType]


def career_parts(save: fmsave.Save) -> CareerParts:
    context = save._context
    players = save.players()
    save.clubs()
    injury_types = save.injury_types()
    with context.section(INJURY_MANAGER_SECTION) as section:
        section_bytes = bytes(section)
    return CareerParts(
        section_bytes, context.player_records(), players, context.club_index(), injury_types
    )


def career_rows(save: fmsave.Save) -> tuple[tuple[InjuryRecord, ...], InjuryStats]:
    """`build_injury_records` run on the career fragment, outside `injury_history()`."""
    parts = career_parts(save)
    walk = walk_injury_manager(parts.section, LAYOUT, FILE_NAME)
    return build_injury_records(
        parts.section,
        walk,
        parts.player_records,
        parts.players,
        parts.club_index,
        parts.injury_types,
        CLOCK,
        LAYOUT,
    )


def test_every_log_row_comes_first_then_every_typed_row(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        history = save.injury_history()

    assert len(history) == 6
    assert [row.kind for row in history] == [InjuryRecordKind.HISTORY] * 3 + [
        InjuryRecordKind.TYPED
    ] * 3
    assert [row.date for row in history] == [
        FIRST_LOG_DATE,
        SECOND_LOG_DATE,
        THIRD_LOG_DATE,
        FIRST_TYPED_DATE,
        SECOND_TYPED_DATE,
        None,
    ]


def test_a_log_row_carries_its_player_its_date_and_the_club_of_the_team_it_names(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        history = save.injury_history()
        player_name = save.players().by_uid(PLAYER_A_UID).name
    row = history[0]

    assert row.player_uid == PLAYER_A_UID
    assert row.player_name == player_name
    assert row.date == FIRST_LOG_DATE
    assert row.team_id == SOUTHPORT_TEAM
    assert row.club_uid == SOUTHPORT_UID
    assert row.club_name == "Southport Example"
    assert row.team_slot == 0
    assert row.type_id is None
    assert row.type_name is None
    assert row.cause is not None
    assert row.cause.label is InjuryCause.IN_MATCH
    assert row.cause.raw == 1
    assert row.severity is not None
    assert row.severity.label is InjurySeverity.MODERATE
    assert row.severity.raw == 2
    assert row.unknown == {"r0": 1, "hi7_date": TIME_SLOT}


def test_a_log_row_with_no_time_slot_keeps_its_date_and_its_codes(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.injury_history()[1]

    assert row.player_uid == PLAYER_C_UID
    assert row.date == SECOND_LOG_DATE
    assert row.team_id == NORTHBRIDGE_TEAM_A
    assert row.club_uid == NORTHBRIDGE_UID
    assert row.severity is not None
    assert row.severity.raw == 3
    assert row.unknown["hi7_date"] == 0


def test_a_log_row_whose_person_is_no_longer_a_player_keeps_its_club(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.injury_history()[2]

    assert row.player_uid is None
    assert row.player_name is None
    assert row.club_uid == ATHLETIC_UID
    assert row.club_name == "Example Athletic"


def test_a_typed_row_carries_its_injury_type_and_no_team_at_all(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.injury_history()[3]

    assert row.kind is InjuryRecordKind.TYPED
    assert row.player_uid == PLAYER_A_UID
    assert row.date == FIRST_TYPED_DATE
    assert row.type_id == NAMED_TYPE_ID
    assert row.type_name == NAMED_TYPE
    assert row.team_id is None
    assert row.club_uid is None
    assert row.club_name is None
    assert row.team_slot is None
    assert row.cause is None
    assert row.severity is None
    assert row.unknown == {"r0": 1, "r11": 2, "r12": 14, "hi7_date": TIME_SLOT}


def test_a_typed_code_the_name_table_misses_and_a_typed_row_with_no_date(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        history = save.injury_history()

    assert history[4].date == SECOND_TYPED_DATE
    assert history[4].type_id == UNNAMED_TYPE_ID
    assert history[4].type_name is None
    assert history[5].date is None
    assert history[5].player_uid is None
    assert history[5].type_name == NAMED_TYPE


def test_the_walk_and_the_joins_count_every_row(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        parts = career_parts(save)
        _rows, stats = career_rows(save)

    assert stats == InjuryStats(
        section_bytes=len(parts.section),
        window_a_rows=1,
        window_b_rows=1,
        list_entries=(1, 0, 1),
        log_rows=3,
        log_lead_ok=3,
        log_dates_ok=3,
        log_steps=2,
        log_ascending_steps=2,
        log_players_resolved=2,
        log_teams_resolved=3,
        recent_log_rows=1,
        recent_log_team_matches=1,
        typed_rows=3,
        typed_lead_ok=3,
        typed_dated=2,
        typed_dated_near_clock=2,
        typed_dated_over_a_week_old=0,
        typed_players_resolved=2,
        typed_types_resolved=2,
        type_table_entries=5,
    )


def test_a_log_row_at_a_controlled_team_names_the_club_that_fields_it(career_path: Path) -> None:
    affiliate_log_row = injury_log_row_bytes(
        date=packed_date(51, 2031),
        selector=1,
        team_id=AFFILIATE_TEAM_ID,
        cause=0,
        severity=1,
    )
    section = injury_manager_body(
        window_a=(),
        window_b=(),
        typed=(),
        log=(affiliate_log_row,),
        lists=((), (), ()),
    )
    with fmsave.open(career_path) as save:
        parts = career_parts(save)
        controlled = replace(
            parts.club_index,
            affiliate_team_to_club={AFFILIATE_TEAM_ID: (NORTHBRIDGE_UID, AFFILIATE_TEAM_SLOT)},
        )
        walk = walk_injury_manager(section, LAYOUT, FILE_NAME)
        rows, _stats = build_injury_records(
            section,
            walk,
            parts.player_records,
            parts.players,
            controlled,
            parts.injury_types,
            CLOCK,
            LAYOUT,
        )

    assert rows[0].team_id == AFFILIATE_TEAM_ID
    assert rows[0].club_uid == NORTHBRIDGE_UID
    assert rows[0].team_slot == AFFILIATE_TEAM_SLOT


@pytest.mark.parametrize("stored_team_id", [0, MISSING_REFERENCE])
def test_a_log_row_naming_no_team_leaves_its_team_and_club_fields_empty(
    career_path: Path, stored_team_id: int
) -> None:
    section = injury_manager_body(
        window_a=(),
        window_b=(),
        typed=(),
        log=(
            injury_log_row_bytes(
                date=packed_date(51, 2031),
                selector=1,
                team_id=stored_team_id,
                cause=0,
                severity=0,
            ),
        ),
        lists=((), (), ()),
    )
    with fmsave.open(career_path) as save:
        parts = career_parts(save)
        walk = walk_injury_manager(section, LAYOUT, FILE_NAME)
        rows, stats = build_injury_records(
            section,
            walk,
            parts.player_records,
            parts.players,
            parts.club_index,
            parts.injury_types,
            CLOCK,
            LAYOUT,
        )

    assert rows[0].team_id is None
    assert rows[0].club_uid is None
    assert rows[0].club_name is None
    assert rows[0].team_slot is None
    assert stats.log_teams_resolved == 0


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            injury_manager_body(
                window_a=career_injury_window_rows(),
                window_b=career_injury_window_rows(),
                typed=career_typed_injury_rows(),
                log=career_injury_log_rows(),
                lists=((12,), (), ()),
                trailing_bytes=b"\x00",
            ),
            id="one byte after the tail",
        ),
        pytest.param(
            injury_manager_body(
                window_a=career_injury_window_rows(),
                window_b=career_injury_window_rows(),
                typed=career_typed_injury_rows(),
                log=career_injury_log_rows(),
                lists=((12,), (), ()),
                tail=bytes.fromhex("010000000000fffe"),
            ),
            id="a tail one byte different",
        ),
        pytest.param(
            injury_manager_body(
                window_a=career_injury_window_rows(),
                window_b=career_injury_window_rows(),
                typed=career_typed_injury_rows(),
                log=career_injury_log_rows(),
                lists=((12,), (), ()),
                log_count=len(career_injury_log_rows()) + 1,
            ),
            id="a log count one too many",
        ),
        pytest.param(
            injury_manager_body(
                window_a=career_injury_window_rows(),
                window_b=career_injury_window_rows(),
                typed=tuple(row + b"\x00" for row in career_typed_injury_rows()),
                log=career_injury_log_rows(),
                lists=((12,), (), ()),
            ),
            id="typed rows of fourteen bytes",
        ),
        pytest.param(
            injury_manager_body(
                window_a=career_injury_window_rows(),
                window_b=career_injury_window_rows(),
                typed=career_typed_injury_rows(),
                log=career_injury_log_rows(),
                lists=((12,), (), ((12, 1),)),
            )[:-10],
            id="a section cut inside the last list",
        ),
    ],
)
def test_a_body_the_walk_cannot_consume_exactly_names_its_section(body: bytes) -> None:
    with pytest.raises(ReaderCheckError, match="'injury_manager'"):
        walk_injury_manager(body, LAYOUT, FILE_NAME)


def typed_rows_with_one_extra_date(packed: bytes) -> bytes:
    """The career fragment's section with one more typed row, dated as given."""
    return injury_manager_body(
        window_a=career_injury_window_rows(),
        window_b=career_injury_window_rows(),
        typed=(
            *career_typed_injury_rows(),
            injury_typed_row_bytes(date=packed, selector=1, type_id=NAMED_TYPE_ID, r11=1, r12=1),
        ),
        log=career_injury_log_rows(),
        lists=((12,), (), ()),
    )


def test_a_typed_row_more_than_a_week_old_is_returned_and_counted_near_the_clock(
    tmp_path: Path,
) -> None:
    # Ten days before the in-game date. Whether the game still holds a row that old is career
    # state: the oldest was seven days back on five save states measured and eight on two, so
    # this row is sound, counted as near the clock, and reported as an anomaly only.
    ten_days_old = typed_rows_with_one_extra_date(packed_date(50, 2031))
    save_path = career_fragment(injury_manager_section=ten_days_old).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        history = save.injury_history()
        _rows, stats = career_rows(save)
        reader_check = save._reader_check(INJURY_HISTORY_READER)

    assert len(history) == 7
    assert stats.typed_rows == 4
    assert stats.typed_dated == 3
    assert stats.typed_dated_near_clock == 3
    assert stats.typed_dated_over_a_week_old == 1
    assert reader_check is not None
    assert reader_check.anomalies["typed_rows_over_a_week_old"] == 1
    assert reader_check.anomalies["typed_rows_far_from_the_clock"] == 0


def test_a_typed_row_dated_years_from_the_clock_is_returned_and_counted_apart(
    tmp_path: Path,
) -> None:
    # Two years before the in-game date, which is where a date read from neighbouring bytes
    # lands and further than the band the date gate judges.
    years_old = typed_rows_with_one_extra_date(packed_date(50, 2029))
    save_path = career_fragment(injury_manager_section=years_old).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        history = save.injury_history()
        _rows, stats = career_rows(save)

    assert len(history) == 7
    assert stats.typed_dated == 3
    assert stats.typed_dated_near_clock == stats.typed_dated - 1
    assert stats.typed_dated_over_a_week_old == 1


def test_a_save_with_no_per_match_file_names_no_type_and_applies_no_type_gate(
    tmp_path: Path,
) -> None:
    save_path = career_fragment(attachments=()).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        history = save.injury_history()
        _rows, stats = career_rows(save)
    unnamed = evaluate_injury_history(healthy_stats(type_table_entries=0), BOUNDS)

    assert len(history) == 6
    assert {row.type_name for row in history} == {None}
    assert stats.type_table_entries == 0
    assert [
        result.applied for result in unnamed if result.name == "injury_typed_types_resolved"
    ] == [False]


def test_the_columns_the_export_flattens() -> None:
    assert column_names(InjuryRecord) == (
        "kind",
        "player_uid",
        "player_name",
        "date",
        "team_id",
        "club_uid",
        "club_name",
        "team_slot",
        "type_id",
        "type_name",
        "cause",
        "cause_code",
        "severity",
        "severity_code",
        "unknown_r0",
        "unknown_r11",
        "unknown_r12",
        "unknown_hi7_date",
    )


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.injury_history()[0]

    # A round trip of fmsave's own record, not data from anywhere else.
    assert pickle.loads(pickle.dumps(row)) == row
    assert copy.deepcopy(row) == row


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first_table = save.injury_history()
        assert save.injury_history() is first_table

    with pytest.raises(SaveClosedError):
        save.injury_history()


def test_the_typed_rows_are_never_described_as_ended() -> None:
    documentation = fmsave.Save.injury_history.__doc__
    assert documentation is not None
    assert "ended" not in documentation.lower()


def test_the_anomalies_count_the_parts_no_row_carries(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.injury_history()
        reader_check = save._reader_check(INJURY_HISTORY_READER)

    assert reader_check is not None
    assert reader_check.record_count == 6
    assert reader_check.anomalies == {
        "window_a_rows": 1,
        "window_b_rows": 1,
        "list_0_entries": 1,
        "list_1_entries": 0,
        "list_2_entries": 1,
        "log_rows_without_a_player": 1,
        "typed_rows_without_a_player": 1,
        "unresolved_log_teams": 0,
        "untyped_rows": 1,
        "undated_typed_rows": 1,
        "typed_rows_far_from_the_clock": 0,
        "typed_rows_over_a_week_old": 0,
    }


def test_the_gates_every_save_measured_passes() -> None:
    assert failed_gate_names(evaluate_injury_history(healthy_stats(), BOUNDS)) == []
    assert [result.name for result in evaluate_injury_history(healthy_stats(), BOUNDS)] == list(
        GATE_NAMES
    )


@pytest.mark.parametrize(
    ("gate_name", "overrides"),
    [
        pytest.param(
            "injury_log_minimum",
            {
                "log_rows": 9_999,
                "log_lead_ok": 9_999,
                "log_dates_ok": 9_999,
                "log_steps": 9_998,
                "log_ascending_steps": 9_998,
                "log_players_resolved": 9_600,
                "log_teams_resolved": 9_990,
            },
            id="fewer log rows than a full save holds",
        ),
        pytest.param("injury_log_lead_byte", {"log_lead_ok": 609}, id="the lead byte read late"),
        pytest.param("injury_log_dates", {"log_dates_ok": 464}, id="the date read late"),
        pytest.param(
            "injury_log_ascending",
            {"log_ascending_steps": 126_287},
            id="dates that go backwards",
        ),
        pytest.param(
            "injury_log_teams_resolved", {"log_teams_resolved": 25_278}, id="the team read late"
        ),
        pytest.param(
            "injury_log_recent_team_matches",
            {"recent_log_team_matches": 2},
            id="a random player in place of the stored one",
        ),
        pytest.param(
            "injury_typed_lead_byte", {"typed_lead_ok": 18}, id="the typed lead byte read late"
        ),
        pytest.param(
            "injury_typed_dates_near_clock",
            {"typed_dated": 9, "typed_dated_near_clock": 0},
            id="the typed date read late",
        ),
        pytest.param(
            "injury_typed_types_resolved",
            {"typed_types_resolved": 0},
            id="the injury type read late",
        ),
    ],
)
def test_each_gate_fails_on_the_value_its_misalignment_measures(
    gate_name: str, overrides: dict[str, int]
) -> None:
    results = evaluate_injury_history(healthy_stats(**overrides), BOUNDS)

    assert failed_gate_names(results) == [gate_name]


def test_log_rows_that_carry_no_date_at_all_fail_the_ascending_gate() -> None:
    results = evaluate_injury_history(
        healthy_stats(log_steps=0, log_ascending_steps=0, log_dates_ok=MEASURED_LOG_ROWS), BOUNDS
    )

    assert "injury_log_ascending" in failed_gate_names(results)


def test_no_gate_applies_on_a_section_too_small_for_a_full_save() -> None:
    results = evaluate_injury_history(
        healthy_stats(section_bytes=SMALL_SECTION_BYTES, log_lead_ok=609, typed_types_resolved=0),
        BOUNDS,
    )

    assert [result.applied for result in results] == [False] * len(GATE_NAMES)


def test_the_share_of_people_who_are_still_players_is_counted_and_never_gated() -> None:
    results = evaluate_injury_history(healthy_stats(log_players_resolved=12_886), BOUNDS)

    assert failed_gate_names(results) == []


def test_the_date_gate_counts_over_every_typed_row_and_not_over_the_dated_ones() -> None:
    # Read one byte late, 9 of the 1,542 typed rows still decode a date, and a share taken
    # over those 9 dated rows alone cannot fail whatever they decode to. The wider denominator
    # is what makes 9 rows a failure.
    misaligned = healthy_stats(typed_dated=9, typed_dated_near_clock=9)
    over_the_dated_rows = misaligned.typed_dated_near_clock / misaligned.typed_dated

    assert over_the_dated_rows == 1.0
    assert failed_gate_names(evaluate_injury_history(misaligned, BOUNDS)) == [
        "injury_typed_dates_near_clock"
    ]


def test_a_date_that_decodes_far_from_the_clock_fails_the_date_gate() -> None:
    # Every typed row carries a date, and every one of them decodes to a year the game has
    # long passed: a share on how many rows are dated at all would score 1.0 on this, and that
    # is where every typed date that still decodes one byte late lands.
    results = evaluate_injury_history(healthy_stats(typed_dated_near_clock=0), BOUNDS)

    assert failed_gate_names(results) == ["injury_typed_dates_near_clock"]


def test_the_date_gate_passes_the_oldest_rows_any_save_state_has_held() -> None:
    # The oldest dated typed row was seven days behind the clock on five of the save states
    # measured and eight days behind on two, a full day's rows at that age rather than a
    # remnant: 225 of 2,457 on the newest, which is what a floor drawn round a one-week window
    # failed. The band is wide enough that career state cannot fail this gate on its own.
    a_tenth_of_the_rows_over_a_week_old = healthy_stats(
        typed_dated_over_a_week_old=MEASURED_TYPED_ROWS // 10
    )

    assert (
        failed_gate_names(evaluate_injury_history(a_tenth_of_the_rows_over_a_week_old, BOUNDS))
        == []
    )


@settings(max_examples=200, deadline=None)
@given(body=st.binary(max_size=4096))
def test_a_random_body_raises_only_an_fmsave_error(body: bytes) -> None:
    try:
        walk_injury_manager(body, LAYOUT, FILE_NAME)
    except FmsaveError:
        pass


@settings(max_examples=200, deadline=None)
@given(missing_bytes=st.integers(min_value=1, max_value=len(career_injury_manager())))
def test_a_truncated_body_raises_only_an_fmsave_error(missing_bytes: int) -> None:
    body = career_injury_manager()[:-missing_bytes]
    try:
        walk_injury_manager(body, LAYOUT, FILE_NAME)
    except FmsaveError:
        pass


def test_the_tail_the_layout_expects_is_the_one_every_save_ends_with() -> None:
    assert LAYOUT.tail == INJURY_MANAGER_TAIL
