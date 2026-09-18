from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

import fmsave
import fmsave._save as save_module
from fmsave import ClubFacilities, CodedValue, CorporateFacilities, export
from fmsave._checks import evaluate_facilities
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import FacilityStats
from fmsave._save import FACILITIES_TABLE_CACHE_KEY
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.facilities import find_facility_layout, read_club_facilities
from fmsave.readers.finances import find_finance_layouts
from tests.fixtures.career import (
    ATHLETIC_FACILITY_BYTE,
    ATHLETIC_UID,
    BUILD_STRING,
    GAME_DB_SCHEMA,
    NORTHBRIDGE_FACILITY_BYTE,
    NORTHBRIDGE_UID,
    career_finance_rows,
)
from tests.fixtures.finances import club_finance_bytes
from tests.fixtures.game_db import club_record_bytes, game_db_body

FILE_NAME = "career example.fm"
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, BUILD_STRING).layout
FINANCE_LAYOUTS = find_finance_layouts(GAME_DB_SCHEMA, BUILD_STRING)
FACILITY_LAYOUT = find_facility_layout(GAME_DB_SCHEMA, BUILD_STRING)
FULL_SIZE_GAME_DB_BYTES = 100 * 1024 * 1024
EXAMPLE_CLUB_UID = 4001
# The fifteen ratings a club's own screen named, with the word it displayed for each.
NAMED_RATINGS = (
    (1, CorporateFacilities.BASIC),
    (2, CorporateFacilities.BASIC),
    (5, CorporateFacilities.FAIRLY_BASIC),
    (6, CorporateFacilities.ADEQUATE),
    (7, CorporateFacilities.ADEQUATE),
    (9, CorporateFacilities.ADEQUATE),
    (10, CorporateFacilities.AVERAGE),
    (11, CorporateFacilities.AVERAGE),
    (12, CorporateFacilities.AVERAGE),
    (13, CorporateFacilities.GOOD),
    (15, CorporateFacilities.GOOD),
    (17, CorporateFacilities.EXCELLENT),
    (18, CorporateFacilities.EXCELLENT),
    (19, CorporateFacilities.EXCELLENT),
    (20, CorporateFacilities.EXCELLENT),
)
# The two the clubs either side of them bracket: 8 between two Adequate clubs, 14 between two
# Good ones. Nothing else is filled in that way.
BRACKETED_RATINGS = (
    (8, CorporateFacilities.ADEQUATE),
    (14, CorporateFacilities.GOOD),
)
# The codes no club in the save carries, which no screen and no bracket names: 3 and 4 sit
# below the lowest word seen and 16 between a Good and an Excellent.
UNNAMED_RATINGS = (3, 4, 16)


def test_facilities_lists_every_club_with_a_series_in_club_index_order(
    career_save_path: Path,
) -> None:
    with fmsave.open(career_save_path) as career_save:
        facilities = tuple(career_save.facilities())
    assert [club.club_uid for club in facilities] == [NORTHBRIDGE_UID, ATHLETIC_UID]
    assert [club.club_name for club in facilities] == ["Northbridge FC", "Example Athletic"]
    assert facilities[0] == ClubFacilities(
        club_uid=NORTHBRIDGE_UID,
        club_name="Northbridge FC",
        corporate_facilities=CodedValue(
            label=CorporateFacilities.EXCELLENT, raw=NORTHBRIDGE_FACILITY_BYTE
        ),
    )
    assert facilities[1].corporate_facilities == CodedValue(
        label=CorporateFacilities.AVERAGE, raw=ATHLETIC_FACILITY_BYTE
    )


def one_club_game_db(facility_byte: int) -> bytes:
    """A game database of one club whose record carries a chain and one facilities rating."""
    record = club_record_bytes(
        club_index=1,
        uid=EXAMPLE_CLUB_UID,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Northbridge FC",
        short_name="Northbridge",
        team_ids=(70001,),
        trailing_bytes=club_finance_bytes(
            rows=career_finance_rows(), sponsors=(), facility_byte=facility_byte
        ),
    )
    return game_db_body([record], [], gap_bytes=256)


def one_club_facilities(facility_byte: int) -> tuple[tuple[ClubFacilities, ...], FacilityStats]:
    game_db = one_club_game_db(facility_byte)
    club_index = read_club_index(
        game_db, find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING), FILE_NAME
    )
    return read_club_facilities(
        game_db, club_index, FINANCE_LAYOUTS, FACILITY_LAYOUT, managed_club_exists=True
    )


@pytest.mark.parametrize(
    ("facility_byte", "expected_label"),
    NAMED_RATINGS,
    ids=[f"rating {facility_byte}" for facility_byte, _label in NAMED_RATINGS],
)
def test_a_named_rating_carries_the_word_its_screen_displayed(
    facility_byte: int, expected_label: CorporateFacilities
) -> None:
    rows, stats = one_club_facilities(facility_byte)
    (row,) = rows
    assert row.corporate_facilities.label is expected_label
    assert row.corporate_facilities.raw == facility_byte
    assert stats == FacilityStats(clubs_with_series=1, rows=1, in_range=1, managed_club_exists=True)


@pytest.mark.parametrize(
    ("facility_byte", "expected_label"),
    BRACKETED_RATINGS,
    ids=[f"rating {facility_byte}" for facility_byte, _label in BRACKETED_RATINGS],
)
def test_a_bracketed_rating_carries_the_word_its_neighbours_share(
    facility_byte: int, expected_label: CorporateFacilities
) -> None:
    """A code between two clubs displaying one word can only be that word on a rising scale."""
    rows, _stats = one_club_facilities(facility_byte)
    (row,) = rows
    below = CodedValue.from_raw(CorporateFacilities, facility_byte - 1)
    above = CodedValue.from_raw(CorporateFacilities, facility_byte + 1)
    assert below.label is expected_label
    assert above.label is expected_label
    assert row.corporate_facilities.label is expected_label
    assert row.corporate_facilities.raw == facility_byte


@pytest.mark.parametrize("facility_byte", UNNAMED_RATINGS)
def test_an_unnamed_rating_reads_unknown_and_keeps_its_number(facility_byte: int) -> None:
    """No club in the save carries these, so neither a screen nor a bracket names them."""
    rows, _stats = one_club_facilities(facility_byte)
    (row,) = rows
    assert row.corporate_facilities.label is CorporateFacilities.UNKNOWN
    assert row.corporate_facilities.raw == facility_byte


def test_a_rating_outside_the_range_is_returned_and_counted_out_of_range() -> None:
    rows, stats = one_club_facilities(0)
    (row,) = rows
    assert row.corporate_facilities.label is CorporateFacilities.UNKNOWN
    assert row.corporate_facilities.raw == 0
    assert stats == FacilityStats(clubs_with_series=1, rows=1, in_range=0, managed_club_exists=True)


def test_a_club_without_a_finance_chain_has_no_row() -> None:
    record = club_record_bytes(
        club_index=1,
        uid=EXAMPLE_CLUB_UID,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Northbridge FC",
        short_name="Northbridge",
        team_ids=(70001,),
        trailing_bytes=bytes(2_000),
    )
    game_db = game_db_body([record], [], gap_bytes=256)
    club_index = read_club_index(
        game_db, find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING), FILE_NAME
    )
    rows, stats = read_club_facilities(
        game_db, club_index, FINANCE_LAYOUTS, FACILITY_LAYOUT, managed_club_exists=True
    )
    assert rows == ()
    assert stats == FacilityStats(clubs_with_series=0, rows=0, in_range=0, managed_club_exists=True)


def test_the_record_exports_its_columns() -> None:
    assert export.column_names(ClubFacilities) == (
        "club_uid",
        "club_name",
        "corporate_facilities",
        "corporate_facilities_code",
    )


def test_the_table_survives_pickle_and_deepcopy(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        facilities = career_save.facilities()
    assert pickle.loads(pickle.dumps(facilities)) == facilities
    assert copy.deepcopy(facilities) == facilities
    assert pickle.loads(pickle.dumps(facilities[0])) == facilities[0]
    assert copy.deepcopy(facilities[0]) == facilities[0]


def test_the_table_is_decoded_once_and_a_closed_save_raises(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decodes: list[int] = []
    decode_facilities = save_module.read_club_facilities

    def counting_read_club_facilities(*arguments: object, **keyword_arguments: object) -> object:
        decodes.append(1)
        return decode_facilities(*arguments, **keyword_arguments)  # pyright: ignore[reportCallIssue, reportArgumentType]

    monkeypatch.setattr(save_module, "read_club_facilities", counting_read_club_facilities)
    career_save = fmsave.open(career_save_path)
    try:
        assert len(career_save.facilities()) == 2
        assert len(career_save.facilities()) == 2
        assert len(decodes) == 1
        assert career_save._context.cached_value(FACILITIES_TABLE_CACHE_KEY) is not None
    finally:
        career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.facilities()


# A club population invented here, so that no count in this file comes from a real save. It is
# round, which makes every share below an exact count of clubs.
CLUBS_WITH_A_SERIES = 1_000
IN_RANGE_FLOOR = 0.99


def facility_stats_at_share(in_range_share: float) -> FacilityStats:
    """An invented save where `in_range_share` of the clubs with a series read a rating in range."""
    return FacilityStats(
        clubs_with_series=CLUBS_WITH_A_SERIES,
        rows=CLUBS_WITH_A_SERIES,
        in_range=round(in_range_share * CLUBS_WITH_A_SERIES),
        managed_club_exists=True,
    )


def passing_facility_stats() -> FacilityStats:
    """Every club reads a rating in range, which is inside every bound."""
    return facility_stats_at_share(1.0)


def failed_gate_names(stats: FacilityStats) -> list[str]:
    gates = evaluate_facilities(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    return [gate.name for gate in gates if gate.applied and not gate.passed]


def test_a_sound_facility_shape_passes_every_facility_gate() -> None:
    assert failed_gate_names(passing_facility_stats()) == []


# The worst share each misalignment scores in the layout's own record of them: the rating read
# one byte early, one byte late, and four bytes late, which is the worst of the three. A share
# is a property of the format, so these are what the floor has to fail whatever save it runs on.
MISALIGNED_SHARES = (
    ("one byte early", 0.02),
    ("one byte late", 0.09),
    ("four bytes late", 0.63),
)


@pytest.mark.parametrize(
    ("shift", "in_range_share"),
    MISALIGNED_SHARES,
    ids=[shift for shift, _share in MISALIGNED_SHARES],
)
def test_a_rating_read_from_the_wrong_byte_fails_the_share(
    shift: str, in_range_share: float
) -> None:
    stats = facility_stats_at_share(in_range_share)
    assert failed_gate_names(stats) == ["facility_byte_in_range"]


def test_the_share_floor_passes_on_it_and_fails_one_club_below_it() -> None:
    """The floor itself is pinned, so a bound that moved cannot go unnoticed here."""
    on_the_floor = facility_stats_at_share(IN_RANGE_FLOOR)
    below_the_floor = dataclasses.replace(on_the_floor, in_range=on_the_floor.in_range - 1)

    assert failed_gate_names(on_the_floor) == []
    assert failed_gate_names(below_the_floor) == ["facility_byte_in_range"]


def test_no_club_with_a_series_fails_the_count_floor_on_a_managed_save() -> None:
    stats = FacilityStats(clubs_with_series=0, rows=0, in_range=0, managed_club_exists=True)
    assert failed_gate_names(stats) == ["facility_clubs_minimum"]
    applied_gates = [
        gate.name
        for gate in evaluate_facilities(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
        if gate.applied
    ]
    # The share has no denominator, so the count floor is the only check that applies.
    assert applied_gates == ["facility_clubs_minimum"]


def test_no_club_with_a_series_and_no_managed_club_fails_nothing() -> None:
    stats = FacilityStats(clubs_with_series=0, rows=0, in_range=0, managed_club_exists=False)
    gates = evaluate_facilities(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(stats) == []
    # This is the hole the reader's docstring names, the same one `finances()` carries.
    assert [gate.name for gate in gates if gate.applied] == []


def test_the_gates_stand_aside_on_a_fragment() -> None:
    fragment_game_db_bytes = 1024 * 1024
    gates = evaluate_facilities(passing_facility_stats(), BOUNDS, fragment_game_db_bytes)
    assert [gate.applied for gate in gates] == [False, False]
