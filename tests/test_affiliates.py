from __future__ import annotations

import copy
import pickle
from pathlib import Path

import pytest

import fmsave
from fmsave._checks import AFFILIATES_READER, GateResult, evaluate_affiliates
from fmsave._errors import ReaderCheckError, SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import AffiliateStats
from fmsave.export import column_names
from fmsave.models.affiliates import AffiliateGroup
from fmsave.readers._common import FEEDER_SECTION, GAME_DB_SECTION
from fmsave.readers.affiliates import (
    build_affiliate_groups,
    find_affiliate_layout,
    walk_affiliate_groups,
)
from fmsave.table import Table
from tests.fixtures.career import ATHLETIC_UID, NORTHBRIDGE_UID, SOUTHPORT_UID, career_fragment
from tests.fixtures.club_sections import feeder_body

GAME_DB_SCHEMA = 4000
FEEDER_SCHEMA = 5
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 100 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
MEMBERS_GATE_NAME = "affiliate_members_resolved"
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_affiliate_layout(FEEDER_SCHEMA, "")
FILE_NAME = "career.bin"
# The two example groups hold four members, of which one names no club the save lists.
CAREER_GROUPS = ((1, 2), (4, 9))
CAREER_MEMBERS = 4
CAREER_MEMBERS_RESOLVED = 3
# Every save measured resolves 419 of 426 members through the public club index, and 366
# through the index read one higher, which is the misalignment control.
MEASURED_MEMBERS = 426
MEASURED_MEMBERS_RESOLVED = 419
PLUS_ONE_MEMBERS_RESOLVED = 366
OVERSIZED_GROUP = tuple(range(1, LAYOUT.group_size_range[1] + 2))


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_stats(**overrides: int) -> AffiliateStats:
    """Counts as every save measured reports them, before any override."""
    fields = {
        "groups": 193,
        "members": MEASURED_MEMBERS,
        "members_resolved": MEASURED_MEMBERS_RESOLVED,
    }
    return AffiliateStats(**(fields | overrides))


def partners_of(groups: Table[AffiliateGroup], club_uid: int) -> tuple[int, ...]:
    """The derived partner view the `affiliates()` docstring shows, run on a table."""
    return tuple(
        member_uid
        for group in groups.filter(lambda group: club_uid in group.club_uids)
        for member_uid in group.club_uids
        if member_uid is not None and member_uid != club_uid
    )


def test_each_stored_group_is_one_row_with_its_members_resolved(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        groups = save.affiliates()

    assert len(groups) == 2
    assert groups[0].group_index == 0
    assert groups[0].club_uids == (NORTHBRIDGE_UID, SOUTHPORT_UID)
    assert groups[0].club_names == ("Northbridge FC", "Southport Example")
    assert groups[1].group_index == 1
    assert groups[1].club_uids == (ATHLETIC_UID, None)
    assert groups[1].club_names == ("Example Athletic", None)


def test_the_walk_and_the_join_count_every_member(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.clubs()
        club_index = save._context.club_index()
        with save._context.section(FEEDER_SECTION) as feeder:
            stored_groups = walk_affiliate_groups(feeder, LAYOUT, FILE_NAME)
        _rows, stats = build_affiliate_groups(stored_groups, club_index)

    assert stored_groups == CAREER_GROUPS
    assert stats == AffiliateStats(
        groups=2, members=CAREER_MEMBERS, members_resolved=CAREER_MEMBERS_RESOLVED
    )


def test_the_unresolved_members_are_reported_as_an_anomaly(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        save.affiliates()
        reader_check = save._reader_check(AFFILIATES_READER)

    assert reader_check is not None
    assert reader_check.record_count == 2
    assert reader_check.anomalies == {"unresolved_members": 1}


def test_a_clubs_partners_are_its_groups_members_without_itself(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        groups = save.affiliates()

    assert partners_of(groups, NORTHBRIDGE_UID) == (SOUTHPORT_UID,)
    assert partners_of(groups, ATHLETIC_UID) == ()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(feeder_body(CAREER_GROUPS) + b"\x00", id="one trailing byte"),
        pytest.param(feeder_body(CAREER_GROUPS, stored_count=3), id="a count of three over two"),
        pytest.param(feeder_body(CAREER_GROUPS)[:-4], id="a group that runs past the end"),
        pytest.param(feeder_body((OVERSIZED_GROUP,)), id="a group above the corruption cap"),
    ],
)
def test_a_body_the_walk_cannot_consume_exactly_names_its_section(body: bytes) -> None:
    with pytest.raises(ReaderCheckError, match="'feeder_man'"):
        walk_affiliate_groups(body, LAYOUT, FILE_NAME)


def test_a_header_read_one_byte_late_names_its_section() -> None:
    body = feeder_body(CAREER_GROUPS)
    shifted = body[:8] + b"\x00" + body[8:]

    with pytest.raises(ReaderCheckError, match="'feeder_man'"):
        walk_affiliate_groups(shifted, LAYOUT, FILE_NAME)


def test_a_section_too_short_to_hold_a_header_names_its_section() -> None:
    with pytest.raises(ReaderCheckError, match="'feeder_man'"):
        walk_affiliate_groups(feeder_body(())[:12], LAYOUT, FILE_NAME)


def test_a_section_with_no_group_and_no_residue_is_an_empty_table(tmp_path: Path) -> None:
    empty = feeder_body(())
    save_path = career_fragment(feeder_section=empty).write(tmp_path / "career.bin")

    assert walk_affiliate_groups(empty, LAYOUT, FILE_NAME) == ()
    with fmsave.open(save_path) as save:
        assert len(save.affiliates()) == 0


def test_the_columns_the_export_flattens() -> None:
    assert column_names(AffiliateGroup) == ("group_index", "club_uids", "club_names")


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.affiliates()[0]

    # A round trip of fmsave's own record, not data from anywhere else.
    assert pickle.loads(pickle.dumps(row)) == row
    assert copy.deepcopy(row) == row


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first_table = save.affiliates()
        assert save.affiliates() is first_table

    with pytest.raises(SaveClosedError):
        save.affiliates()


def test_an_index_read_one_higher_fails_the_gate_and_the_stored_index_passes() -> None:
    failing = evaluate_affiliates(
        healthy_stats(members_resolved=PLUS_ONE_MEMBERS_RESOLVED), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    passing = evaluate_affiliates(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(failing) == [MEMBERS_GATE_NAME]
    assert failed_gate_names(passing) == []


def test_the_gate_does_not_apply_on_a_small_game_db_or_without_a_member() -> None:
    small_game_db = evaluate_affiliates(
        healthy_stats(members_resolved=PLUS_ONE_MEMBERS_RESOLVED), BOUNDS, SMALL_GAME_DB_BYTES
    )
    no_members = evaluate_affiliates(
        healthy_stats(groups=0, members=0, members_resolved=0), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )

    assert [result.applied for result in small_game_db] == [False]
    assert [result.applied for result in no_members] == [False]
