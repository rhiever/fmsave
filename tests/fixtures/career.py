"""One whole synthetic career fragment, composed from the section builders, for CLI tests.

It holds name pools, clubs with their status records, a human manager with a contract, four
players with person blocks, contracts and suspensions, the `humans` section and a save summary
that links the manager to a club.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All names are fictional.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from tests.fixtures.container import (
    ContainerFragment,
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    save_summary_body,
    section_body,
)
from tests.fixtures.game_db import (
    NORMAL_STATUS_KIND,
    PLAYER_RECORD_MARKER,
    STUB_STATUS_KIND,
    club_record_bytes,
    contract_bytes,
    fallback_contract_bytes,
    game_db_body,
    humans_body,
    name_pools_bytes,
    person_block_bytes,
    player_record_bytes,
    relation_entry_bytes,
    status_record_bytes,
    suspension_entry_bytes,
)

GAME_DB_SCHEMA = 4000
BUILD_STRING = "26.3.2+2329565"
FREE_AGENT_TEAM_ID = 0xFFFFFFFF
MISSING_NAME_ID = 0xFFFFFFFF

FIRST_NAMES = ("Alex", "Sam", "")
SURNAMES = ("Example", "Sample")
COMMON_NAMES = ("Exo", "Pim")

NORTHBRIDGE_UID = 5001
NORTHBRIDGE_TEAM_A = 70001
NORTHBRIDGE_TEAM_B = 70002
SOUTHPORT_UID = 5002
SOUTHPORT_TEAM = 70003
ATHLETIC_UID = 5004
SECOND_NORTHBRIDGE_UID = 5006
HOME_NATION_ID = 3
ATHLETIC_NATION_ID = 7
SECOND_NORTHBRIDGE_NATION_ID = 9

MANAGER_NAME = "Alex Manager"
MANAGER_SELECTOR = 500
MANAGER_PERSON_UID = 777001
UNMATCHED_MANAGER_SELECTOR = 507

PLAYER_A_UID = 900001
PLAYER_B_UID = 900002
PLAYER_C_UID = 900003
PLAYER_D_UID = 900004
PLAYER_NATION_ID = 44
PLAYER_D_NATION_ID = 45
PLAYER_D_LEGAL_NAME = "Légal Ōnly"

RATINGS = (1, 1, 18, 20, 15, 18, 2, 16, 3, 4, 5, 6, 7, 8, 9)
RAW_ATTRIBUTES = (1, 2, 3, 98, 100, *([48] * 19), 88, 33, *([48] * 28))
PERSONALITY = (15, 12, 9, 20, 18, 7, 11, 3)
# A player's own contract chain records carry his pindex plus 1 as their selector.
SELECTOR_OFFSET = 1


@dataclass(frozen=True)
class ExampleClub:
    club_index: int
    uid: int
    name: str
    short_name: str
    nation_id: int
    team_ids: tuple[int, ...]
    float_anchor_only: bool = False


EXAMPLE_CLUBS = (
    ExampleClub(
        1,
        NORTHBRIDGE_UID,
        "Northbridge FC",
        "Northbridge",
        HOME_NATION_ID,
        (NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B),
    ),
    ExampleClub(
        2,
        SOUTHPORT_UID,
        "Southport Example",
        "Southport",
        HOME_NATION_ID,
        (SOUTHPORT_TEAM,),
        float_anchor_only=True,
    ),
    ExampleClub(
        4, ATHLETIC_UID, "Example Athletic", "Athletic", ATHLETIC_NATION_ID, (70005, 70004, 70006)
    ),
)
SECOND_NORTHBRIDGE_CLUB = ExampleClub(
    6,
    SECOND_NORTHBRIDGE_UID,
    "Northbridge FC",
    "Northbridge",
    SECOND_NORTHBRIDGE_NATION_ID,
    (70010,),
)


def clubs_region_bytes(clubs: tuple[ExampleClub, ...]) -> bytes:
    club_records = [
        club_record_bytes(
            club_index=club.club_index,
            uid=club.uid,
            nation_id=club.nation_id,
            fa_nation_id=club.nation_id,
            city_id=77,
            name=club.name,
            short_name=club.short_name,
            team_ids=club.team_ids,
            float_anchor_only=club.float_anchor_only,
        )
        for club in clubs
    ]
    status_records = [
        status_record_bytes(
            ordinal=51 + position,
            club_index=club.club_index,
            uid=club.uid,
            kind=STUB_STATUS_KIND if club.float_anchor_only else NORMAL_STATUS_KIND,
            last_league_position=position + 1,
            reputation=5000 - position * 500,
        )
        for position, club in enumerate(clubs)
    ]
    return game_db_body(club_records, status_records, gap_bytes=2000)


def manager_region_bytes() -> bytes:
    """A non-player person header, then the manager's current contract chain record."""
    person_header = struct.pack(
        "<III", MANAGER_SELECTOR - 1, MANAGER_PERSON_UID, MANAGER_PERSON_UID
    )
    chain_record, _tag_offset = contract_bytes(
        selector=MANAGER_SELECTOR,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=4000,
        start=packed_date(183, 2029),
        tail={"end": packed_date(182, 2032), "status": 3},
        head={"type": 1},
    )
    return person_header + bytes(64) + chain_record + bytes(64)


def player_bytes(
    *,
    pindex: int,
    uid: int,
    team_id: int,
    current_ability: int,
    potential_ability: int,
    transfer_value_raw: int,
    height_cm: int,
    trailing: bytes,
    marker: bytes = PLAYER_RECORD_MARKER,
) -> bytes:
    return player_record_bytes(
        pindex=pindex,
        uid=uid,
        current_ability=current_ability,
        potential_ability=potential_ability,
        bucket=100,
        home_reputation=5000,
        current_reputation=5200,
        world_reputation=5100,
        team_id=team_id,
        ratings=RATINGS,
        raw_attributes=RAW_ATTRIBUTES,
        transfer_value_raw=transfer_value_raw,
        join_date=packed_date(60, 2029),
        sharpness=7000,
        condition=9000,
        height_cm=height_cm,
        marker=marker,
        trailing=trailing,
    )


def player_a_bytes() -> bytes:
    """At Southport: two suspensions, a full person block and two contract chain records."""
    pindex = 11
    suspensions = suspension_entry_bytes(
        competition_id=1234, issued=packed_date(51, 2031), e7=3, e14=1
    ) + suspension_entry_bytes(competition_id=4321, issued=packed_date(306, 2030), e7=64, e14=5)
    person_block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=MISSING_NAME_ID,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=PLAYER_NATION_ID,
        personality=PERSONALITY,
        trait_bits=(1 << 13) | (1 << 40),
        relations=(
            relation_entry_bytes(12, 8, 9, 100),
            relation_entry_bytes(40, 8, 9, 15),
            relation_entry_bytes(12, 8, 9, 100),
            relation_entry_bytes(5, 8, 70),
            relation_entry_bytes(2, 1, 72),
            relation_entry_bytes(7, 3, 1),
        ),
    )
    first_record, _ = contract_bytes(
        selector=pindex + SELECTOR_OFFSET,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=12000,
        start=packed_date(183, 2028),
        tail={
            "end": packed_date(181, 2030),
            "status": 3,
            "e2": 0x0301,
            "e8": 4,
            "e12": 2028,
            "e16": 100,
            "e20": 0xFFFFFFFF,
            "e24": 0xFFFFFFFF,
            "e37": 4,
            "e38": 4,
            "e39": 0x40,
        },
        events=1,
        head={"type": 1, "money_a": 72000, "money_b": 5, "money_c": 9},
        clauses=((250000, 365, 0x11), (0xFFFFFFFF, 2, 0x16)),
    )
    second_record, _ = contract_bytes(
        selector=pindex + SELECTOR_OFFSET,
        team_id=SOUTHPORT_TEAM,
        wage=3000,
        start=packed_date(213, 2029),
        tail={"end": packed_date(151, 2030), "status": 7},
        head={"type": 1},
    )
    decoy_record, _ = contract_bytes(
        selector=99, team_id=NORTHBRIDGE_TEAM_A, wage=1, start=packed_date(1, 2000), tail=None
    )
    return player_bytes(
        pindex=pindex,
        uid=PLAYER_A_UID,
        team_id=SOUTHPORT_TEAM,
        current_ability=140,
        potential_ability=165,
        transfer_value_raw=4_500_000,
        height_cm=181,
        trailing=suspensions + person_block + first_record + second_record + decoy_record,
    )


def player_b_bytes() -> bytes:
    """A free agent with a common name, a legal name and fallback contract dates only."""
    person_block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=1,
        legal_name="Alexander Sample Example",
        birth=packed_date(62, 2004),
        nation_id=PLAYER_NATION_ID,
        personality=PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    fallback = fallback_contract_bytes(end=packed_date(182, 2032), start=packed_date(1, 2027))
    return player_bytes(
        pindex=12,
        uid=PLAYER_B_UID,
        team_id=FREE_AGENT_TEAM_ID,
        current_ability=100,
        potential_ability=-8,
        transfer_value_raw=0xFFFFFFFF,
        height_cm=175,
        trailing=person_block + fallback + bytes(300),
    )


def player_c_bytes() -> bytes:
    """A marker-less record at Northbridge, with a chain record whose tail has no end date."""
    pindex = 13
    person_block = person_block_bytes(
        first_name_id=1,
        surname_id=1,
        common_name_id=2,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=PLAYER_NATION_ID,
        personality=PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    chain_record, _ = contract_bytes(
        selector=pindex + SELECTOR_OFFSET,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2000,
        start=packed_date(1, 2027),
        tail={"end": None, "status": 5},
        head={"type": 2},
    )
    return player_bytes(
        pindex=pindex,
        uid=PLAYER_C_UID,
        team_id=NORTHBRIDGE_TEAM_A,
        current_ability=110,
        potential_ability=130,
        transfer_value_raw=300_000_000,
        height_cm=178,
        marker=packed_date(45, 2010),
        trailing=person_block + chain_record + bytes(300),
    )


def player_d_bytes() -> bytes:
    """A free agent of another nation, known by last name only, with a broken contract tail."""
    pindex = 14
    person_block = person_block_bytes(
        first_name_id=MISSING_NAME_ID,
        surname_id=1,
        common_name_id=MISSING_NAME_ID,
        legal_name=PLAYER_D_LEGAL_NAME,
        birth=packed_date(60, 2004),
        nation_id=PLAYER_D_NATION_ID,
        personality=PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    chain_record, _ = contract_bytes(
        selector=pindex + SELECTOR_OFFSET,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1500,
        start=packed_date(1, 2025),
        tail={"break_tail": True},
    )
    fallback = fallback_contract_bytes(end=packed_date(1, 2030), start=packed_date(1, 2024))
    return player_bytes(
        pindex=pindex,
        uid=PLAYER_D_UID,
        team_id=FREE_AGENT_TEAM_ID,
        current_ability=95,
        potential_ability=105,
        transfer_value_raw=0,
        height_cm=170,
        trailing=person_block + chain_record + fallback + bytes(300),
    )


def career_game_db(*, duplicate_club_name: bool = False) -> bytes:
    clubs = EXAMPLE_CLUBS + ((SECOND_NORTHBRIDGE_CLUB,) if duplicate_club_name else ())
    payload = (
        name_pools_bytes(FIRST_NAMES, SURNAMES, COMMON_NAMES)
        + clubs_region_bytes(clubs)
        + bytes(64)
        + manager_region_bytes()
        + player_a_bytes()
        + player_b_bytes()
        + player_c_bytes()
        + player_d_bytes()
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def career_summary(*, linked: bool) -> bytes:
    """The save summary; when linked, the manager's name is followed by his club's link."""
    if linked:
        return save_summary_body(
            leading_strings=("Example League",),
            trailing_strings=("Example Cup", MANAGER_NAME),
            club_uid_after=("Northbridge", NORTHBRIDGE_UID),
        )
    return save_summary_body(
        leading_strings=("Example League",),
        trailing_strings=("Example Cup", MANAGER_NAME, "Northbridge"),
    )


def career_fragment(
    *, duplicate_club_name: bool = False, manager_between_jobs: bool = False
) -> ContainerFragment:
    """The whole career fragment.

    Args:
        duplicate_club_name: Add a second club (uid 5006) with the same name, "Northbridge FC",
            and the same short name, "Northbridge".
        manager_between_jobs: Give the one human manager no contract and no summary link, so
            no route finds a managed club.
    """
    selector = UNMATCHED_MANAGER_SELECTOR if manager_between_jobs else MANAGER_SELECTOR
    replacements = {
        "game_db": career_game_db(duplicate_club_name=duplicate_club_name),
        "humans": humans_body(count=1, selector=selector),
        "save_game_summary": career_summary(linked=not manager_between_jobs),
    }
    sections = [
        SectionFrame(
            section.name,
            replacements.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    return build_container_fragment(sections)
