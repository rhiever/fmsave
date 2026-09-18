from __future__ import annotations

import copy
import dataclasses
import pickle
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import fmsave
import fmsave._context as context_module
from fmsave import Club, Team, export
from fmsave._container import ContainerIndex
from fmsave._context import CLUB_INDEX_CACHE_KEY
from fmsave._errors import ReaderCheckError
from fmsave._layouts import ClubRecordLayout, ClubStatusLayout, TeamListLayout, find_layout
from fmsave._save import CLUBS_TABLE_CACHE_KEY
from fmsave.readers.clubs import ClubIndex, ClubLayouts, find_club_layouts, read_club_index
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    section_body,
)
from tests.fixtures.game_db import (
    NORMAL_STATUS_KIND,
    NULL_DATE,
    STATUS_RECORD_BYTES,
    STATUS_UID_AT,
    STUB_STATUS_KIND,
    club_record_bytes,
    club_record_names_end,
    game_db_body,
    status_record_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000


@dataclass(frozen=True)
class ExampleClubSpec:
    club_index: int
    uid: int
    name: str
    short_name: str
    nation_id: int
    fa_nation_id: int
    city_id: int
    team_ids: tuple[int, ...]
    affiliate_team_ids: tuple[int, ...] = ()
    float_anchor_only: bool = False

    def record_bytes(self) -> bytes:
        return club_record_bytes(
            club_index=self.club_index,
            uid=self.uid,
            nation_id=self.nation_id,
            fa_nation_id=self.fa_nation_id,
            city_id=self.city_id,
            name=self.name,
            short_name=self.short_name,
            team_ids=self.team_ids,
            affiliate_team_ids=self.affiliate_team_ids,
            float_anchor_only=self.float_anchor_only,
        )

    def names_end(self) -> int:
        return club_record_names_end(self.name, self.short_name)


NORTHBRIDGE = ExampleClubSpec(1, 5001, "Northbridge FC", "Northbridge", 3, 3, 77, (70001, 70002))
SOUTHPORT = ExampleClubSpec(
    2, 5002, "Southport Example", "Southport", 3, 4, 78, (70003,), float_anchor_only=True
)
ATHLETIC = ExampleClubSpec(4, 5004, "Example Athletic", "Athletic", 9, 9, 79, (70005, 70004, 70006))
ROVERS = ExampleClubSpec(3, 5003, "Example Rovers", "Rovers", 5, 5, 80, (70009,))
EXAMPLE_CLUBS = (NORTHBRIDGE, SOUTHPORT, ATHLETIC)
FICTIONAL_NAMES = (
    "Northbridge FC",
    "Northbridge",
    "Southport Example",
    "Southport",
    "Example Athletic",
    "Athletic",
)


def example_status_records(
    ordinals: tuple[int, int, int] = (51, 52, 53),
    *,
    northbridge_reputation: int = 6500,
) -> list[bytes]:
    return [
        status_record_bytes(
            ordinal=ordinals[0],
            club_index=1,
            uid=5001,
            kind=NORMAL_STATUS_KIND,
            last_league_position=2,
            reputation=northbridge_reputation,
        ),
        status_record_bytes(
            ordinal=ordinals[1],
            club_index=2,
            uid=5002,
            kind=STUB_STATUS_KIND,
            last_league_position=5,
            reputation=3000,
        ),
        status_record_bytes(
            ordinal=ordinals[2],
            club_index=4,
            uid=5004,
            kind=NORMAL_STATUS_KIND,
            last_league_position=14,
            reputation=1200,
        ),
    ]


def example_game_db(
    club_records: Sequence[bytes] | None = None,
    status_records: Sequence[bytes] | None = None,
) -> bytes:
    chosen_club_records = (
        [club.record_bytes() for club in EXAMPLE_CLUBS] if club_records is None else club_records
    )
    chosen_status_records = example_status_records() if status_records is None else status_records
    body = game_db_body(chosen_club_records, chosen_status_records)
    return section_body(".dat", GAME_DB_SCHEMA, body)


def registered_club_layouts() -> ClubLayouts:
    return find_club_layouts(GAME_DB_SCHEMA, "")


def read_index(game_db: bytes) -> ClubIndex:
    return read_club_index(game_db, registered_club_layouts(), FILE_NAME)


def club_uids(club_index: ClubIndex) -> list[int]:
    return [club.uid for club in club_index.clubs]


def test_reads_every_club_with_its_fields() -> None:
    club_index = read_index(example_game_db())
    assert club_uids(club_index) == [5001, 5002, 5004]
    assert club_index.clubs[0] == Club(
        uid=5001,
        name="Northbridge FC",
        short_name="Northbridge",
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        teams=(
            Team(team_id=70001, slot=0, club_uid=5001, is_affiliate=False),
            Team(team_id=70002, slot=1, club_uid=5001, is_affiliate=False),
        ),
        parent_club_uid=None,
        parent_club_name=None,
        reputation=6500,
        last_league_position=2,
    )


def test_cross_border_stub_club_has_no_reputation() -> None:
    southport = read_index(example_game_db()).club_by_uid[5002]
    assert southport.name == "Southport Example"
    assert southport.short_name == "Southport"
    assert southport.nation_id == 3
    assert southport.fa_nation_id == 4
    assert southport.city_id == 78
    assert southport.reputation is None
    assert southport.last_league_position is None
    assert southport.teams == (Team(70003, 0, 5002, False),)


def test_team_ids_keep_their_stored_order() -> None:
    athletic = read_index(example_game_db()).club_by_uid[5004]
    assert athletic.teams == (
        Team(70005, 0, 5004, False),
        Team(70004, 1, 5004, False),
        Team(70006, 2, 5004, False),
    )
    assert athletic.reputation == 1200
    assert athletic.last_league_position == 14


def test_city_id_stored_as_the_missing_id_is_none() -> None:
    no_city_club = replace(SOUTHPORT, city_id=0xFFFFFFFF)
    zero_city_club = replace(ATHLETIC, city_id=0)
    club_records = [
        NORTHBRIDGE.record_bytes(),
        no_city_club.record_bytes(),
        zero_city_club.record_bytes(),
    ]
    club_index = read_index(example_game_db(club_records))
    assert club_uids(club_index) == [5001, 5002, 5004]
    assert club_index.club_by_uid[5002].city_id is None
    assert club_index.club_by_uid[5002].teams == (Team(70003, 0, 5002, False),)
    assert club_index.club_by_uid[5004].city_id == 0
    assert club_index.club_by_uid[5001].city_id == 77


def test_index_maps_club_indexes_uids_and_teams() -> None:
    club_index = read_index(example_game_db())
    assert club_index.team_to_club[70003] == (5002, 0)
    assert club_index.team_to_club[70004] == (5004, 1)
    assert club_index.uid_by_club_index[4] == 5004
    assert dict(club_index.uid_by_club_index) == {1: 5001, 2: 5002, 4: 5004}
    assert club_index.club_by_uid[5001] is club_index.clubs[0]
    assert len(club_index.team_to_club) == 6
    assert isinstance(club_index.clubs, tuple)


def test_non_ascii_names_round_trip() -> None:
    lodz_club = replace(NORTHBRIDGE, name="Łódź Example", short_name="Łódź")
    tokyo_club = replace(ATHLETIC, name="東京 Example FC", short_name="東京")
    club_records = [lodz_club.record_bytes(), SOUTHPORT.record_bytes(), tokyo_club.record_bytes()]
    club_index = read_index(example_game_db(club_records))
    assert club_index.club_by_uid[5001].name == "Łódź Example"
    assert club_index.club_by_uid[5001].short_name == "Łódź"
    assert club_index.club_by_uid[5004].name == "東京 Example FC"
    assert club_index.club_by_uid[5004].short_name == "東京"
    assert club_index.club_by_uid[5004].reputation == 1200


def records_with_rovers_after_northbridge(rovers_record: bytes) -> list[bytes]:
    return [
        NORTHBRIDGE.record_bytes(),
        rovers_record,
        SOUTHPORT.record_bytes(),
        ATHLETIC.record_bytes(),
    ]


def test_valid_rovers_record_is_accepted_and_clubs_follow_club_index_order() -> None:
    club_index = read_index(
        example_game_db(records_with_rovers_after_northbridge(ROVERS.record_bytes()))
    )
    assert club_uids(club_index) == [5001, 5002, 5003, 5004]
    assert dict(club_index.uid_by_club_index) == {1: 5001, 2: 5002, 3: 5003, 4: 5004}
    assert club_index.team_to_club[70009] == (5003, 0)
    assert club_index.club_by_uid[5001].teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
    )
    assert club_index.club_by_uid[5004].reputation == 1200


def test_club_with_fa_nation_zero_is_not_accepted() -> None:
    rovers_record = replace(ROVERS, fa_nation_id=0).record_bytes()
    club_index = read_index(example_game_db(records_with_rovers_after_northbridge(rovers_record)))
    assert club_uids(club_index) == [5001, 5002, 5004]
    assert 70009 not in club_index.team_to_club


def patched(record: bytes, offset: int, replacement: bytes) -> bytes:
    return record[:offset] + replacement + record[offset + len(replacement) :]


ROVERS_LONG_NAME_TEXT_AT = 39 + 4
ROVERS_SHORT_NAME_TEXT_AT = 39 + 4 + len("Example Rovers") + 4


@pytest.mark.parametrize(
    ("offset", "replacement"),
    [
        pytest.param(12, b"\x01", id="nonzero byte before the league nation"),
        pytest.param(13, (1000).to_bytes(4, "little"), id="league nation above 999"),
        pytest.param(13, (0).to_bytes(4, "little"), id="league nation zero"),
        pytest.param(25, (6).to_bytes(4, "little"), id="league nation copy differs"),
        pytest.param(21, (1000).to_bytes(4, "little"), id="fa nation above 999"),
        pytest.param(8, (1).to_bytes(4, "little"), id="uid copy differs"),
        pytest.param(39, (0).to_bytes(4, "little"), id="empty long name"),
        pytest.param(39, (65).to_bytes(4, "little"), id="long name above 64 bytes"),
        pytest.param(ROVERS_LONG_NAME_TEXT_AT + 1, b"\xff", id="invalid utf-8 long name"),
        pytest.param(ROVERS_SHORT_NAME_TEXT_AT + 1, b"\xc3", id="invalid utf-8 short name"),
        pytest.param(
            ROVERS_SHORT_NAME_TEXT_AT - 4, (0).to_bytes(4, "little"), id="empty short name"
        ),
    ],
)
def test_club_failing_a_check_is_not_accepted(offset: int, replacement: bytes) -> None:
    rovers_record = patched(ROVERS.record_bytes(), offset, replacement)
    club_index = read_index(example_game_db(records_with_rovers_after_northbridge(rovers_record)))
    assert club_uids(club_index) == [5001, 5002, 5004]
    assert club_index.club_by_uid[5001].teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
    )


def test_club_after_a_gap_of_more_than_64_kib_is_not_accepted() -> None:
    fifth_club = ExampleClubSpec(5, 5005, "Example Wanderers", "Wanderers", 3, 3, 81, (70007,))
    club_records = [club.record_bytes() for club in EXAMPLE_CLUBS]
    club_records.append(bytes(70_000) + fifth_club.record_bytes())
    club_index = read_index(example_game_db(club_records))
    assert club_uids(club_index) == [5001, 5002, 5004]
    assert 70007 not in club_index.team_to_club
    assert club_index.club_by_uid[5004].reputation == 1200


def test_club_after_a_gap_below_64_kib_is_accepted() -> None:
    fifth_club = ExampleClubSpec(5, 5005, "Example Wanderers", "Wanderers", 3, 3, 81, (70007,))
    club_records = [club.record_bytes() for club in EXAMPLE_CLUBS]
    club_records.append(bytes(60_000) + fifth_club.record_bytes())
    club_index = read_index(example_game_db(club_records))
    assert club_uids(club_index) == [5001, 5002, 5004, 5005]
    assert club_index.team_to_club[70007] == (5005, 0)


@pytest.mark.parametrize(
    ("start_distance", "expected_uids"),
    [
        (65_536, [5001, 5002, 5004]),
        (65_535, [5001, 5002, 5004, 5005]),
    ],
)
def test_scan_stops_at_a_candidate_exactly_64_kib_past_the_last_record(
    start_distance: int, expected_uids: list[int]
) -> None:
    fifth_club = ExampleClubSpec(5, 5005, "Example Wanderers", "Wanderers", 3, 3, 81, (70007,))
    club_records = [club.record_bytes() for club in EXAMPLE_CLUBS]
    padding_bytes = start_distance - len(club_records[-1])
    club_records.append(bytes(padding_bytes) + fifth_club.record_bytes())
    club_index = read_index(example_game_db(club_records))
    assert club_uids(club_index) == expected_uids


def test_last_club_team_list_is_found_beyond_20000_bytes() -> None:
    athletic_record = ATHLETIC.record_bytes()
    names_end = ATHLETIC.names_end()
    long_athletic_record = athletic_record[:names_end] + bytes(25_000) + athletic_record[names_end:]
    club_records = [NORTHBRIDGE.record_bytes(), SOUTHPORT.record_bytes(), long_athletic_record]
    athletic = read_index(example_game_db(club_records)).club_by_uid[5004]
    assert athletic.teams == (
        Team(70005, 0, 5004, False),
        Team(70004, 1, 5004, False),
        Team(70006, 2, 5004, False),
    )


def test_last_club_team_list_past_the_scan_stop_is_not_read() -> None:
    athletic_record = ATHLETIC.record_bytes()
    names_end = ATHLETIC.names_end()
    far_athletic_record = athletic_record[:names_end] + bytes(70_000) + athletic_record[names_end:]
    club_records = [NORTHBRIDGE.record_bytes(), SOUTHPORT.record_bytes(), far_athletic_record]
    club_index = read_index(example_game_db(club_records))
    assert club_index.club_by_uid[5004].teams == ()
    assert club_index.club_by_uid[5004].name == "Example Athletic"


def test_team_list_that_does_not_parse_gives_no_teams() -> None:
    no_team_club = replace(ATHLETIC, team_ids=())
    out_of_range_club = replace(SOUTHPORT, team_ids=(3_000_001,))
    nine_team_club = replace(NORTHBRIDGE, team_ids=tuple(range(70001, 70010)))
    club_records = [
        nine_team_club.record_bytes(),
        out_of_range_club.record_bytes(),
        no_team_club.record_bytes(),
    ]
    club_index = read_index(example_game_db(club_records))
    assert [club.teams for club in club_index.clubs] == [(), (), ()]
    assert len(club_index.team_to_club) == 0


def test_team_ids_at_the_range_limits_are_read() -> None:
    edge_club = replace(ATHLETIC, team_ids=(1, 3_000_000))
    club_records = [NORTHBRIDGE.record_bytes(), SOUTHPORT.record_bytes(), edge_club.record_bytes()]
    athletic = read_index(example_game_db(club_records)).club_by_uid[5004]
    assert athletic.teams == (Team(1, 0, 5004, False), Team(3_000_000, 1, 5004, False))


def test_team_list_cut_off_by_the_section_end_gives_no_teams() -> None:
    truncated_record = ATHLETIC.record_bytes()[:-2]
    game_db = section_body(".dat", GAME_DB_SCHEMA, bytes(64) + truncated_record)
    club_index = read_index(game_db)
    assert club_uids(club_index) == [5004]
    assert club_index.clubs[0].teams == ()
    assert club_index.clubs[0].reputation is None


def test_float_anchor_is_tried_when_the_first_date_triple_does_not_parse() -> None:
    athletic_record = ATHLETIC.record_bytes()
    decoy_record = patched(athletic_record, ATHLETIC.names_end(), NULL_DATE * 3)
    club_records = [NORTHBRIDGE.record_bytes(), SOUTHPORT.record_bytes(), decoy_record]
    athletic = read_index(example_game_db(club_records)).club_by_uid[5004]
    assert athletic.teams == (
        Team(70005, 0, 5004, False),
        Team(70004, 1, 5004, False),
        Team(70006, 2, 5004, False),
    )


ACADEMY = ExampleClubSpec(5, 5005, "Example Academy", "Academy", 3, 3, 81, (70011,))
ACADEMY_TEAM_ID = 70011


def index_with_affiliate(
    affiliate_team_ids: tuple[int, ...] = (ACADEMY_TEAM_ID,),
    *,
    also_listed_by_athletic: tuple[int, ...] = (),
) -> ClubIndex:
    """Northbridge controls `affiliate_team_ids`; Academy (uid 5005) fields team 70011."""
    club_records = [
        replace(NORTHBRIDGE, affiliate_team_ids=affiliate_team_ids).record_bytes(),
        SOUTHPORT.record_bytes(),
        replace(ATHLETIC, affiliate_team_ids=also_listed_by_athletic).record_bytes(),
        ACADEMY.record_bytes(),
    ]
    return read_index(example_game_db(club_records))


def test_affiliate_teams_follow_the_clubs_own_slots() -> None:
    club_index = index_with_affiliate()
    parent = club_index.club_by_uid[5001]
    # Every own slot is listed, including the second one no player is registered with, and
    # the affiliate team takes the next slot.
    assert parent.teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
        Team(ACADEMY_TEAM_ID, 2, 5005, True),
    )
    assert parent.parent_club_uid is None
    assert parent.parent_club_name is None


def test_an_affiliate_club_keeps_its_row_its_own_slots_and_names_its_parent() -> None:
    academy = index_with_affiliate().club_by_uid[5005]
    assert academy.name == "Example Academy"
    assert academy.teams == (Team(ACADEMY_TEAM_ID, 0, 5005, False),)
    assert academy.parent_club_uid == 5001
    assert academy.parent_club_name == "Northbridge FC"


def test_an_affiliate_team_keeps_its_stored_club_and_gains_a_fielding_club() -> None:
    club_index = index_with_affiliate()
    assert club_index.team_to_club[ACADEMY_TEAM_ID] == (5005, 0)
    assert club_index.affiliate_team_to_club[ACADEMY_TEAM_ID] == (5001, 2)
    assert 70001 not in club_index.affiliate_team_to_club
    assert club_index.stats.affiliate_lists == 1
    assert club_index.stats.affiliate_refs == 1
    assert club_index.stats.affiliate_refs_linked == 1


@pytest.mark.parametrize(
    "affiliate_team_ids",
    [
        pytest.param((79999,), id="team of no club"),
        pytest.param((70002,), id="the club's own team"),
    ],
)
def test_an_affiliate_id_that_does_not_resolve_is_left_out(
    affiliate_team_ids: tuple[int, ...],
) -> None:
    club_index = index_with_affiliate(affiliate_team_ids)
    assert club_index.club_by_uid[5001].teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
    )
    assert club_index.club_by_uid[5005].parent_club_uid is None
    assert club_index.affiliate_team_to_club == {}
    # The list is still counted, so the club checks see the id it lost.
    assert club_index.stats.affiliate_lists == 1
    assert club_index.stats.affiliate_refs == 1
    assert club_index.stats.affiliate_refs_linked == 0


@pytest.mark.parametrize(
    "affiliate_team_ids",
    [
        pytest.param((ACADEMY_TEAM_ID, 79999), id="the id that resolves comes first"),
        pytest.param((79999, ACADEMY_TEAM_ID), id="the id that resolves comes second"),
    ],
)
def test_an_id_that_does_not_resolve_does_not_cost_the_rest_of_its_list(
    affiliate_team_ids: tuple[int, ...],
) -> None:
    club_index = index_with_affiliate(affiliate_team_ids)
    assert club_index.club_by_uid[5001].teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
        Team(ACADEMY_TEAM_ID, 2, 5005, True),
    )
    assert club_index.club_by_uid[5005].parent_club_uid == 5001
    assert club_index.affiliate_team_to_club[ACADEMY_TEAM_ID] == (5001, 2)
    assert club_index.stats.affiliate_lists == 1
    assert club_index.stats.affiliate_refs == 2
    assert club_index.stats.affiliate_refs_linked == 1


def test_a_team_two_clubs_list_keeps_only_the_first_parent() -> None:
    club_index = index_with_affiliate(also_listed_by_athletic=(ACADEMY_TEAM_ID,))
    assert club_index.club_by_uid[5005].parent_club_uid == 5001
    assert club_index.affiliate_team_to_club[ACADEMY_TEAM_ID] == (5001, 2)
    assert [team.team_id for team in club_index.club_by_uid[5004].teams] == [70005, 70004, 70006]
    assert club_index.stats.affiliate_refs == 2
    assert club_index.stats.affiliate_refs_linked == 1


def test_an_affiliate_count_above_the_range_leaves_the_list_unread() -> None:
    lowest_count, highest_count = registered_club_layouts().team_lists.affiliate_count_range
    assert (lowest_count, highest_count) == (0, 8)
    too_many_ids = tuple(range(ACADEMY_TEAM_ID, ACADEMY_TEAM_ID + highest_count + 1))
    club_index = index_with_affiliate(too_many_ids)
    assert club_index.club_by_uid[5001].teams == (
        Team(70001, 0, 5001, False),
        Team(70002, 1, 5001, False),
    )
    assert club_index.stats.affiliate_lists == 0
    assert club_index.stats.affiliate_refs == 0


def test_team_claimed_by_two_clubs_raises_reader_check() -> None:
    clashing_southport = replace(SOUTHPORT, team_ids=(70001,))
    club_records = [
        NORTHBRIDGE.record_bytes(),
        clashing_southport.record_bytes(),
        ATHLETIC.record_bytes(),
    ]
    with pytest.raises(ReaderCheckError) as error_info:
        read_index(example_game_db(club_records))
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message
    for fictional_name in FICTIONAL_NAMES:
        assert fictional_name not in message


@pytest.mark.parametrize(
    ("changed_southport", "expected_detail"),
    [
        pytest.param(replace(SOUTHPORT, uid=5001), "club uid 5001 ", id="uid twice"),
        pytest.param(replace(SOUTHPORT, club_index=1), "club index 1 ", id="club index twice"),
    ],
)
def test_repeated_club_uid_or_index_raises_reader_check(
    changed_southport: ExampleClubSpec, expected_detail: str
) -> None:
    club_records = [
        NORTHBRIDGE.record_bytes(),
        changed_southport.record_bytes(),
        ATHLETIC.record_bytes(),
    ]
    with pytest.raises(ReaderCheckError) as error_info:
        read_index(example_game_db(club_records))
    message = str(error_info.value)
    assert expected_detail in message
    assert FILE_NAME in message
    assert "game_db" in message


def test_team_listed_twice_by_one_club_raises_reader_check() -> None:
    repeating_athletic = replace(ATHLETIC, team_ids=(70005, 70004, 70005))
    club_records = [
        NORTHBRIDGE.record_bytes(),
        SOUTHPORT.record_bytes(),
        repeating_athletic.record_bytes(),
    ]
    with pytest.raises(ReaderCheckError, match="team id 70005 is listed twice") as error_info:
        read_index(example_game_db(club_records))
    assert FILE_NAME in str(error_info.value)
    assert "game_db" in str(error_info.value)


def test_game_db_without_club_records_raises_reader_check() -> None:
    game_db = section_body(".dat", GAME_DB_SCHEMA, bytes(4096) + b"\xff" * 64 + bytes(128))
    with pytest.raises(ReaderCheckError) as error_info:
        read_index(game_db)
    assert FILE_NAME in str(error_info.value)
    assert "game_db" in str(error_info.value)


@pytest.mark.parametrize("athletic_ordinal", [40, 52])
def test_status_ordinal_not_above_the_previous_one_is_skipped(athletic_ordinal: int) -> None:
    status_records = example_status_records((51, 52, athletic_ordinal))
    club_index = read_index(example_game_db(status_records=status_records))
    assert club_index.club_by_uid[5004].reputation is None
    assert club_index.club_by_uid[5004].last_league_position is None
    assert club_index.club_by_uid[5001].reputation == 6500


def test_status_ordinal_at_the_limit_is_skipped() -> None:
    status_records = example_status_records((51, 52, 200_000))
    club_index = read_index(example_game_db(status_records=status_records))
    assert club_index.club_by_uid[5004].reputation is None
    assert club_index.club_by_uid[5004].last_league_position is None


def test_status_ordinal_just_below_the_limit_is_read() -> None:
    status_records = example_status_records((51, 52, 199_999))
    club_index = read_index(example_game_db(status_records=status_records))
    assert club_index.club_by_uid[5004].reputation == 1200


@pytest.mark.parametrize(
    ("stored_reputation", "expected_reputation"),
    [(0, None), (10_001, None), (1, 1), (10_000, 10_000)],
)
def test_reputation_outside_its_range_is_none(
    stored_reputation: int, expected_reputation: int | None
) -> None:
    status_records = example_status_records(northbridge_reputation=stored_reputation)
    northbridge = read_index(example_game_db(status_records=status_records)).club_by_uid[5001]
    assert northbridge.reputation == expected_reputation
    assert northbridge.last_league_position == 2


def test_club_without_a_status_record_has_no_status() -> None:
    status_records = example_status_records()[:2]
    club_index = read_index(example_game_db(status_records=status_records))
    assert club_index.club_by_uid[5004].reputation is None
    assert club_index.club_by_uid[5004].last_league_position is None
    assert club_index.club_by_uid[5001].last_league_position == 2


def test_status_record_with_another_kind_is_skipped() -> None:
    status_records = example_status_records()
    status_records[0] = patched(status_records[0], 18 + 8, b"\x0c")
    northbridge = read_index(example_game_db(status_records=status_records)).club_by_uid[5001]
    assert northbridge.reputation is None
    assert northbridge.last_league_position is None


@pytest.mark.parametrize(
    ("decoy_ordinal", "decoy_kind"),
    [
        pytest.param(52, NORMAL_STATUS_KIND, id="ordinal not above the previous one"),
        pytest.param(53, 0x0C, id="another kind byte"),
    ],
)
def test_rejected_status_hit_is_passed_over_for_a_later_valid_one(
    decoy_ordinal: int, decoy_kind: int
) -> None:
    northbridge_status, southport_status, athletic_status = example_status_records((51, 52, 54))
    decoy_status = status_record_bytes(
        ordinal=decoy_ordinal,
        club_index=4,
        uid=5004,
        kind=decoy_kind,
        last_league_position=1,
        reputation=9999,
    )
    status_records = [northbridge_status, southport_status, decoy_status, athletic_status]
    athletic = read_index(example_game_db(status_records=status_records)).club_by_uid[5004]
    assert athletic.reputation == 1200
    assert athletic.last_league_position == 14


# From the cursor just after Southport's kind byte, Rovers' uid sits at this many bytes plus the
# gap: the rest of Southport's record, Athletic's record, then Rovers' uid offset.
ROVERS_UID_DISTANCE_BEFORE_GAP = (
    STATUS_RECORD_BYTES - (STATUS_UID_AT + 8) + STATUS_RECORD_BYTES + STATUS_UID_AT
)


@pytest.mark.parametrize(
    ("distance_beyond_window", "rovers_reputation", "athletic_reputation"),
    [
        pytest.param(0, 4000, None, id="at the window end"),
        pytest.param(1, None, 1200, id="one byte beyond the window"),
    ],
)
def test_status_search_after_the_first_hit_is_bounded_by_the_window(
    distance_beyond_window: int, rovers_reputation: int | None, athletic_reputation: int | None
) -> None:
    window_bytes = registered_club_layouts().statuses.search_window_bytes
    rovers_status = status_record_bytes(
        ordinal=60,
        club_index=3,
        uid=5003,
        kind=NORMAL_STATUS_KIND,
        last_league_position=7,
        reputation=4000,
    )
    gap_bytes = window_bytes - ROVERS_UID_DISTANCE_BEFORE_GAP + distance_beyond_window
    status_records = [*example_status_records(), bytes(gap_bytes) + rovers_status]
    club_records = records_with_rovers_after_northbridge(ROVERS.record_bytes())
    club_index = read_index(example_game_db(club_records, status_records))
    assert club_index.club_by_uid[5001].reputation == 6500
    assert club_index.club_by_uid[5003].reputation == rovers_reputation
    assert club_index.club_by_uid[5004].reputation == athletic_reputation


@pytest.mark.parametrize(("missing_clubs", "last_club_reputation"), [(15, 1200), (16, None)])
def test_status_walk_stops_after_too_many_leading_misses(
    missing_clubs: int, last_club_reputation: int | None
) -> None:
    assert registered_club_layouts().statuses.maximum_leading_misses == 16
    leading_clubs = [
        ExampleClubSpec(
            club_number, 6000 + club_number, f"Example Club {club_number}", "Club", 3, 3, 77, ()
        )
        for club_number in range(1, missing_clubs + 1)
    ]
    last_club = replace(ATHLETIC, club_index=missing_clubs + 1)
    last_club_status = status_record_bytes(
        ordinal=51,
        club_index=missing_clubs + 1,
        uid=5004,
        kind=NORMAL_STATUS_KIND,
        last_league_position=14,
        reputation=1200,
    )
    club_records = [club.record_bytes() for club in (*leading_clubs, last_club)]
    club_index = read_index(example_game_db(club_records, [last_club_status]))
    assert len(club_index.clubs) == missing_clubs + 1
    assert club_index.club_by_uid[5004].reputation == last_club_reputation
    assert club_index.club_by_uid[6001].reputation is None


def test_clubs_and_teams_survive_pickle_and_deepcopy() -> None:
    club_index = read_index(example_game_db())
    for club in club_index.clubs:
        for protocol in range(2, pickle.HIGHEST_PROTOCOL + 1):
            copied_club = pickle.loads(pickle.dumps(club, protocol=protocol))
            assert copied_club == club
            assert type(copied_club) is Club
        assert copy.deepcopy(club) == club
    first_team = club_index.clubs[0].teams[0]
    assert pickle.loads(pickle.dumps(first_team)) == first_team
    assert copy.deepcopy(first_team) == first_team
    assert type(copy.deepcopy(first_team)) is Team
    clubs_table = fmsave.Table(club_index.clubs, Club)
    assert pickle.loads(pickle.dumps(clubs_table)) == clubs_table


def test_club_and_team_are_frozen() -> None:
    club = read_index(example_game_db()).clubs[0]
    with pytest.raises(AttributeError):
        club.name = "Example Rovers"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        club.teams[0].slot = 3  # type: ignore[misc]


def test_club_index_repr_hides_names_and_the_file_name() -> None:
    club_index = read_index(example_game_db())
    description = repr(club_index)
    assert FILE_NAME not in description
    for fictional_name in FICTIONAL_NAMES:
        assert fictional_name not in description
    assert "3 clubs" in description


LAYOUT_VALUE_PATTERN = r"(?:-?\d+|b'[^']*'|\(\d+, \d+\))"


def test_layouts_hold_and_show_only_numbers_and_byte_patterns() -> None:
    club_layouts = registered_club_layouts()
    for layout in (club_layouts.records, club_layouts.team_lists, club_layouts.statuses):
        type_name = type(layout).__name__
        for layout_field in dataclasses.fields(layout):
            value = getattr(layout, layout_field.name)
            is_number_pair = isinstance(value, tuple) and all(
                type(item) is int
                for item in value  # pyright: ignore[reportUnknownVariableType]
            )
            assert type(value) in (int, bytes) or is_number_pair, f"{type_name}.{layout_field.name}"
        field_pattern = rf"\w+={LAYOUT_VALUE_PATTERN}"
        repr_pattern = rf"{type_name}\({field_pattern}(?:, {field_pattern})*\)"
        assert re.fullmatch(repr_pattern, repr(layout)), type_name


def test_field_statuses_follow_the_brief() -> None:
    assert fmsave.field_status(Club, "reputation") == "verified"
    assert fmsave.field_status(Club, "last_league_position") == "verified"
    for unconfirmed_field in (
        "uid",
        "name",
        "short_name",
        "nation_id",
        "fa_nation_id",
        "city_id",
        "teams",
        "parent_club_uid",
        "parent_club_name",
    ):
        assert fmsave.field_status(Club, unconfirmed_field) == "unconfirmed", unconfirmed_field
    for unconfirmed_team_field in ("team_id", "slot", "club_uid", "is_affiliate"):
        assert fmsave.field_status(Team, unconfirmed_team_field) == "unconfirmed"


def test_clubs_export_with_nested_teams() -> None:
    clubs_table = fmsave.Table(read_index(example_game_db()).clubs, Club)
    assert "teams" in export.column_names(Club)
    first_row = clubs_table.to_dicts(json_ready=True)[0]
    assert first_row["teams"] == [
        {"team_id": 70001, "slot": 0, "club_uid": 5001, "is_affiliate": False},
        {"team_id": 70002, "slot": 1, "club_uid": 5001, "is_affiliate": False},
    ]
    assert first_row["reputation"] == 6500


def test_registered_club_layouts() -> None:
    record_match = find_layout(ClubRecordLayout, "game_db", GAME_DB_SCHEMA, "")
    team_list_match = find_layout(TeamListLayout, "game_db", GAME_DB_SCHEMA, "")
    status_match = find_layout(ClubStatusLayout, "game_db", GAME_DB_SCHEMA, "")
    assert record_match.exact and team_list_match.exact and status_match.exact
    record_layout = record_match.layout
    assert record_layout.anchor == b"\xff\xff\xff\xff"
    assert record_layout.anchor_offset == 17
    assert record_layout.long_name_offset == 39
    assert record_layout.nation_id_range == (1, 999)
    assert record_layout.max_name_bytes == 64
    assert record_layout.stop_gap_bytes == 65_536
    team_list_layout = team_list_match.layout
    assert team_list_layout.null_date_triple == NULL_DATE * 3
    assert team_list_layout.float_anchor == b"\x00\x00\x80\x3f"
    assert team_list_layout.float_anchor_offset == 33
    assert team_list_layout.minimum_float_anchor_record_offset == 40
    assert team_list_layout.team_count_range == (1, 8)
    assert team_list_layout.team_id_range == (1, 3_000_000)
    assert team_list_layout.affiliate_count_range == (0, 8)
    status_layout = status_match.layout
    assert status_layout.ordinal_limit == 200_000
    assert (status_layout.normal_kind, status_layout.stub_kind) == (0x0A, 0x0B)
    assert (status_layout.position_offset, status_layout.reputation_offset) == (10, 11)
    assert status_layout.reputation_range == (1, 10_000)
    assert status_layout.search_window_bytes == 262_144
    assert status_layout.maximum_leading_misses == 16
    club_layouts = registered_club_layouts()
    assert club_layouts == ClubLayouts(record_layout, team_list_layout, status_layout)


@pytest.fixture
def clubs_fragment_path(tmp_path: Path) -> Path:
    sections = [
        SectionFrame("game_db", example_game_db()) if section.name == "game_db" else section
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def test_save_clubs_returns_a_cached_table(
    clubs_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section_reads: list[str] = []
    original_read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        section_reads.append(name)
        return original_read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)
    with fmsave.open(clubs_fragment_path) as career_save:
        clubs = career_save.clubs()
        assert isinstance(clubs, fmsave.Table)
        assert clubs.record_type is Club
        assert len(clubs) == 3
        assert career_save.clubs() is clubs
        assert career_save._context.club_index() is career_save._context.club_index()
        assert career_save._context.club_index().clubs == tuple(clubs)
        assert clubs.find(name="northbridge fc")[0].uid == 5001
        assert clubs.by_uid(5004).teams[1] == Team(70004, 1, 5004, False)
        assert section_reads == ["game_db"]
        assert career_save._context._loaned_sections == {}
        assert CLUB_INDEX_CACHE_KEY == "club_index"
        assert CLUBS_TABLE_CACHE_KEY == "table:clubs"
        assert career_save._context._cache[CLUBS_TABLE_CACHE_KEY] is clubs
        assert CLUB_INDEX_CACHE_KEY in career_save._context._cache
    assert career_save.closed
    with pytest.raises(fmsave.SaveClosedError):
        career_save.clubs()
    with pytest.raises(fmsave.SaveClosedError):
        career_save._context.club_index()
    assert len(clubs) == 3
    assert clubs.by_uid(5002).fa_nation_id == 4
    assert clubs.find(name="Example Athletic")[0].reputation == 1200


def test_save_clubs_errors_name_the_file_but_not_its_folder(tmp_path: Path) -> None:
    sections = [
        SectionFrame("game_db", section_body(".dat", GAME_DB_SCHEMA, bytes(512)))
        if section.name == "game_db"
        else section
        for section in default_sections()
    ]
    fragment_path = build_container_fragment(sections).write(
        tmp_path / "Private Folder" / FILE_NAME
    )
    with fmsave.open(fragment_path) as career_save:
        with pytest.raises(ReaderCheckError) as error_info:
            career_save.clubs()
        with pytest.raises(ReaderCheckError):
            career_save.clubs()
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message
    assert "Private Folder" not in message
    assert str(tmp_path) not in message
