from __future__ import annotations

import copy
import dataclasses
import pickle
import struct
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._checks import (
    GateResult,
    check_stadiums,
    enforce,
    evaluate_fixtures,
    evaluate_stadium_table,
    evaluate_stadiums,
)
from fmsave._context import STADIUM_INDEX_CACHE_KEY
from fmsave._errors import SaveClosedError
from fmsave._layouts import (
    FULL_SAVE_MINIMUM_SPAN_BYTES,
    GateBounds,
    StadiumTableLayout,
    find_layout,
)
from fmsave._reader_stats import FixtureStats, StadiumStats
from fmsave._status import field_status
from fmsave.export import column_names
from fmsave.models.fixtures import Fixture
from fmsave.models.stadiums import Stadium
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.stadiums import build_stadiums, read_stadium_index
from tests.fixtures.career import (
    ATHLETIC_UID,
    FIXTURE_STAGE_ID,
    LEAGUE_KICK_OFF_SLOT,
    NEUTRAL_VENUE_MINIMUM_FIXTURES,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    SOUTHPORT_TEAM,
    SOUTHPORT_UID,
    UNLISTED_STADIUM_FIXTURE,
    ExampleFixture,
    career_fragment,
)
from tests.fixtures.stadiums import (
    CAREER_NAMED_STADIUM,
    CAREER_NAMED_STADIUM_ORDINAL,
    CAREER_STADIUM_ROW_COUNT,
    CAREER_STADIUM_UID_BASE,
    CAREER_TEMPLATE_STADIUM_ORDINAL,
    STADIUM_INLINE_NAME_FLAG,
    STADIUM_TABLE_LEADING_BYTES,
    stadium_row_bytes,
    stadium_table_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 100 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
FULL_SIZE_SPAN_BYTES = FULL_SAVE_MINIMUM_SPAN_BYTES + MEBIBYTE
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT: StadiumTableLayout = find_layout(
    StadiumTableLayout, GAME_DB_SECTION, GAME_DB_SCHEMA, ""
).layout

TABLE_GATE_NAMES = (
    "stadium_rows_minimum",
    "stadium_pitch_within_limits",
    "stadium_owners_resolved",
    "stadium_capacity_within_all_seater",
)
STADIUM_GATE_NAMES = (*TABLE_GATE_NAMES, "stadium_home_grounds_owned")

# Positions in the table the reader returns, which is ordinal order.
FIRST_OWNED_GROUND = 9
SECOND_OWNED_GROUND = 19
UNLISTED_OWNER_GROUND = 29
UNOWNED_GROUND = 98
NAMED_GROUND = CAREER_NAMED_STADIUM_ORDINAL - 1
TEMPLATE_GROUND = CAREER_TEMPLATE_STADIUM_ORDINAL - 1
NON_TEMPLATE_ROWS = CAREER_STADIUM_ROW_COUNT - 1
# The ground the reserve-side test sends Northbridge's second team to, which is row 30.
RESERVE_STADIUM_ORDINAL = UNLISTED_OWNER_GROUND + 1

FIRST_GROUND_UID = CAREER_STADIUM_UID_BASE + 10
SECOND_GROUND_UID = CAREER_STADIUM_UID_BASE + 20
CUP_GROUND_UID = CAREER_STADIUM_UID_BASE + 99
NULL_DATE_AS_INT = 124_518_401

# Positions in the sorted calendar the fixture reader returns.
FIRST_LEAGUE_MATCH = 2
AWAY_LEAGUE_MATCH = 3
CUP_TIE = 4

EXPECTED_STADIUM_COLUMNS = (
    "uid",
    "name",
    "all_seater_capacity",
    "expansion_capacity",
    "capacity",
    "owner_club_uid",
    "owner_club_name",
    "home_club_uids",
    "home_club_names",
    "pitch_length_dm",
    "pitch_width_dm",
    "pitch_min_length_dm",
    "pitch_min_width_dm",
    "pitch_max_length_dm",
    "pitch_max_width_dm",
    "built_date",
    "rebuilt_date",
    "unknown_u17",
    "unknown_u25",
    "unknown_b33",
    "unknown_date_58",
    "unknown_flags_156",
)


def write_career(
    tmp_path: Path,
    extra_fixtures: Sequence[ExampleFixture] = (),
    *,
    stadium_table: bool = True,
) -> Path:
    return career_fragment(extra_fixtures=extra_fixtures, stadium_table=stadium_table).write(
        tmp_path / "Private Folder" / FILE_NAME
    )


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return write_career(tmp_path)


def built_from(career_save: fmsave.Save) -> tuple[tuple[Stadium, ...], StadiumStats]:
    """The table and its counts, built straight from the save's own shared indexes."""
    context = career_save._context
    fixtures = career_save.fixtures()
    with context.section(GAME_DB_SECTION):
        club_index = context.club_index()
        stadium_index = context.stadium_index()
    return build_stadiums(stadium_index, club_index, tuple(fixtures), LAYOUT)


def healthy_stats(**overrides: int) -> StadiumStats:
    """Counts with every rate comfortably inside its bound, at full-save size."""
    stats = StadiumStats(
        rows=47_748,
        table_end_reached=1,
        named_rows=220,
        template_rows=1,
        owners_set=12_698,
        owners_resolved=12_489,
        capacity_set=9_402,
        capacity_within_all_seater=47_734,
        pitch_checked=47_747,
        pitch_within_limits=47_747,
        clubs_with_home_ground=3_365,
        owning_clubs_with_home_ground=1_330,
        owning_clubs_home_ground_owned=942,
    )
    return dataclasses.replace(stats, **overrides)


def failed_gate_names(results: Sequence[GateResult]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def named_row_bytes(*, ordinal: int, name: str) -> bytes:
    """One row carrying an inline name, for the walk traps around a name's stored length."""
    return stadium_row_bytes(
        ordinal=ordinal,
        uid=CAREER_STADIUM_UID_BASE + ordinal,
        all_seater=5_000 + ordinal,
        expansion=6_000 + ordinal,
        owner_club_index=None,
        capacity=0,
        name=name,
    )


def example_rows(count: int, *, first_ordinal: int = 1) -> list[bytes]:
    """`count` plain rows, starting at `first_ordinal`."""
    return [
        stadium_row_bytes(
            ordinal=ordinal,
            uid=CAREER_STADIUM_UID_BASE + ordinal,
            all_seater=5_000 + ordinal,
            expansion=6_000 + ordinal,
            owner_club_index=None,
            capacity=0,
        )
        for ordinal in range(first_ordinal, first_ordinal + count)
    ]


def test_the_table_holds_one_row_per_walked_ground_in_ordinal_order(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        stadiums = save.stadiums()

    assert len(stadiums) == CAREER_STADIUM_ROW_COUNT
    assert stadiums[FIRST_OWNED_GROUND].uid == FIRST_GROUND_UID
    assert stadiums[TEMPLATE_GROUND].uid == CAREER_STADIUM_UID_BASE + 101
    assert [stadium.uid for stadium in stadiums] == sorted(stadium.uid for stadium in stadiums)


def test_every_field_of_one_fully_filled_ground(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        ground = save.stadiums()[FIRST_OWNED_GROUND]

    assert ground.all_seater_capacity == 5_010
    assert ground.expansion_capacity == 6_010
    assert ground.capacity == 5_010
    assert ground.owner_club_uid == NORTHBRIDGE_UID
    assert ground.owner_club_name == "Northbridge FC"
    assert ground.pitch_length_dm == 1050
    assert ground.pitch_width_dm == 680
    assert ground.pitch_min_length_dm == 900
    assert ground.pitch_min_width_dm == 550
    assert ground.pitch_max_length_dm == 1200
    assert ground.pitch_max_width_dm == 900
    assert ground.built_date == date(1950, 4, 10)
    assert ground.rebuilt_date == date(1990, 2, 19)
    assert dict(ground.unknown) == {
        "u17": 5_000,
        "u25": 4_000,
        "b33": 10,
        "date_58": NULL_DATE_AS_INT,
        "flags_156": 0,
    }


def test_an_owner_no_club_holds_and_a_ground_with_no_owner(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        stadiums, stats = built_from(save)

    assert stadiums[SECOND_OWNED_GROUND].capacity is None
    assert stadiums[SECOND_OWNED_GROUND].owner_club_uid == SOUTHPORT_UID
    assert stadiums[UNLISTED_OWNER_GROUND].owner_club_uid is None
    assert stadiums[UNLISTED_OWNER_GROUND].owner_club_name is None
    assert stats.owners_set - stats.owners_resolved == 1
    assert stadiums[UNOWNED_GROUND].owner_club_uid is None
    assert stats.owners_set == 3


def test_an_inline_name_is_read_and_the_row_after_it_still_decodes(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        stadiums, stats = built_from(save)

    assert stadiums[NAMED_GROUND].name == CAREER_NAMED_STADIUM
    assert stadiums[NAMED_GROUND].unknown["flags_156"] == STADIUM_INLINE_NAME_FLAG
    assert stats.named_rows == 1
    assert stadiums[TEMPLATE_GROUND].uid == CAREER_STADIUM_UID_BASE + 101
    assert stadiums[NAMED_GROUND].name is not None
    assert stadiums[FIRST_OWNED_GROUND].name is None


def test_the_template_row_is_returned_and_left_out_of_the_pitch_count(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        stadiums, stats = built_from(save)

    assert stadiums[TEMPLATE_GROUND].all_seater_capacity == 16_777_216
    assert stats.template_rows == 1
    assert stats.pitch_checked == NON_TEMPLATE_ROWS
    assert stats.pitch_within_limits == NON_TEMPLATE_ROWS


def test_the_home_grounds_come_from_the_calendar(tmp_path: Path) -> None:
    with fmsave.open(write_career(tmp_path)) as save:
        stadiums = save.stadiums()

    assert stadiums[FIRST_OWNED_GROUND].home_club_uids == (NORTHBRIDGE_UID,)
    assert stadiums[FIRST_OWNED_GROUND].home_club_names == ("Northbridge FC",)
    assert stadiums[SECOND_OWNED_GROUND].home_club_uids == ()
    assert stadiums[SECOND_OWNED_GROUND].home_club_names == ()


def test_one_ground_serves_every_club_that_plays_most_of_its_home_matches_there(
    tmp_path: Path,
) -> None:
    career_path = write_career(tmp_path, NEUTRAL_VENUE_MINIMUM_FIXTURES)
    with fmsave.open(career_path) as save:
        stadiums = save.stadiums()

    assert stadiums[FIRST_OWNED_GROUND].home_club_uids == (NORTHBRIDGE_UID, ATHLETIC_UID)
    assert stadiums[FIRST_OWNED_GROUND].home_club_names == ("Northbridge FC", "Example Athletic")
    assert stadiums[SECOND_OWNED_GROUND].home_club_uids == ()


def test_only_a_clubs_first_team_votes_for_its_home_ground(tmp_path: Path) -> None:
    """A reserve side often plays elsewhere, and its matches must not move the club's ground.

    Northbridge's second team plays five home matches at ground 30 here, against its first
    team's four at ground 10. Counting them would carry the vote and make ground 30 the club's
    home; only the first team's matches count, so ground 10 keeps it and ground 30 has no club.
    """
    reserve_fixtures = tuple(
        ExampleFixture(
            FIXTURE_STAGE_ID,
            NORTHBRIDGE_TEAM_B,
            SOUTHPORT_TEAM,
            142 + 7 * step,
            LEAGUE_KICK_OFF_SLOT,
            14 + step,
            True,
            RESERVE_STADIUM_ORDINAL,
        )
        for step in range(5)
    )
    with fmsave.open(write_career(tmp_path, reserve_fixtures)) as save:
        stadiums = save.stadiums()

    assert stadiums[FIRST_OWNED_GROUND].home_club_uids == (NORTHBRIDGE_UID,)
    assert stadiums[UNLISTED_OWNER_GROUND].home_club_uids == ()


def test_the_owned_home_ground_counts_the_checks_judge(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        _stadiums, stats = built_from(save)

    assert stats.clubs_with_home_ground == 1
    assert stats.owning_clubs_with_home_ground == 1
    assert stats.owning_clubs_home_ground_owned == 1


def test_each_fixture_carries_the_ground_its_record_stores(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        fixtures = save.fixtures()

    assert fixtures[FIRST_LEAGUE_MATCH].stadium_uid == FIRST_GROUND_UID
    assert fixtures[AWAY_LEAGUE_MATCH].stadium_uid == SECOND_GROUND_UID
    assert fixtures[CUP_TIE].stadium_uid == CUP_GROUND_UID


def test_a_ground_the_table_does_not_hold_leaves_the_fixture_empty(tmp_path: Path) -> None:
    career_path = write_career(tmp_path, (UNLISTED_STADIUM_FIXTURE,))
    with fmsave.open(career_path) as save:
        fixtures = save.fixtures()
        reader_check = save._reader_check("fixtures")

    unlisted = [fixture for fixture in fixtures if fixture.date == date(2031, 5, 15)]
    assert len(unlisted) == 1
    assert unlisted[0].stadium_uid is None
    assert reader_check is not None
    assert reader_check.anomalies["unresolved_stadiums"] == 1


def test_the_new_fixture_column_sits_beside_the_venue_flag() -> None:
    columns = column_names(Fixture)

    assert "stadium_uid" in columns
    assert columns[columns.index("is_neutral_venue") + 1] == "stadium_uid"
    # A derived field is no stronger than its inputs, and the stadium uid it carries is
    # measured rather than displayed anywhere.
    assert field_status(Fixture, "stadium_uid") == "unconfirmed"
    assert field_status(Stadium, "uid") == "unconfirmed"


def test_a_save_with_no_stadium_table_raises_for_both_readers(tmp_path: Path) -> None:
    career_path = write_career(tmp_path, stadium_table=False)
    for reader_name in ("fixtures", "stadiums"):
        with (
            fmsave.open(career_path) as save,
            pytest.raises(fmsave.ReaderCheckError) as error_info,
        ):
            getattr(save, reader_name)()
        message = str(error_info.value)
        assert f"section {GAME_DB_SECTION!r}" in message
        for fictional_text in ("Northbridge", "Southport", "Example Park", "Alex"):
            assert fictional_text not in message


def test_a_decoy_run_of_ordinals_is_skipped_for_the_real_table() -> None:
    decoy = [
        stadium_row_bytes(
            ordinal=ordinal,
            uid=CAREER_STADIUM_UID_BASE + ordinal,
            all_seater=1_000,
            expansion=1_000,
            owner_club_index=None,
            capacity=0,
        )
        for ordinal in range(1, 4)
    ]
    # Break the doubled uid on every decoy row, which is what the acceptance test rejects.
    broken_decoy = []
    for row in decoy:
        mutable_row = bytearray(row)
        struct.pack_into("<I", mutable_row, 8, 42)
        broken_decoy.append(bytes(mutable_row))
    rows = example_rows(20)
    game_db = stadium_table_bytes(broken_decoy) + stadium_table_bytes(rows)

    index = read_stadium_index(game_db, LAYOUT, FILE_NAME)

    assert len(index.rows) == 20
    assert index.locator_hits >= 2


def test_a_name_that_is_not_utf8_ends_the_walk() -> None:
    rows = example_rows(20)
    named = bytearray(
        stadium_row_bytes(
            ordinal=21,
            uid=CAREER_STADIUM_UID_BASE + 21,
            all_seater=5_021,
            expansion=6_021,
            owner_club_index=None,
            capacity=0,
            name=CAREER_NAMED_STADIUM,
        )
    )
    name_start = LAYOUT.name_offset
    named[name_start : name_start + len(CAREER_NAMED_STADIUM)] = b"\xff" * len(CAREER_NAMED_STADIUM)
    game_db = stadium_table_bytes([*rows, bytes(named), *example_rows(1, first_ordinal=22)])

    index = read_stadium_index(game_db, LAYOUT, FILE_NAME)

    assert len(index.rows) == 20
    assert index.reached_table_end is False


@pytest.mark.parametrize(
    "stored_name_length",
    [LAYOUT.name_length_range[0] - 1, LAYOUT.name_length_range[1] + 1],
    ids=["below-the-range", "above-the-range"],
)
def test_a_name_length_outside_the_layouts_range_ends_the_walk(stored_name_length: int) -> None:
    """The stored length decides where the next row starts, so one out of range ends the walk.

    The table is padded well past the row, so the name the length promises is inside the
    section and reads as sound text: the range is the only thing that can turn it away.
    """
    named = bytearray(named_row_bytes(ordinal=21, name=CAREER_NAMED_STADIUM))
    struct.pack_into("<I", named, LAYOUT.name_length_offset, stored_name_length)
    game_db = stadium_table_bytes([*example_rows(20), bytes(named)], trailing_bytes=1024)

    index = read_stadium_index(game_db, LAYOUT, FILE_NAME)

    assert len(index.rows) == 20
    assert index.reached_table_end is False


def test_a_name_running_past_the_section_ends_the_walk() -> None:
    """A length inside the range still ends the walk when the name it promises is not there."""
    plain_rows = example_rows(20)
    long_name = "x" * 200
    game_db = stadium_table_bytes([*plain_rows, named_row_bytes(ordinal=21, name=long_name)])
    # Cut where the named row's own unnamed-length bytes end, so its stored length reads but
    # the 200 bytes of name it promises are gone.
    named_row_start = STADIUM_TABLE_LEADING_BYTES + len(b"".join(plain_rows))
    game_db = game_db[: named_row_start + LAYOUT.row_bytes]

    index = read_stadium_index(game_db, LAYOUT, FILE_NAME)

    assert len(index.rows) == 20
    assert index.reached_table_end is False


def test_a_table_cut_through_a_row_keeps_the_complete_rows() -> None:
    rows = example_rows(20)
    whole_table = stadium_table_bytes(rows)
    cut_at = len(whole_table) - LAYOUT.row_bytes // 2

    index = read_stadium_index(whole_table[:cut_at], LAYOUT, FILE_NAME)

    assert len(index.rows) == 19
    assert index.reached_table_end is False


def test_a_whole_table_ends_where_the_terminator_word_sits() -> None:
    index = read_stadium_index(stadium_table_bytes(example_rows(20)), LAYOUT, FILE_NAME)

    assert len(index.rows) == 20
    assert index.reached_table_end is True


def test_a_repeated_stadium_uid_raises() -> None:
    """Two rows sharing a uid would merge their home clubs and hand one row the other's owner."""
    repeated_uid = CAREER_STADIUM_UID_BASE + 1
    rows = [
        stadium_row_bytes(
            ordinal=ordinal,
            # Every row keeps its own ordinal; the thirteenth repeats the first row's uid.
            uid=repeated_uid if ordinal in (1, 13) else CAREER_STADIUM_UID_BASE + ordinal,
            all_seater=5_000 + ordinal,
            expansion=6_000 + ordinal,
            owner_club_index=None,
            capacity=0,
        )
        for ordinal in range(1, 21)
    ]

    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        read_stadium_index(stadium_table_bytes(rows), LAYOUT, FILE_NAME)

    message = str(error_info.value)
    assert "a stadium uid appears in two rows" in message
    assert f"section {GAME_DB_SECTION!r}" in message
    assert str(repeated_uid) not in message


def test_the_index_repr_hides_the_ground_names(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.stadiums()
        description = repr(save._context.cached_value(STADIUM_INDEX_CACHE_KEY))

    assert FILE_NAME not in description
    for fictional_text in (CAREER_NAMED_STADIUM, "Northbridge", "Southport"):
        assert fictional_text not in description
    assert f"{CAREER_STADIUM_ROW_COUNT} grounds" in description
    assert "1 named" in description


def test_the_columns_the_export_flattens() -> None:
    assert column_names(Stadium) == EXPECTED_STADIUM_COLUMNS


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        stadiums = save.stadiums()
        row = stadiums[FIRST_OWNED_GROUND]

    # A round trip of fmsave's own records, not data from anywhere else.
    assert pickle.loads(pickle.dumps(row)) == row
    assert copy.deepcopy(row) == row
    assert pickle.loads(pickle.dumps(stadiums)) == stadiums
    assert copy.deepcopy(stadiums) == stadiums


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first_table = save.stadiums()
        assert save.stadiums() is first_table

    with pytest.raises(SaveClosedError):
        save.stadiums()


def test_the_field_statuses_follow_the_stadium_coverage() -> None:
    for verified_field in (
        "all_seater_capacity",
        "expansion_capacity",
        "pitch_length_dm",
        "pitch_width_dm",
        "built_date",
        "rebuilt_date",
    ):
        assert field_status(Stadium, verified_field) == "verified", verified_field
    for unconfirmed_field in ("uid", "name", "capacity", "owner_club_uid", "home_club_uids"):
        assert field_status(Stadium, unconfirmed_field) == "unconfirmed", unconfirmed_field
    assert Stadium.UNKNOWN_KEYS == ("u17", "u25", "b33", "date_58", "flags_156")


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(healthy_stats(), [], id="the-measured-counts"),
        pytest.param(healthy_stats(rows=9_999), ["stadium_rows_minimum"], id="too-few-rows"),
        pytest.param(
            healthy_stats(pitch_checked=10_000, pitch_within_limits=9_800),
            ["stadium_pitch_within_limits"],
            id="pitches-outside-their-own-limits",
        ),
        pytest.param(
            healthy_stats(owners_set=47_748, owners_resolved=33),
            ["stadium_owners_resolved"],
            id="owners-that-name-no-club",
        ),
        pytest.param(
            healthy_stats(capacity_within_all_seater=17_968),
            ["stadium_capacity_within_all_seater"],
            id="capacities-above-the-all-seater",
        ),
        pytest.param(
            healthy_stats(owning_clubs_with_home_ground=1_330, owning_clubs_home_ground_owned=2),
            ["stadium_home_grounds_owned"],
            id="home-grounds-owned-by-someone-else",
        ),
    ],
)
def test_the_stadium_gates_fail_one_at_a_time(
    stats: StadiumStats, expected_failures: list[str]
) -> None:
    results = evaluate_stadiums(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert [result.name for result in results] == list(STADIUM_GATE_NAMES)
    assert failed_gate_names(results) == expected_failures
    if not expected_failures:
        enforce("stadiums", results, strict=True)
        return
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("stadiums", results, strict=True)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Northbridge", "Example Park", FILE_NAME):
        assert fictional_text not in message


def test_the_table_gates_are_the_four_the_index_is_enforced_on() -> None:
    results = evaluate_stadium_table(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert [result.name for result in results] == list(TABLE_GATE_NAMES)
    assert failed_gate_names(results) == []


def test_no_stadium_gate_applies_on_a_small_game_db() -> None:
    """Counts a fragment cannot meet are reported as not applied, name by name."""
    results = evaluate_stadiums(
        healthy_stats(rows=101, owning_clubs_home_ground_owned=0), BOUNDS, SMALL_GAME_DB_BYTES
    )

    assert [(result.name, result.applied) for result in results] == [
        (name, False) for name in STADIUM_GATE_NAMES
    ]


def test_an_empty_population_leaves_a_share_gate_unapplied() -> None:
    """A share gate with no denominator did not fail: nothing was there to judge."""
    results = evaluate_stadiums(
        healthy_stats(
            owners_set=0,
            owners_resolved=0,
            owning_clubs_with_home_ground=0,
            owning_clubs_home_ground_owned=0,
        ),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    applied_names = [result.name for result in results if result.applied]

    assert "stadium_owners_resolved" not in applied_names
    assert "stadium_home_grounds_owned" not in applied_names
    assert "stadium_rows_minimum" in applied_names
    assert failed_gate_names(results) == []


def healthy_fixture_stats(**overrides: int) -> FixtureStats:
    """Fixture counts with every rate inside its bound, including the ground join."""
    stats = FixtureStats(
        span_records=106_600,
        cluster_records=105_546,
        clusters=18,
        strays_without_a_copy=150,
        with_stage=105_000,
        stage_resolved=104_800,
        home_team_resolved=105_400,
        away_team_resolved=105_400,
        undated=0,
        bad_kick_off_slots=0,
        neutral_venue_votes=600,
        with_stadium=104_331,
        stadium_resolved=104_265,
    )
    return dataclasses.replace(stats, **overrides)


def test_a_ground_join_that_lost_the_named_tail_fails_its_gate() -> None:
    """The floor sits above the share a table missing its named rows resolves at."""
    lost_tail = healthy_fixture_stats(stadium_resolved=103_809)
    results = evaluate_fixtures(lost_tail, BOUNDS, FULL_SIZE_SPAN_BYTES)
    passing = evaluate_fixtures(healthy_fixture_stats(), BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == ["fixture_stadiums_resolved"]
    assert failed_gate_names(passing) == []


def test_a_calendar_that_stores_no_ground_leaves_the_join_gate_unapplied() -> None:
    results = evaluate_fixtures(
        healthy_fixture_stats(with_stadium=0, stadium_resolved=0),
        BOUNDS,
        FULL_SIZE_SPAN_BYTES,
    )
    applied_names = [result.name for result in results if result.applied]

    assert "fixture_stadiums_resolved" not in applied_names
    assert failed_gate_names(results) == []


def test_the_reader_check_reports_the_counts_and_the_anomalies() -> None:
    reader_check = check_stadiums(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert reader_check.reader == "stadiums"
    assert reader_check.record_count == 47_748
    assert dict(reader_check.anomalies) == {
        "walk_stopped_before_the_table_end": 0,
        "named_rows": 220,
        "template_rows": 1,
        "unresolved_owners": 209,
        "unset_capacities": 38_346,
        "clubs_with_home_ground": 3_365,
    }
