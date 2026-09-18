from __future__ import annotations

import copy
import pickle
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._checks import JOB_VACANCIES_READER, GateResult, evaluate_job_vacancies
from fmsave._errors import ReaderCheckError, SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import JobVacancyStats
from fmsave.export import column_names
from fmsave.models.jobs import JobVacancy
from fmsave.readers._common import GAME_DB_SECTION, MISSING_REFERENCE
from fmsave.readers.jobs import find_job_centre_layout, read_job_vacancies
from tests.fixtures.career import (
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_UID,
    SECOND_COMPETITION_DATABASE_ID,
    SECOND_COMPETITION_ID,
    SOUTHPORT_UID,
    UNREGISTERED_FIXTURE_TEAM_ID,
    career_fragment,
    career_job_records,
)
from tests.fixtures.club_sections import job_centre_body, job_record_bytes
from tests.fixtures.container import packed_date

GAME_DB_SCHEMA = 4000
JOB_CENTRE_SCHEMA = 1
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_job_centre_layout(JOB_CENTRE_SCHEMA, "")
FILE_NAME = "career.bin"
EXAMPLE_COMPETITION_NAMES = {
    FIRST_COMPETITION_DATABASE_ID: "Example League",
    SECOND_COMPETITION_DATABASE_ID: "Example Cup",
}
# The raw four bytes of each example record's second date, read as one little-endian int.
FIRST_DATE_12 = 133_106_216
SECOND_DATE_12 = 133_103_649
# Counts the biggest feed measured reports, and the smallest feed the gates apply to.
MEASURED_RECORDS = 134
MEASURED_TEAMS_RESOLVED = 129
MEASURED_WITH_LEAGUE_POSITION = 104
MEASURED_FLAGGED = 9
MINIMUM_RECORDS = BOUNDS.job_vacancy_minimum_applies_from_records
# What a record start shifted by a whole field lands on, measured on the saves the shift was
# run against: a shift drops one record off the end, so those feeds hold one record fewer.
SHIFTED_RECORDS = MEASURED_RECORDS - 1
SHIFTED_TAGGED = 2
SHIFTED_RESERVED_ZERO = 1
# The one shifted share that is not near zero: 41 of 42 steps on the smallest feed measured.
SHIFTED_ASCENDING_RECORDS = 43
SHIFTED_ASCENDING_STEPS = 42
SHIFTED_ASCENDING_OK = 41


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def sound_stats(records: int, **overrides: int) -> JobVacancyStats:
    """Counts a feed of `records` sound records reports, before any override."""
    fields = {
        "records": records,
        "tagged": records,
        "dates_ordered": records,
        "advertised_steps": max(records - 1, 0),
        "advertised_ascending_steps": max(records - 1, 0),
        "reserved_zero": records,
        "competitions_known": records,
        "teams_resolved": records,
        "with_competition": records,
        "with_league_position": records,
        "flagged": 0,
    }
    return JobVacancyStats(**(fields | overrides))


def healthy_stats(**overrides: int) -> JobVacancyStats:
    """Counts the biggest feed measured reports, before any override."""
    measured = sound_stats(
        MEASURED_RECORDS,
        teams_resolved=MEASURED_TEAMS_RESOLVED,
        with_league_position=MEASURED_WITH_LEAGUE_POSITION,
        flagged=MEASURED_FLAGGED,
    )
    if not overrides:
        return measured
    return sound_stats(
        MEASURED_RECORDS,
        teams_resolved=MEASURED_TEAMS_RESOLVED,
        with_league_position=MEASURED_WITH_LEAGUE_POSITION,
        flagged=MEASURED_FLAGGED,
        **overrides,
    )


def decode(
    save_path: Path,
    body: bytes | None = None,
    *,
    competition_names: Mapping[int, str] | None = None,
) -> tuple[tuple[JobVacancy, ...], JobVacancyStats]:
    """The vacancies of one job-centre body, joined through a save's own indexes."""
    with fmsave.open(save_path, competition_names=competition_names) as save:
        save.clubs()
        save.competitions()
        club_index = save._context.club_index()
        competition_index = save._context.competition_index()
        clock = save.info.game_date
        assert clock is not None
        if body is None:
            with save._context.section("job_centre") as job_centre:
                body = bytes(job_centre)
        return read_job_vacancies(body, club_index, competition_index, clock, LAYOUT, FILE_NAME)


def altered_records(position: int, **overrides: object) -> Sequence[bytes]:
    """The three example records with one of them rewritten."""
    fields: dict[str, object] = {
        "team_id": NORTHBRIDGE_TEAM_A,
        "role": 16,
        "advertised": packed_date(20, 2031, 33),
        "date_12": packed_date(40, 2031, 5),
        "competition_id": FIRST_COMPETITION_ID,
        "u20": 57,
        "league_position": 3,
        "flag": 0,
    }
    records = list(career_job_records())
    records[position] = job_record_bytes(**(fields | overrides))  # pyright: ignore[reportArgumentType]
    return records


def test_every_record_becomes_one_row_in_stored_order(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        vacancies = save.job_vacancies()

    assert len(vacancies) == 3
    assert [row.team_id for row in vacancies] == [
        NORTHBRIDGE_TEAM_A,
        70003,
        UNREGISTERED_FIXTURE_TEAM_ID,
    ]


def test_a_vacancy_at_a_club_the_save_lists_carries_its_club_and_its_league(
    career_path: Path,
) -> None:
    with fmsave.open(career_path) as save:
        row = save.job_vacancies()[0]

    assert row.team_id == NORTHBRIDGE_TEAM_A
    assert row.club_uid == NORTHBRIDGE_UID
    assert row.club_name == "Northbridge FC"
    assert row.team_slot == 0
    assert row.advertised_date == date(2031, 1, 20)
    assert row.competition_id == FIRST_COMPETITION_ID
    assert row.league_position == 3
    assert row.unknown == {
        "role": 16,
        "advertised_slot": 33,
        "date_12": FIRST_DATE_12,
        "u20": 57,
        "b24": 0,
    }


def test_a_vacancy_with_no_competition_has_no_league_position_either(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.job_vacancies()[1]

    assert row.club_uid == SOUTHPORT_UID
    assert row.competition_id is None
    assert row.competition_name is None
    assert row.league_position is None
    assert row.advertised_date == date(2031, 1, 30)
    assert row.unknown["b24"] == 1
    assert row.unknown["date_12"] == SECOND_DATE_12


def test_a_vacancy_at_a_team_no_club_lists_keeps_its_team_id_alone(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.job_vacancies()[2]

    assert row.team_id == UNREGISTERED_FIXTURE_TEAM_ID
    assert row.club_uid is None
    assert row.club_name is None
    assert row.team_slot is None
    assert row.competition_id == SECOND_COMPETITION_ID
    assert row.league_position == 12
    assert row.advertised_date == date(2031, 2, 14)


@pytest.mark.parametrize("stored_team_id", [0, MISSING_REFERENCE])
def test_a_record_naming_no_team_leaves_its_team_and_club_fields_empty(
    career_path: Path, stored_team_id: int
) -> None:
    """A stored 0 or the missing-reference word is no team, and never a team id of its own.

    No save measured stores either here, but every other reader that hands out a stored id
    reads them this way, and a feed that starts storing one must not have it handed out as a
    team the caller could look up. The rest of the record still decodes.
    """
    records = altered_records(0, team_id=stored_team_id)
    vacancies, stats = decode(career_path, job_centre_body(records))

    assert vacancies[0].team_id is None
    assert vacancies[0].club_uid is None
    assert vacancies[0].club_name is None
    assert vacancies[0].team_slot is None
    # The record is still a record: only its team went empty.
    assert vacancies[0].advertised_date == date(2031, 1, 20)
    assert vacancies[0].competition_id == FIRST_COMPETITION_ID
    assert len(vacancies) == len(records)
    # A sentinel resolved through no club before this mapping either, so the count is unmoved.
    assert stats.teams_resolved == 1


def test_a_competition_name_arrives_only_through_a_supplied_map(tmp_path: Path) -> None:
    save_path = career_fragment().write(tmp_path / "career.bin")

    with fmsave.open(save_path, competition_names=EXAMPLE_COMPETITION_NAMES) as named_save:
        named = named_save.job_vacancies()
    with fmsave.open(save_path) as plain_save:
        unnamed = plain_save.job_vacancies()

    assert [row.competition_name for row in named] == ["Example League", None, "Example Cup"]
    assert [row.competition_name for row in unnamed] == [None, None, None]


def test_the_stats_count_every_shape_the_feed_holds(career_path: Path) -> None:
    _rows, stats = decode(career_path)

    assert stats == JobVacancyStats(
        records=3,
        tagged=3,
        dates_ordered=3,
        advertised_steps=2,
        advertised_ascending_steps=2,
        reserved_zero=3,
        competitions_known=3,
        teams_resolved=2,
        with_competition=2,
        with_league_position=2,
        flagged=1,
    )


def test_a_section_whose_size_is_not_the_records_it_claims_names_its_section(
    career_path: Path,
) -> None:
    records = career_job_records()

    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(records, trailing_bytes=b"\x00"))
    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(records, stored_count=len(records) + 1))


def test_a_section_too_short_to_hold_a_count_names_its_section(career_path: Path) -> None:
    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(())[:10])


def test_a_record_that_fails_a_per_record_check_is_still_returned(career_path: Path) -> None:
    untagged = altered_records(0, tag=b"\x07\x00\x00")
    reserved = altered_records(0, reserved_u16=1)
    after_clock = altered_records(
        2, advertised=packed_date(90, 2031), date_12=packed_date(95, 2031)
    )

    _untagged_rows, untagged_stats = decode(career_path, job_centre_body(untagged))
    _reserved_rows, reserved_stats = decode(career_path, job_centre_body(reserved))
    after_clock_rows, after_clock_stats = decode(career_path, job_centre_body(after_clock))

    assert untagged_stats.records == 3
    assert untagged_stats.tagged == 2
    assert reserved_stats.records == 3
    assert reserved_stats.reserved_zero == 2
    assert len(after_clock_rows) == 3
    assert after_clock_stats.dates_ordered == 2


def test_an_empty_feed_is_an_empty_table_and_applies_no_gate(tmp_path: Path) -> None:
    empty = job_centre_body(())
    save_path = career_fragment(job_centre_section=empty).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        vacancies = save.job_vacancies()
    results = evaluate_job_vacancies(sound_stats(0), BOUNDS)

    assert len(vacancies) == 0
    assert [result.applied for result in results] == [False] * len(results)


def test_the_gates_apply_from_the_record_floor_and_not_below_it() -> None:
    below = evaluate_job_vacancies(sound_stats(MINIMUM_RECORDS - 1, tagged=0), BOUNDS)
    at_floor = evaluate_job_vacancies(sound_stats(MINIMUM_RECORDS, tagged=0), BOUNDS)

    assert [result.applied for result in below] == [False] * len(below)
    assert all(result.applied for result in at_floor)
    assert failed_gate_names(at_floor) == ["job_vacancy_tag"]


def test_a_record_start_shifted_by_a_field_fails_every_gate_it_moves() -> None:
    shifted = {
        "job_vacancy_tag": sound_stats(SHIFTED_RECORDS, tagged=SHIFTED_TAGGED),
        "job_vacancy_dates_ordered": sound_stats(SHIFTED_RECORDS, dates_ordered=0),
        "job_vacancy_advertised_ascending": sound_stats(
            SHIFTED_ASCENDING_RECORDS,
            advertised_steps=SHIFTED_ASCENDING_STEPS,
            advertised_ascending_steps=SHIFTED_ASCENDING_OK,
        ),
        "job_vacancy_reserved_zero": sound_stats(
            SHIFTED_RECORDS, reserved_zero=SHIFTED_RESERVED_ZERO
        ),
    }

    for gate_name, stats in shifted.items():
        assert failed_gate_names(evaluate_job_vacancies(stats, BOUNDS)) == [gate_name]
    assert failed_gate_names(evaluate_job_vacancies(healthy_stats(), BOUNDS)) == []


def test_a_feed_whose_advertised_dates_never_decode_fails_for_want_of_a_rate() -> None:
    no_steps = healthy_stats(advertised_steps=0, advertised_ascending_steps=0, dates_ordered=0)

    failures = failed_gate_names(evaluate_job_vacancies(no_steps, BOUNDS))

    assert "job_vacancy_advertised_ascending" in failures


def test_the_anomalies_count_what_the_joins_and_the_flags_left(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.job_vacancies()
        reader_check = save._reader_check(JOB_VACANCIES_READER)

    assert reader_check is not None
    assert reader_check.record_count == 3
    assert reader_check.anomalies == {
        "unresolved_teams": 1,
        "competitions_outside_the_competition_table": 0,
        "without_competition": 1,
        "without_league_position": 1,
        "flagged": 1,
    }


def test_the_columns_the_export_flattens() -> None:
    assert column_names(JobVacancy) == (
        "team_id",
        "club_uid",
        "club_name",
        "team_slot",
        "advertised_date",
        "competition_id",
        "competition_name",
        "league_position",
        "unknown_role",
        "unknown_advertised_slot",
        "unknown_date_12",
        "unknown_u20",
        "unknown_b24",
    )


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.job_vacancies()[0]

    # A round trip of fmsave's own record, not data from anywhere else.
    assert pickle.loads(pickle.dumps(row)) == row
    assert copy.deepcopy(row) == row


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first_table = save.job_vacancies()
        assert save.job_vacancies() is first_table

    with pytest.raises(SaveClosedError):
        save.job_vacancies()
