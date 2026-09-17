from __future__ import annotations

import copy
import pickle
import random
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._errors import FmsaveError, ReaderCheckError, SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import TrainingStats
from fmsave.checks import (
    MENTORING_READER,
    TRAINING_READER,
    GateResult,
    evaluate_mentoring,
    evaluate_training,
)
from fmsave.export import column_names
from fmsave.models.training import MentoringGroup, TeamTraining, TrainingSchedule, TrainingWeek
from fmsave.readers._common import GAME_DB_SECTION, TRAINING_SECTION
from fmsave.readers.training import (
    build_training_tables,
    find_training_layout,
    locate_schedule_library,
    walk_training_blocks,
)
from tests.fixtures.career import (
    CAREER_SCHEDULE_LIBRARY,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    PLAYER_A_UID,
    PLAYER_C_UID,
    TRAINING_YEAR,
    UNREGISTERED_FIXTURE_TEAM_ID,
    career_fragment,
    career_training_blocks,
    career_training_section,
)
from tests.fixtures.container import packed_date
from tests.fixtures.training import (
    TRAINING_SCHEMA,
    mentoring_group_bytes,
    training_block_bytes,
    training_header_entry_bytes,
    training_man_body,
    training_week_bytes,
)

GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 100 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_training_layout(TRAINING_SCHEMA, "")
FILE_NAME = "career.bin"
CLUB_TEAM_IDS = frozenset({NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B})
BLOCKS_GATE_NAME = "training_blocks_match_club_teams"
WEEK_STEPS_GATE_NAME = "training_week_steps"
MEMBERS_AT_CLUB_GATE_NAME = "mentoring_members_at_club"
CAREER_LIBRARY_ROWS = tuple(
    TrainingSchedule(folder, name, {"schedule_id": schedule_id})
    for folder, schedule_id, name in CAREER_SCHEDULE_LIBRARY
)
# Counts every save measured reports: five team blocks of one five-team club, 290 weekly
# records whose 285 steps all step seven days, and ten mentoring groups of 24 players.
MEASURED_CLUB_TEAMS = 5
MEASURED_BLOCKS = 5
MEASURED_WEEKS = 290
MEASURED_WEEK_STEPS = 285
MEASURED_MEMBERS = 24
# The same counts with the block walk started one or four bytes late, which parses no block.
MISALIGNED_BLOCKS = 0
# The same members with each selector read one higher: they still resolve (21 of 21 on one
# save measured), but only one of them is then a player of the managed club.
PLUS_ONE_MEMBERS_AT_CLUB = 1


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_stats(**overrides: object) -> TrainingStats:
    """Counts as every save measured reports them, before any override."""
    fields: dict[str, object] = {
        "managed_club_exists": True,
        "club_team_count": MEASURED_CLUB_TEAMS,
        "blocks": MEASURED_BLOCKS,
        "header_entries": 109,
        "weeks": MEASURED_WEEKS,
        "week_steps": MEASURED_WEEK_STEPS,
        "seven_day_steps": MEASURED_WEEK_STEPS,
        "undated_weeks": 0,
        "library_entries": 8,
        "groups": 10,
        "members": MEASURED_MEMBERS,
        "members_resolved": MEASURED_MEMBERS,
        "members_at_club": MEASURED_MEMBERS,
    }
    return TrainingStats(**(fields | overrides))  # pyright: ignore[reportArgumentType]


def week_bytes(day_of_year: int, schedule_name: str) -> bytes:
    return training_week_bytes(
        week_start=packed_date(day_of_year, TRAINING_YEAR), schedule_name=schedule_name
    )


def one_block_body(weeks: tuple[bytes, ...], *, team_id: int = NORTHBRIDGE_TEAM_A) -> bytes:
    """A section holding one block of the managed club, with no group and no library."""
    return training_man_body(
        header_entries=(),
        blocks=(
            training_block_bytes(team_id=team_id, entries=0, weeks=weeks, groups=(), last=True),
        ),
    )


def active_week(team_training: TeamTraining, clock: date) -> date | None:
    """The active week of a team: the latest week starting on or before the save's date."""
    started = [
        week.week_start
        for week in team_training.weeks
        if week.week_start is not None and week.week_start <= clock
    ]
    return max(started) if started else None


def test_one_row_per_block_in_stored_order_with_its_club_and_slot(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        teams = save.training()

    assert len(teams) == 2
    assert [row.team_id for row in teams] == [NORTHBRIDGE_TEAM_B, NORTHBRIDGE_TEAM_A]
    assert [row.club_uid for row in teams] == [NORTHBRIDGE_UID, NORTHBRIDGE_UID]
    assert [row.club_name for row in teams] == ["Northbridge FC", "Northbridge FC"]
    assert [row.team_slot for row in teams] == [1, 0]


def test_each_name_belongs_to_the_date_written_before_it(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        teams = save.training()

    first_team = next(row for row in teams if row.team_id == NORTHBRIDGE_TEAM_A)
    assert first_team.weeks == (
        TrainingWeek(date(2031, 2, 17), "Example Balanced"),
        TrainingWeek(date(2031, 2, 24), "Example Recovery"),
        TrainingWeek(date(2031, 3, 3), "Example Balanced"),
    )


def test_a_differing_second_name_moves_with_its_own_date_not_the_next_record() -> None:
    body = one_block_body((week_bytes(48, "Example Light"), week_bytes(55, "Example Balanced")))

    blocks, _counts = walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert blocks[0].weeks == (
        TrainingWeek(date(2031, 2, 17), "Example Light"),
        TrainingWeek(date(2031, 2, 24), "Example Balanced"),
    )


@pytest.mark.parametrize("name_length", [3, 40])
def test_the_length_rule_walks_names_of_any_length(name_length: int) -> None:
    schedule_name = "E" * name_length
    body = one_block_body((week_bytes(48, schedule_name), week_bytes(55, schedule_name)))

    blocks, counts = walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert [week.schedule_name for week in blocks[0].weeks] == [schedule_name, schedule_name]
    assert counts.weeks == 2


def test_the_walk_counts_every_block_week_and_step(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.training()
        reader_check = save._reader_check(TRAINING_READER)
        with save._context.section(TRAINING_SECTION) as training:
            blocks, counts = walk_training_blocks(training, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert len(blocks) == 2
    assert counts.weeks == 5
    assert counts.week_steps == 3
    assert counts.seven_day_steps == 3
    assert counts.header_entries == 1
    assert reader_check is not None
    assert reader_check.record_count == 2
    assert reader_check.anomalies == {
        "undated_weeks": 0,
        "header_entries": 1,
        "library_entries": 3,
    }


def test_the_active_week_of_each_team_is_the_latest_one_already_started(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        clock = save.info.game_date
        teams = save.training()

    assert clock == date(2031, 3, 1)
    assert [active_week(row, date(2031, 3, 1)) for row in teams] == [
        date(2031, 2, 24),
        date(2031, 2, 24),
    ]


@pytest.mark.parametrize("late_bytes", [1, 4])
def test_a_walk_started_late_parses_no_block(late_bytes: int) -> None:
    body = training_man_body(
        header_entries=(),
        blocks=career_training_blocks(),
        header_gap=bytes(3 + late_bytes),
    )

    blocks, counts = walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert blocks == ()
    assert counts.weeks == 0
    assert counts.week_steps == 0


def test_a_block_of_another_clubs_team_ends_the_walk_before_it(tmp_path: Path) -> None:
    body = one_block_body((week_bytes(48, "Example Light"),), team_id=UNREGISTERED_FIXTURE_TEAM_ID)
    save_path = career_fragment(training_section=body).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        teams = save.training()
        save.clubs()
        club_index = save._context.club_index()
        player_records = save._context.player_records()
        players = save.players()
        with save._context.section(TRAINING_SECTION) as training:
            blocks, counts = walk_training_blocks(training, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)
            _teams, _groups, stats = build_training_tables(
                blocks, (), club_index, player_records, players, NORTHBRIDGE_UID, counts
            )

    assert len(teams) == 0
    assert stats.blocks == 0
    assert stats.club_team_count == 2
    assert failed_gate_names(evaluate_training(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)) == [
        BLOCKS_GATE_NAME,
        WEEK_STEPS_GATE_NAME,
    ]


def test_a_step_of_eight_days_is_returned_and_counted_apart() -> None:
    body = one_block_body((week_bytes(48, "Example Light"), week_bytes(56, "Example Light")))

    blocks, counts = walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert [week.week_start for week in blocks[0].weeks] == [
        date(2031, 2, 17),
        date(2031, 2, 25),
    ]
    assert counts.week_steps == 1
    assert counts.seven_day_steps == counts.week_steps - 1


def test_with_the_manager_between_jobs_both_tables_are_empty_and_nothing_is_judged(
    tmp_path: Path,
) -> None:
    save_path = career_fragment(manager_between_jobs=True).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        teams = save.training()
        groups = save.mentoring()
        training_check = save._reader_check(TRAINING_READER)
        mentoring_check = save._reader_check(MENTORING_READER)

    assert len(teams) == 0
    assert len(groups) == 0
    assert training_check is not None
    assert mentoring_check is not None
    assert [gate.applied for gate in training_check.gates] == [False, False]
    assert [gate.applied for gate in mentoring_check.gates] == [False]


def test_every_row_carries_the_sections_one_schedule_library(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        teams = save.training()

    for row in teams:
        assert len(row.schedule_library) == len(CAREER_LIBRARY_ROWS)
        for read_schedule, expected in zip(row.schedule_library, CAREER_LIBRARY_ROWS, strict=True):
            assert read_schedule.folder == expected.folder
            assert read_schedule.name == expected.name
            assert dict(read_schedule.unknown) == dict(expected.unknown)


def test_a_section_with_no_library_bytes_still_returns_every_row(tmp_path: Path) -> None:
    body = career_training_section(library=False)
    save_path = career_fragment(training_section=body).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        teams = save.training()

    assert len(teams) == 2
    assert [row.schedule_library for row in teams] == [(), ()]


def test_the_library_is_read_from_after_the_last_block_only() -> None:
    body = career_training_section()
    blocks, counts = walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)

    assert len(blocks) == 2
    assert len(locate_schedule_library(body, counts.blocks_end, LAYOUT)) == 3
    assert locate_schedule_library(body, len(body), LAYOUT) == ()


def test_one_row_per_mentoring_group_with_its_members(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        groups = save.mentoring()

    assert len(groups) == 2
    first_group, second_group = groups
    assert first_group.team_id == NORTHBRIDGE_TEAM_A
    assert first_group.club_uid == NORTHBRIDGE_UID
    assert first_group.team_slot == 0
    assert first_group.group_number == 1
    assert first_group.label == "Group 1"
    assert first_group.member_uids == (PLAYER_C_UID, PLAYER_A_UID)
    assert first_group.member_names == ("Sam Sample", "Alex Example")
    assert second_group.group_number == 2
    assert second_group.label == "Group 2"
    assert second_group.member_uids == (None,)
    assert second_group.member_names == (None,)


def test_the_mentoring_counts_and_anomalies(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.mentoring()
        reader_check = save._reader_check(MENTORING_READER)
        save.clubs()
        club_index = save._context.club_index()
        player_records = save._context.player_records()
        players = save.players()
        with save._context.section(TRAINING_SECTION) as training:
            blocks, counts = walk_training_blocks(training, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)
            _teams, _groups, stats = build_training_tables(
                blocks, (), club_index, player_records, players, NORTHBRIDGE_UID, counts
            )

    assert stats.groups == 2
    assert stats.members == 3
    assert stats.members_resolved == 2
    assert stats.members_at_club == 1
    assert reader_check is not None
    assert reader_check.record_count == 2
    assert reader_check.anomalies == {"members_without_a_player": 1, "members_elsewhere": 1}


def test_the_columns_the_export_flattens() -> None:
    assert column_names(TeamTraining) == (
        "team_id",
        "club_uid",
        "club_name",
        "team_slot",
        "weeks",
        "schedule_library",
    )
    assert column_names(MentoringGroup) == (
        "team_id",
        "club_uid",
        "club_name",
        "team_slot",
        "group_number",
        "label",
        "member_uids",
        "member_names",
    )


def test_every_new_record_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        teams = save.training()
        groups = save.mentoring()

    records: tuple[object, ...] = (
        teams,
        groups,
        teams[0],
        teams[0].weeks[0],
        teams[1].schedule_library[0],
        groups[0],
    )
    for record in records:
        # A round trip of fmsave's own records, not data from anywhere else.
        assert pickle.loads(pickle.dumps(record)) == record
        assert copy.deepcopy(record) == record


def test_both_tables_come_from_one_decode_and_raise_after_the_save_is_closed(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        teams = save.training()
        groups = save.mentoring()
        assert save.training() is teams
        assert save.mentoring() is groups

    with pytest.raises(SaveClosedError):
        save.training()
    with pytest.raises(SaveClosedError):
        save.mentoring()


def test_a_misaligned_count_fails_each_gate_and_the_measured_counts_pass() -> None:
    fewer_blocks = evaluate_training(healthy_stats(blocks=4), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    longer_step = evaluate_training(
        healthy_stats(seven_day_steps=MEASURED_WEEK_STEPS - 3), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    no_steps = evaluate_training(
        healthy_stats(blocks=MISALIGNED_BLOCKS, weeks=0, week_steps=0, seven_day_steps=0),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    members_elsewhere = evaluate_mentoring(
        healthy_stats(members_at_club=PLUS_ONE_MEMBERS_AT_CLUB),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    passing_training = evaluate_training(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    passing_mentoring = evaluate_mentoring(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(fewer_blocks) == [BLOCKS_GATE_NAME]
    assert failed_gate_names(longer_step) == [WEEK_STEPS_GATE_NAME]
    assert failed_gate_names(no_steps) == [BLOCKS_GATE_NAME, WEEK_STEPS_GATE_NAME]
    assert failed_gate_names(members_elsewhere) == [MEMBERS_AT_CLUB_GATE_NAME]
    assert failed_gate_names(passing_training) == []
    assert failed_gate_names(passing_mentoring) == []


def test_no_gate_applies_on_a_small_save_or_without_a_managed_club_or_a_member() -> None:
    small_game_db = evaluate_training(healthy_stats(blocks=4), BOUNDS, SMALL_GAME_DB_BYTES)
    no_managed_club = evaluate_training(
        healthy_stats(managed_club_exists=False, blocks=4), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    no_members = evaluate_mentoring(
        healthy_stats(groups=0, members=0, members_resolved=0, members_at_club=0),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )

    assert [gate.applied for gate in small_game_db] == [False, False]
    assert [gate.applied for gate in no_managed_club] == [False, False]
    assert [gate.applied for gate in no_members] == [False]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(training_man_body(header_entries=(), blocks=())[:20], id="a short section"),
        pytest.param(
            training_man_body(
                header_entries=(
                    training_header_entry_bytes(
                        selector=12,
                        first_date=packed_date(50, TRAINING_YEAR),
                        second_date=packed_date(57, TRAINING_YEAR),
                    ),
                )
                * 4,
                blocks=(),
            )[:34],
            id="a header list that runs past the section",
        ),
        pytest.param(
            one_block_body((week_bytes(48, "Example Light"),))[:-20],
            id="a block that runs past the section",
        ),
        pytest.param(
            training_man_body(
                header_entries=(),
                blocks=(
                    training_block_bytes(
                        team_id=NORTHBRIDGE_TEAM_A,
                        entries=0,
                        weeks=(week_bytes(48, "Example Light"),),
                        groups=(
                            mentoring_group_bytes(
                                number=1, label="Group 1", member_selectors=range(200)
                            ),
                        ),
                        last=True,
                    ),
                ),
            ),
            id="a group above the corruption cap",
        ),
    ],
)
def test_a_body_the_walk_cannot_read_names_its_section(body: bytes) -> None:
    with pytest.raises(ReaderCheckError, match="'training_man'"):
        walk_training_blocks(body, CLUB_TEAM_IDS, LAYOUT, FILE_NAME)


def test_random_and_truncated_bodies_raise_only_fmsave_errors() -> None:
    generator = random.Random(20260917)
    healthy = career_training_section()
    bodies = [bytes(generator.randbytes(generator.randint(0, 400))) for _ in range(120)]
    bodies.extend(healthy[: generator.randrange(len(healthy))] for _ in range(60))
    for body in bodies:
        mutated = bytearray(body)
        if mutated:
            mutated[generator.randrange(len(mutated))] = generator.randrange(256)
        try:
            blocks, counts = walk_training_blocks(bytes(mutated), CLUB_TEAM_IDS, LAYOUT, FILE_NAME)
            locate_schedule_library(bytes(mutated), counts.blocks_end, LAYOUT)
        except FmsaveError:
            continue
        assert isinstance(blocks, tuple)
