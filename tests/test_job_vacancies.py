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
        relative_dates_ordered=3,
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


def test_a_record_storing_an_id_list_is_walked_past_its_ids(career_path: Path) -> None:
    """A record can store a count byte and that many u32 ids in front of its later fields.

    Each record is sized by its own count, so neither the record carrying the ids nor any
    record after it moves, and the section still ends exactly where the last record does.
    """
    ids = (90001, 90002, 90003, 90004, 90005, 90006, 90007, 90008, 90009, 90010)
    with_ids = altered_records(0, ids=ids, b17=1)
    first_two_with_ids = [with_ids[0], altered_records(1, ids=ids[:8], b17=1)[1], with_ids[2]]

    plain_rows, plain_stats = decode(career_path, job_centre_body(career_job_records()))
    for records in (with_ids, first_two_with_ids):
        rows, stats = decode(career_path, job_centre_body(records))

        assert len(rows) == len(records)
        assert rows[0].team_id == NORTHBRIDGE_TEAM_A
        assert rows[0].competition_id == FIRST_COMPETITION_ID
        assert rows[0].league_position == 3
        assert rows[0].unknown["u20"] == 57
        assert rows[2] == plain_rows[2]
        assert stats.reserved_zero == stats.tagged == stats.records == 3
    assert plain_stats.reserved_zero == 3


def test_an_id_count_the_record_does_not_hold_breaks_the_size_identity(
    career_path: Path,
) -> None:
    records = list(career_job_records())
    records[0] = altered_records(0, ids=(90001, 90002))[0]
    claims_three = bytearray(records[0])
    claims_three[16] = 3
    records[0] = bytes(claims_three)

    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(records))
    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(records[:1]))


def test_a_section_too_short_to_hold_a_count_names_its_section(career_path: Path) -> None:
    with pytest.raises(ReaderCheckError, match="'job_centre'"):
        decode(career_path, job_centre_body(())[:10])


def test_a_record_that_fails_a_per_record_check_is_still_returned(career_path: Path) -> None:
    untagged = altered_records(0, tag=b"\x07\x00\x00")
    reserved = altered_records(0, b17=2)
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


@pytest.fixture
def missing_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from tests.fixtures import career
    from tests.fixtures.container import default_sections, game_info_body

    sections = [
        replace(section, body=game_info_body(game_day_of_year=0))
        if section.name == "game_info"
        else section
        for section in default_sections()
    ]
    monkeypatch.setattr(career, "default_sections", lambda: sections)


@pytest.mark.parametrize("strict", [False, True])
def test_missing_clock_returns_vacancies_with_unavailable_check_warning(
    tmp_path: Path, missing_clock: None, strict: bool
) -> None:
    path = career_fragment().write(tmp_path / "career.bin")
    with fmsave.open(path, strict=strict) as save:
        assert save.info.game_date is None
        with pytest.warns(fmsave.ReaderCheckWarning, match="clock.*unavailable"):
            rows = save.job_vacancies()
        assert len(rows) == 3
        assert rows[0].advertised_date == date(2031, 1, 20)
        check = save._reader_check(JOB_VACANCIES_READER)
        assert check is not None
        gate = next(gate for gate in check.gates if gate.name == "job_vacancy_dates_ordered")
        assert not gate.applied
        assert gate.observed is None


@pytest.mark.parametrize("strict", [False, True])
def test_missing_clock_does_not_excuse_malformed_job_section(
    tmp_path: Path, missing_clock: None, strict: bool
) -> None:
    path = career_fragment(job_centre_section=job_centre_body((), stored_count=1)).write(
        tmp_path / "career.bin"
    )
    with (
        fmsave.open(path, strict=strict) as save,
        pytest.raises(ReaderCheckError, match="job_centre"),
    ):
        save.job_vacancies()


@pytest.mark.parametrize("strict", [False, True])
def test_missing_clock_preserves_relative_date_validation(
    tmp_path: Path, missing_clock: None, strict: bool
) -> None:
    records = [altered_records(0, date_12=packed_date(10, 2031))[0]] * MINIMUM_RECORDS
    path = career_fragment(job_centre_section=job_centre_body(records)).write(
        tmp_path / "career.bin"
    )
    failure = (
        pytest.raises(ReaderCheckError, match="job_vacancy_relative_dates_ordered")
        if strict
        else pytest.warns(fmsave.ReaderCheckWarning, match="job_vacancy_relative_dates_ordered")
    )
    with (
        fmsave.open(path, strict=strict) as save,
        pytest.warns(fmsave.ReaderCheckWarning, match="clock.*unavailable"),
        failure,
    ):
        save.job_vacancies()


def test_future_advertisements_return_rows_in_strict_mode(tmp_path: Path) -> None:
    records = [
        altered_records(0, advertised=packed_date(90, 2031), date_12=packed_date(95, 2031))[0]
    ] * MINIMUM_RECORDS
    path = career_fragment(job_centre_section=job_centre_body(records)).write(
        tmp_path / "career.bin"
    )
    with (
        fmsave.open(path, strict=True) as save,
        pytest.warns(fmsave.ReaderCheckWarning, match="job_vacancy_dates_ordered"),
    ):
        rows = save.job_vacancies()
    assert len(rows) == MINIMUM_RECORDS
    assert rows[0].advertised_date == date(2031, 3, 31)


def test_readable_clock_preserves_relative_date_validation(tmp_path: Path) -> None:
    records = [altered_records(0, date_12=packed_date(10, 2031))[0]] * MINIMUM_RECORDS
    path = career_fragment(job_centre_section=job_centre_body(records)).write(
        tmp_path / "career.bin"
    )
    with (
        fmsave.open(path, strict=True) as save,
        pytest.raises(ReaderCheckError, match="job_vacancy_relative_dates_ordered"),
    ):
        save.job_vacancies()
