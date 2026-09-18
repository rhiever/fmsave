"""One whole synthetic career fragment, composed from the section builders, for CLI tests.

It holds name pools, clubs with their status records, a human manager with a contract, four
players with person blocks, contracts and suspensions, the `humans` section and a save summary
that links the manager to a club.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, replace

from tests.fixtures.club_sections import (
    NO_JOB_COMPETITION,
    feeder_body,
    job_centre_body,
    job_record_bytes,
)
from tests.fixtures.container import (
    ContainerFragment,
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    save_summary_body,
    section_body,
)
from tests.fixtures.finances import (
    club_finance_bytes,
    finance_row_bytes,
    sponsor_row_bytes,
)
from tests.fixtures.game_db import (
    NORMAL_STATUS_KIND,
    PLAYER_RECORD_MARKER,
    STAGE_MISSING_VALUE,
    STUB_STATUS_KIND,
    club_record_bytes,
    competition_id_pair_bytes,
    contract_bytes,
    fallback_contract_bytes,
    game_db_body,
    humans_body,
    match_record_bytes,
    name_pools_bytes,
    person_block_bytes,
    player_record_bytes,
    relation_entry_bytes,
    stage_row_bytes,
    stage_table_bytes,
    status_record_bytes,
    suspension_entry_bytes,
    transfer_window_bytes,
)
from tests.fixtures.injuries import (
    CAREER_INJURY_TYPES,
    DECOY_INJURY_TYPES,
    NULL_DATE_WORD,
    injury_log_row_bytes,
    injury_manager_body,
    injury_type_entries,
    injury_typed_row_bytes,
    injury_window_row_bytes,
    match_file_body,
)
from tests.fixtures.span import (
    STAGE_RESULT_LEAD_BYTE,
    STAGE_RESULT_R22,
    STAGE_RESULT_SENTINEL,
    fixture_record_bytes,
    rules_preamble_bytes,
    span_frames,
    span_payloads,
    stage_result_bytes,
    table_block_bytes,
)
from tests.fixtures.stadiums import career_stadium_rows, stadium_table_bytes
from tests.fixtures.staff import staff_entry_bytes, staff_object_bytes
from tests.fixtures.tactics import (
    HAS_TACTICS_VALUE,
    NO_SELECTOR,
    NO_TACTICS_VALUE,
    ROUTINE_COUNT,
    selection_part_bytes,
    set_piece_area_bytes,
    setting_unit_bytes,
    slot_block_bytes,
    tactic_record_bytes,
    tactics_man_body,
)
from tests.fixtures.training import (
    mentoring_group_bytes,
    schedule_library_bytes,
    training_block_bytes,
    training_header_entry_bytes,
    training_man_body,
    training_week_bytes,
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
ATHLETIC_TEAM_A = 70005
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
PLAYER_A_PINDEX = 11
PLAYER_B_PINDEX = 12
PLAYER_C_PINDEX = 13
PLAYER_D_PINDEX = 14
PLAYER_NATION_ID = 44
PLAYER_D_NATION_ID = 45
PLAYER_D_LEGAL_NAME = "Légal Ōnly"

STAGE_ROW_COUNT = 220
FIRST_COMPETITION_ID = 900
SECOND_COMPETITION_ID = 901
THIRD_COMPETITION_ID = 902
FIRST_COMPETITION_DATABASE_ID = 12_345
SECOND_COMPETITION_DATABASE_ID = 12_346
THIRD_COMPETITION_DATABASE_ID = 12_347
# The id-pair records cover every entity of the stage id space, not only its competitions.
# The stage table never calls this one a competition, so it must not reach the competitions.
NON_COMPETITION_ENTITY_ID = 7
NON_COMPETITION_DATABASE_ID = 999
# A stage row of every save carries this id, which is far above any competition id and is a
# marker or a malformed row rather than a competition, so the reader rejects it.
OUT_OF_BAND_COMPETITION_ID = 16_777_216
GROUPED_STAGE_GROUP_ID = 5501
SEMI_FINAL_ROUND_CODE = 17
FINAL_ROUND_CODE = 19
# Round codes the save uses often that no in-game label reaches, so both stay UNKNOWN.
UNNAMED_LOW_ROUND_CODE = 5
UNNAMED_ROUND_CODE = 77
# The last word of a stage row is the missing value on almost every row; this is one of the few
# that carries a number instead.
EMPTY_STAGE_S29 = 7

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
    affiliate_team_ids: tuple[int, ...] = ()
    staff_lists: tuple[tuple[int, ...], ...] | None = None
    trailing_bytes: bytes = b""


# Monthly finance snapshots, oldest first: the last row is the month before the save's clock of
# 1 March 2031, so these three are December 2030, January 2031 and February 2031. Each row's
# net equals its total income less its total expenditure, and each balance is the one before it
# plus that month's net, which is what the two arithmetic checks judge.
FINANCE_MONTH_VALUES = (
    {
        "balance": 900_000,
        "transfer_allocated": 500_000,
        "transfer_remaining": 400_000,
        "wage_budget_weekly": 30_000,
        "wage_payroll_weekly": 25_000,
        "income_excluding_transfers": 120_000,
        "net_transfers": 0,
        "wage_bill": 80_000,
        "net": 20_000,
        "expenditure_excluding_transfers": 100_000,
        "total_income": 120_000,
        "total_expenditure": 100_000,
    },
    {
        "balance": 1_000_000,
        "transfer_allocated": 500_000,
        "transfer_remaining": 350_000,
        "wage_budget_weekly": 30_000,
        "wage_payroll_weekly": 25_500,
        "income_excluding_transfers": 250_000,
        "net_transfers": -30_000,
        "wage_bill": 90_000,
        "net": 100_000,
        "expenditure_excluding_transfers": 180_000,
        "total_income": 300_000,
        "total_expenditure": 200_000,
    },
    {
        "balance": 950_000,
        "transfer_allocated": 450_000,
        "transfer_remaining": 300_000,
        "wage_budget_weekly": 30_000,
        "wage_payroll_weekly": 26_000,
        "income_excluding_transfers": 150_000,
        "net_transfers": 40_000,
        "wage_bill": 95_000,
        "net": -50_000,
        "expenditure_excluding_transfers": 160_000,
        "total_income": 150_000,
        "total_expenditure": 200_000,
    },
)
FINANCE_MONTH_COUNT = len(FINANCE_MONTH_VALUES)

# Sponsor contracts. A is running, B ended two years before the clock and so carries no annual
# value, and C is Example Athletic's one running contract.
SPONSOR_A = {
    "sponsor_type": 4,
    "start": packed_date(182, 2030),
    "end": packed_date(181, 2033),
    "flag10": 1,
    "total": 3_000_000,
    "u15": 77,
    "b17": 0,
    "enum18": 2,
    "b19": 5,
    "annual": 1_000_000,
}
SPONSOR_B = {
    "sponsor_type": 1,
    "start": packed_date(1, 2026),
    "end": packed_date(366, 2028),
    "flag10": 0,
    "total": 400_000,
    "u15": 3,
    "b17": 1,
    "enum18": 255,
    "b19": 0,
    "annual": 0,
}
SPONSOR_C = {
    "sponsor_type": 9,
    "start": packed_date(182, 2030),
    "end": packed_date(182, 2032),
    "flag10": 1,
    "total": 500_000,
    "u15": 0,
    "b17": 0,
    "enum18": 0,
    "b19": 0,
    "annual": 250_000,
}
# A second, dead run of sponsor rows, which the save holds for a handful of clubs: every row
# has ended and carries no annual value. A reader taking the longest run reads these instead.
DEAD_SPONSOR = {
    "sponsor_type": 3,
    "start": packed_date(1, 2020),
    "end": packed_date(1, 2022),
    "flag10": 0,
    "total": 10_000,
    "u15": 0,
    "b17": 0,
    "enum18": 0,
    "b19": 0,
    "annual": 0,
}
DEAD_SPONSOR_COUNT = 2
NORTHBRIDGE_FACILITY_BYTE = 17
ATHLETIC_FACILITY_BYTE = 12


def career_finance_rows() -> tuple[bytes, ...]:
    return tuple(finance_row_bytes(**values) for values in FINANCE_MONTH_VALUES)


def club_finance_trailing_bytes(
    sponsors: Sequence[dict[str, object]],
    *,
    facility_byte: int,
    dead_sponsors: Sequence[dict[str, object]] = (),
) -> bytes:
    """One club's finance bytes: the three months, then the sponsors it holds."""
    return club_finance_bytes(
        rows=career_finance_rows(),
        sponsors=[sponsor_row_bytes(**values) for values in sponsors],  # pyright: ignore[reportArgumentType]
        facility_byte=facility_byte,
        dead_sponsors=[sponsor_row_bytes(**values) for values in dead_sponsors],  # pyright: ignore[reportArgumentType]
    )


# Staff person ids and the values a club list stores for them, which are the id plus 1. Every
# id sits above every player pindex, so a list-only person is bracketed by the last player.
STAFF_CONTRACTED_PERSON_ID = 21
STAFF_LISTED_ONLY_PERSON_ID = 22
STAFF_CONTRACT_ONLY_PERSON_ID = 23
STAFF_AFFILIATE_PERSON_ID = 24
STAFF_CONTRACTED_UID = 810_021
STAFF_LISTED_ONLY_UID = 810_022
STAFF_CONTRACT_ONLY_UID = 810_023
STAFF_AFFILIATE_UID = 810_024
PLAYER_B_PINDEX = 12
# Northbridge lists the contracted person in list 0, and in list 1 both the list-only person
# and player B's pindex plus 1, which a reader has to drop and count.
NORTHBRIDGE_STAFF_LISTS = (
    (STAFF_CONTRACTED_PERSON_ID + 1,),
    (STAFF_LISTED_ONLY_PERSON_ID + 1, PLAYER_B_PINDEX + 1),
    (),
)
NO_STAFF_LISTS: tuple[tuple[int, ...], ...] = ((), (), ())
COLTS_STAFF_LISTS = ((), (), (STAFF_AFFILIATE_PERSON_ID + 1,))

EXAMPLE_CLUBS = (
    ExampleClub(
        1,
        NORTHBRIDGE_UID,
        "Northbridge FC",
        "Northbridge",
        HOME_NATION_ID,
        (NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B),
        staff_lists=NORTHBRIDGE_STAFF_LISTS,
        trailing_bytes=club_finance_trailing_bytes(
            (SPONSOR_A, SPONSOR_B), facility_byte=NORTHBRIDGE_FACILITY_BYTE
        ),
    ),
    ExampleClub(
        2,
        SOUTHPORT_UID,
        "Southport Example",
        "Southport",
        HOME_NATION_ID,
        (SOUTHPORT_TEAM,),
        float_anchor_only=True,
        staff_lists=NO_STAFF_LISTS,
    ),
    ExampleClub(
        4,
        ATHLETIC_UID,
        "Example Athletic",
        "Athletic",
        ATHLETIC_NATION_ID,
        (70005, 70004, 70006),
        staff_lists=NO_STAFF_LISTS,
        trailing_bytes=club_finance_trailing_bytes(
            (SPONSOR_C,),
            facility_byte=ATHLETIC_FACILITY_BYTE,
            dead_sponsors=(DEAD_SPONSOR,) * DEAD_SPONSOR_COUNT,
        ),
    ),
)
SECOND_NORTHBRIDGE_CLUB = ExampleClub(
    6,
    SECOND_NORTHBRIDGE_UID,
    "Northbridge FC",
    "Northbridge",
    SECOND_NORTHBRIDGE_NATION_ID,
    (70010,),
    staff_lists=NO_STAFF_LISTS,
)
# The B team Northbridge controls, which lists a person Northbridge itself pays.
COLTS_CLUB_INDEX = 7
COLTS_UID = 5007
COLTS_TEAM = 70007
COLTS_CLUB = ExampleClub(
    COLTS_CLUB_INDEX,
    COLTS_UID,
    "Northbridge Colts",
    "Colts",
    HOME_NATION_ID,
    (COLTS_TEAM,),
    staff_lists=COLTS_STAFF_LISTS,
)


def example_clubs(
    *, staff_affiliate: bool = False, duplicate_club_name: bool = False
) -> tuple[ExampleClub, ...]:
    """The example clubs, with the colts and Northbridge's link to them when asked for."""
    clubs = EXAMPLE_CLUBS
    if staff_affiliate:
        northbridge = replace(clubs[0], affiliate_team_ids=(COLTS_TEAM,))
        clubs = (northbridge, *clubs[1:], COLTS_CLUB)
    if duplicate_club_name:
        clubs = (*clubs, SECOND_NORTHBRIDGE_CLUB)
    return clubs


def clubs_region_bytes(
    clubs: tuple[ExampleClub, ...], *, competition_id_pairs: bytes = b""
) -> bytes:
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
            affiliate_team_ids=club.affiliate_team_ids,
            float_anchor_only=club.float_anchor_only,
            staff_lists=club.staff_lists,
            trailing_bytes=club.trailing_bytes,
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
    return game_db_body(
        club_records,
        status_records,
        gap_bytes=2000,
        competition_id_pairs=competition_id_pairs,
    )


def career_competition_id_pairs() -> bytes:
    """One id-pair record per competition of the example stage table, and one for an entity
    that the stage table never calls a competition.
    """
    return b"".join(
        competition_id_pair_bytes(entity_id=entity_id, database_id=database_id)
        for entity_id, database_id in (
            (FIRST_COMPETITION_ID, FIRST_COMPETITION_DATABASE_ID),
            (SECOND_COMPETITION_ID, SECOND_COMPETITION_DATABASE_ID),
            (THIRD_COMPETITION_ID, THIRD_COMPETITION_DATABASE_ID),
            (NON_COMPETITION_ENTITY_ID, NON_COMPETITION_DATABASE_ID),
        )
    )


# The human manager's own object. His kind byte is not the staff one, he carries one entry in
# front of a stretch of bytes where no ability signature reads, and his name block sits after
# his one contract record rather than in front of it.
MANAGER_OBJECT_KIND = 9
MANAGER_ENTRY = (1024, 3212)
MANAGER_HEADER_BYTES = 12
MANAGER_ENTRY_LIST_BYTES = 3 + 7
MANAGER_BEFORE_CONTRACT_BYTES = 64
MANAGER_BLOCK_AFTER_CONTRACT_BYTES = 24
MANAGER_BIRTH_DAY = 60
MANAGER_BIRTH_YEAR = 1975
MANAGER_NATION_ID = 44
MANAGER_PERSONALITY = (12,) * 8


def manager_region_bytes() -> bytes:
    """The human manager's object: his header, his contract chain record and his name block.

    The 10 bytes the object-kind byte and the entry list take up come out of the padding in
    front of the contract record, so the record itself sits exactly where it did before.
    """
    person_header = struct.pack(
        "<III", MANAGER_SELECTOR - 1, MANAGER_PERSON_UID, MANAGER_PERSON_UID
    )
    entry_list = bytearray((MANAGER_OBJECT_KIND, 1, 0))
    entry_list.extend(staff_entry_bytes(*MANAGER_ENTRY))
    chain_record, _tag_offset = contract_bytes(
        selector=MANAGER_SELECTOR,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=4000,
        start=packed_date(183, 2029),
        tail={"end": packed_date(182, 2032), "status": 3},
        head={"type": 1},
    )
    person_block = person_block_bytes(
        first_name_id=0,
        surname_id=1,
        common_name_id=MISSING_NAME_ID,
        legal_name=None,
        birth=packed_date(MANAGER_BIRTH_DAY, MANAGER_BIRTH_YEAR),
        nation_id=MANAGER_NATION_ID,
        personality=MANAGER_PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    return (
        person_header
        + bytes(entry_list)
        + bytes(MANAGER_BEFORE_CONTRACT_BYTES - MANAGER_ENTRY_LIST_BYTES)
        + chain_record
        + bytes(MANAGER_BLOCK_AFTER_CONTRACT_BYTES)
        + person_block
        + bytes(64)
    )


def staff_region_bytes(*, staff_affiliate: bool = False) -> bytes:
    """The example staff objects, in ascending person id.

    The contracted person, the list-only person (whose two entries move his ability block), the
    contract-only person and, when asked for, the person the colts list and Northbridge pays.
    """
    contracted_record, _tag_offset = contract_bytes(
        selector=STAFF_CONTRACTED_PERSON_ID + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2500,
        start=packed_date(183, 2029),
        tail={"end": packed_date(182, 2032), "status": 0, "e39": 0x40},
        head={"type": 1},
    )
    contract_only_record, _tag_offset = contract_bytes(
        selector=STAFF_CONTRACT_ONLY_PERSON_ID + 1,
        team_id=SOUTHPORT_TEAM,
        wage=900,
        start=packed_date(1, 2030),
        tail={"end": packed_date(181, 2031), "status": 3},
        head={"type": 0},
    )
    objects = [
        staff_object_bytes(
            person_id=STAFF_CONTRACTED_PERSON_ID,
            uid=STAFF_CONTRACTED_UID,
            current_ability=120,
            potential_ability=140,
            r4=16,
            contract=contracted_record,
            person_block=person_block_bytes(
                first_name_id=1,
                surname_id=0,
                common_name_id=MISSING_NAME_ID,
                legal_name=None,
                birth=packed_date(167, 1980),
                nation_id=PLAYER_NATION_ID,
                personality=(14, 10, 12, 8, 16, 11, 9, 5),
                trait_bits=0,
                relations=(),
            ),
        ),
        staff_object_bytes(
            person_id=STAFF_LISTED_ONLY_PERSON_ID,
            uid=STAFF_LISTED_ONLY_UID,
            entries=((6792, 3212), (6658, 3212)),
            current_ability=80,
            potential_ability=95,
            r4=20,
            person_block=person_block_bytes(
                first_name_id=1,
                surname_id=1,
                common_name_id=MISSING_NAME_ID,
                legal_name=None,
                birth=packed_date(100, 1975),
                nation_id=PLAYER_D_NATION_ID,
                personality=(9,) * 8,
                trait_bits=0,
                relations=(),
            ),
        ),
        staff_object_bytes(
            person_id=STAFF_CONTRACT_ONLY_PERSON_ID,
            uid=STAFF_CONTRACT_ONLY_UID,
            current_ability=100,
            potential_ability=100,
            r4=16,
            contract=contract_only_record,
            person_block=person_block_bytes(
                first_name_id=0,
                surname_id=0,
                common_name_id=MISSING_NAME_ID,
                legal_name=None,
                birth=packed_date(1, 1970),
                nation_id=PLAYER_NATION_ID,
                personality=(7,) * 8,
                trait_bits=0,
                relations=(),
            ),
        ),
    ]
    if staff_affiliate:
        affiliate_record, _tag_offset = contract_bytes(
            selector=STAFF_AFFILIATE_PERSON_ID + 1,
            team_id=NORTHBRIDGE_TEAM_A,
            wage=1200,
            start=packed_date(1, 2030),
            tail={"end": packed_date(181, 2031), "status": 0},
            head={"type": 1},
        )
        objects.append(
            staff_object_bytes(
                person_id=STAFF_AFFILIATE_PERSON_ID,
                uid=STAFF_AFFILIATE_UID,
                current_ability=110,
                potential_ability=115,
                r4=14,
                contract=affiliate_record,
                person_block=person_block_bytes(
                    first_name_id=1,
                    surname_id=0,
                    common_name_id=MISSING_NAME_ID,
                    legal_name=None,
                    birth=packed_date(1, 1990),
                    nation_id=PLAYER_NATION_ID,
                    personality=(11,) * 8,
                    trait_bits=0,
                    relations=(),
                ),
            )
        )
    return b"".join(objects)


# Per-match player records. The four matches sit inside player A's own window; player B plays
# none. Every date falls in the window a scan builds from the in-game date of 1 March 2031.
MATCH_YEAR = 2031
FIRST_MATCH_DAY = 51
UNPLAYED_MATCH_DAY = 44
UNLISTED_COMPETITION_MATCH_DAY = 37
OUT_OF_RANGE_MATCH_DAY = 30
# A competition id the example stage table never names, so it is outside the stage id space.
UNLISTED_MATCH_COMPETITION_ID = 4242
# The one mask bit a displayed in-game label names, so this match carries a named position.
FIRST_MATCH_POSITION_MASK = 1 << 0
# A bit no displayed label names, which has to read as unknown with its raw mask kept.
UNNAMED_POSITION_MASK = 1 << 12
FIRST_MATCH_ROLE_CODE = 5
FIRST_MATCH_GOALS = 2
FIRST_MATCH_ASSISTS = 1
FIRST_MATCH_MINUTES = 90
FIRST_MATCH_LEFT_AT = 90
FIRST_MATCH_RATING_X10 = 78
FIRST_MATCH_PASSES_ATTEMPTED = 40
FIRST_MATCH_PASSES_COMPLETED = 35
UNLISTED_COMPETITION_MATCH_MINUTES = 45
UNLISTED_COMPETITION_MATCH_RATING_X10 = 65
# Past every bound the body's own sanity flag holds a match to.
OUT_OF_RANGE_MATCH_MINUTES = 200
OUT_OF_RANGE_MATCH_RATING_X10 = 120
OUT_OF_RANGE_MATCH_GOALS = 30
PLAYER_A_MATCH_COUNT = 4


def player_a_match_records() -> bytes:
    """Player A's four matches, in the order the save stores them.

    The first carries a filled-in body, the second is the 15-byte header the save keeps for a
    match with no body at all, the third names a competition the stage table does not hold, and
    the fourth is played against a team no club lists with a body past every range. The fourth
    opponent is the team id the fixture calendar below leaves unlisted as well.
    """
    return (
        match_record_bytes(
            day_of_year=FIRST_MATCH_DAY,
            year=MATCH_YEAR,
            opponent_team_id=NORTHBRIDGE_TEAM_A,
            competition_id=FIRST_COMPETITION_ID,
            played=True,
            position_mask=FIRST_MATCH_POSITION_MASK,
            role_code=FIRST_MATCH_ROLE_CODE,
            goals=FIRST_MATCH_GOALS,
            assists=FIRST_MATCH_ASSISTS,
            left_at=FIRST_MATCH_LEFT_AT,
            minutes=FIRST_MATCH_MINUTES,
            rating_x10=FIRST_MATCH_RATING_X10,
            passes_attempted=FIRST_MATCH_PASSES_ATTEMPTED,
            passes_completed=FIRST_MATCH_PASSES_COMPLETED,
        )
        + match_record_bytes(
            day_of_year=UNPLAYED_MATCH_DAY,
            year=MATCH_YEAR,
            opponent_team_id=ATHLETIC_TEAM_A,
            competition_id=FIRST_COMPETITION_ID,
            played=False,
        )
        + match_record_bytes(
            day_of_year=UNLISTED_COMPETITION_MATCH_DAY,
            year=MATCH_YEAR,
            opponent_team_id=NORTHBRIDGE_TEAM_A,
            competition_id=UNLISTED_MATCH_COMPETITION_ID,
            played=True,
            position_mask=UNNAMED_POSITION_MASK,
            minutes=UNLISTED_COMPETITION_MATCH_MINUTES,
            rating_x10=UNLISTED_COMPETITION_MATCH_RATING_X10,
        )
        + match_record_bytes(
            day_of_year=OUT_OF_RANGE_MATCH_DAY,
            year=MATCH_YEAR,
            opponent_team_id=UNREGISTERED_FIXTURE_TEAM_ID,
            competition_id=FIRST_COMPETITION_ID,
            played=True,
            goals=OUT_OF_RANGE_MATCH_GOALS,
            minutes=OUT_OF_RANGE_MATCH_MINUTES,
            rating_x10=OUT_OF_RANGE_MATCH_RATING_X10,
        )
    )


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
    match_records: bytes = b"",
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
        match_records=match_records,
    )


def player_a_bytes() -> bytes:
    """At Southport: two suspensions, a full person block, two contract chain records and the
    four matches `player_a_match_records` writes at the end of his window.
    """
    pindex = PLAYER_A_PINDEX
    # The first ban covers one competition, and names one this career really holds, so a name
    # map reaches it. The second is nation-wide, and its id is a nation id that happens to
    # equal the third competition's id: a lookup that ignored the scope would name it after
    # that competition, which is the mistake the scope exists to stop.
    suspensions = suspension_entry_bytes(
        scope_id=FIRST_COMPETITION_ID, issued=packed_date(51, 2031), e7=3, scope_code=1
    ) + suspension_entry_bytes(
        scope_id=THIRD_COMPETITION_ID, issued=packed_date(306, 2030), e7=64, scope_code=5
    )
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
        clauses=((250000, 365, 0x12), (0xFFFFFFFF, 2, 0x16)),
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
        match_records=player_a_match_records(),
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
        pindex=PLAYER_B_PINDEX,
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
    pindex = PLAYER_C_PINDEX
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
    pindex = PLAYER_D_PINDEX
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


def career_stage_rows() -> list[bytes]:
    """220 stage rows, ids 1 to 220: a handful with distinctive values, then a long run.

    Row 1 stores the missing value as its previous stage id, row 2 a group and one unidentified
    word, row 3 a round code with no confirmed meaning, row 4 nothing but its id and both
    unidentified words, and row 5 the out-of-band competition id the reader rejects. Rows 6 to
    220 all belong to one competition, which makes the run long enough to prove the reader's
    200-row chain.
    """
    rows = [
        stage_row_bytes(
            stage_id=1,
            competition_id=FIRST_COMPETITION_ID,
            group_id=None,
            round_code=FINAL_ROUND_CODE,
            previous_stage_id=STAGE_MISSING_VALUE,
        ),
        stage_row_bytes(
            stage_id=2,
            competition_id=FIRST_COMPETITION_ID,
            group_id=GROUPED_STAGE_GROUP_ID,
            round_code=SEMI_FINAL_ROUND_CODE,
            s25=3,
        ),
        stage_row_bytes(
            stage_id=3,
            competition_id=SECOND_COMPETITION_ID,
            group_id=None,
            round_code=UNNAMED_ROUND_CODE,
        ),
        stage_row_bytes(
            stage_id=4,
            competition_id=None,
            group_id=None,
            round_code=None,
            s25=22,
            s29=EMPTY_STAGE_S29,
        ),
        stage_row_bytes(
            stage_id=5,
            competition_id=OUT_OF_BAND_COMPETITION_ID,
            group_id=None,
            round_code=UNNAMED_LOW_ROUND_CODE,
        ),
    ]
    rows.extend(
        stage_row_bytes(
            stage_id=stage_id, competition_id=THIRD_COMPETITION_ID, group_id=None, round_code=None
        )
        for stage_id in range(6, STAGE_ROW_COUNT + 1)
    )
    return rows


# The unnamed span between this section and `humans` is where the fixture calendar lives.
SPAN_SECTION_NAME = "non_pl_hist_ls"

# Fixture calendar: the career's own run of records, then a stray copy of two more, far enough
# past it to count as a separate run. Only the larger run is the calendar, which is what drops
# the block of template records every real save carries.
FIXTURE_STAGE_ID = 1
CUP_FIXTURE_STAGE_ID = 3
# A stage id the example stage table does not hold, so its competition never resolves.
UNRESOLVED_FIXTURE_STAGE_ID = 9999
STRAY_FIXTURE_STAGE_ID = 4
FIXTURE_KICK_OFF_YEAR = 2031
FIXTURE_SEASON_START_YEAR = 2030
STRAY_FIXTURE_SEASON_START_YEAR = 2029
LEAGUE_KICK_OFF_SLOT = 34
CUP_KICK_OFF_SLOT = 41
# (73 + 23) * 15 is exactly one whole day of minutes, so it names no time of day.
PAST_MIDNIGHT_KICK_OFF_SLOT = 73
HOME_STADIUM_ORDINAL = 10
AWAY_STADIUM_ORDINAL = 20
NEUTRAL_STADIUM_ORDINAL = 99
# An ordinal past the last row of the example stadium table, so no ground resolves from it.
UNLISTED_STADIUM_ORDINAL = 150
NO_ROUND_INDEX = 255
# A team id no club of the example save lists.
UNREGISTERED_FIXTURE_TEAM_ID = 79999
FIRST_MATCH_RECORD_ID = 880_000
STRAY_MATCH_RECORD_ID = 990_000
FIXTURE_SEPARATOR_BYTES = 64
# Comfortably past the 1 MiB that separates one run of fixture records from the next.
STRAY_CLUSTER_GAP_BYTES = 2 * 1024 * 1024
FIXTURE_DATE2 = 0x1234
FIXTURE_PHASE = 2
FIXTURE_LEG = 1
FIXTURE_R39_42 = 0x11223344
FIXTURE_R47_54 = 0x0102030405060708
FIXTURE_MATCH_RULES_TEMPLATE = (7, 8, 9)


@dataclass(frozen=True)
class ExampleFixture:
    stage_id: int
    home_team_id: int
    away_team_id: int
    day_of_year: int
    time_slot: int
    round_index: int
    played: bool
    stadium_ordinal: int
    season_start_year: int = FIXTURE_SEASON_START_YEAR


# Written out of date order on purpose: file order is neither sorted nor a rotation of a
# sorted order on a real save, so a reader that does not sort has to fail on these.
MAIN_CLUSTER_FIXTURES = (
    ExampleFixture(FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 51, 34, 0, True, 10),
    ExampleFixture(FIXTURE_STAGE_ID, SOUTHPORT_TEAM, NORTHBRIDGE_TEAM_A, 58, 34, 1, True, 20),
    ExampleFixture(CUP_FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, 70005, 65, 41, 255, False, 99),
    ExampleFixture(UNRESOLVED_FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, 70004, 72, 34, 2, False, 10),
    ExampleFixture(FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, 70006, 44, 34, 3, True, 10),
    ExampleFixture(FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 37, 34, 4, True, 10),
)
# Dated before every record of the calendar, so a reader that keeps them lists them first.
STRAY_FIXTURES = (
    ExampleFixture(
        STRAY_FIXTURE_STAGE_ID,
        NORTHBRIDGE_TEAM_B,
        70005,
        10,
        LEAGUE_KICK_OFF_SLOT,
        0,
        True,
        HOME_STADIUM_ORDINAL,
        STRAY_FIXTURE_SEASON_START_YEAR,
    ),
    ExampleFixture(
        STRAY_FIXTURE_STAGE_ID,
        70005,
        NORTHBRIDGE_TEAM_B,
        17,
        LEAGUE_KICK_OFF_SLOT,
        1,
        True,
        AWAY_STADIUM_ORDINAL,
        STRAY_FIXTURE_SEASON_START_YEAR,
    ),
)
# Extra calendar records some tests add: one whose home team no club lists, and one whose
# kick-off slot lands past midnight.
UNRESOLVED_TEAM_FIXTURE = ExampleFixture(
    FIXTURE_STAGE_ID,
    UNREGISTERED_FIXTURE_TEAM_ID,
    SOUTHPORT_TEAM,
    79,
    LEAGUE_KICK_OFF_SLOT,
    5,
    True,
    HOME_STADIUM_ORDINAL,
)
PAST_MIDNIGHT_FIXTURE = ExampleFixture(
    FIXTURE_STAGE_ID,
    NORTHBRIDGE_TEAM_B,
    SOUTHPORT_TEAM,
    86,
    PAST_MIDNIGHT_KICK_OFF_SLOT,
    6,
    True,
    HOME_STADIUM_ORDINAL,
)
# A record storing a ground ordinal the stadium table does not hold, so its ground stays empty.
UNLISTED_STADIUM_FIXTURE = ExampleFixture(
    FIXTURE_STAGE_ID,
    NORTHBRIDGE_TEAM_B,
    SOUTHPORT_TEAM,
    135,
    LEAGUE_KICK_OFF_SLOT,
    13,
    True,
    UNLISTED_STADIUM_ORDINAL,
)
# Records that pin the neutral-venue minimum from both sides in one save: Example Athletic's
# team 70005 plays exactly four times at home in the season, three at its own ground and once
# elsewhere, so its usual ground is decided and the odd match out is neutral. Southport's two
# extra home matches bring it to three, one short, so none of its matches is called neutral.
NEUTRAL_VENUE_MINIMUM_FIXTURES = (
    ExampleFixture(FIXTURE_STAGE_ID, 70005, SOUTHPORT_TEAM, 93, LEAGUE_KICK_OFF_SLOT, 7, True, 10),
    ExampleFixture(FIXTURE_STAGE_ID, 70005, SOUTHPORT_TEAM, 100, LEAGUE_KICK_OFF_SLOT, 8, True, 10),
    ExampleFixture(FIXTURE_STAGE_ID, 70005, SOUTHPORT_TEAM, 107, LEAGUE_KICK_OFF_SLOT, 9, True, 10),
    ExampleFixture(
        FIXTURE_STAGE_ID, 70005, SOUTHPORT_TEAM, 114, LEAGUE_KICK_OFF_SLOT, 10, True, 99
    ),
    ExampleFixture(
        FIXTURE_STAGE_ID, SOUTHPORT_TEAM, 70005, 121, LEAGUE_KICK_OFF_SLOT, 11, True, 20
    ),
    ExampleFixture(
        FIXTURE_STAGE_ID, SOUTHPORT_TEAM, 70005, 128, LEAGUE_KICK_OFF_SLOT, 12, True, 20
    ),
)
# A stray that repeats the calendar's first record exactly: same teams, same day and same
# kick-off slot. Only its match record id differs, which is not what makes a record a copy.
DUPLICATE_STRAY_FIXTURE = MAIN_CLUSTER_FIXTURES[0]


def fixture_blob(example: ExampleFixture, match_record_id: int) -> bytes:
    """One fixture calendar record with its lead-in bytes."""
    return fixture_record_bytes(
        stage_id=example.stage_id,
        stadium_ordinal=example.stadium_ordinal,
        home_team_id=example.home_team_id,
        away_team_id=example.away_team_id,
        day_of_year=example.day_of_year,
        year=FIXTURE_KICK_OFF_YEAR,
        time_slot=example.time_slot,
        season_start_year=example.season_start_year,
        match_record_id=match_record_id,
        round_index=example.round_index,
        played=example.played,
        date2=FIXTURE_DATE2,
        phase=FIXTURE_PHASE,
        leg=FIXTURE_LEG,
        r39_42=FIXTURE_R39_42,
        match_rules_template=FIXTURE_MATCH_RULES_TEMPLATE,
        r47_54=FIXTURE_R47_54,
    )


# Stage-keyed results: the records that fill a fixture's goals. They sit in the span after the
# league tables, and in a `news` section the fragment carries only when a test writes results
# into it, so every save built without them holds no score at all.
NEWS_SECTION_NAME = "news"
NEWS_SECTION_SCHEMA = 11
RESULT_SEPARATOR_BYTES = 32
RESULT_R22 = STAGE_RESULT_R22


@dataclass(frozen=True)
class ExampleResult:
    """One stage-keyed result record to write into a save.

    `lead_byte`, `sentinel` and `zero_byte` carry the values a sound record holds, so a test
    that overrides one of them writes a record the locator has to turn away.
    """

    stage_id: int
    home_team_id: int
    away_team_id: int
    day_of_year: int
    home_goals: int
    away_goals: int
    year: int = FIXTURE_KICK_OFF_YEAR
    r22: int = STAGE_RESULT_R22
    lead_byte: int = STAGE_RESULT_LEAD_BYTE
    sentinel: int = STAGE_RESULT_SENTINEL
    zero_byte: int = 0


def result_blob(example: ExampleResult) -> bytes:
    """One 27-byte stage-keyed result record."""
    return stage_result_bytes(
        stage_id=example.stage_id,
        home_team_id=example.home_team_id,
        away_team_id=example.away_team_id,
        day_of_year=example.day_of_year,
        year=example.year,
        home_goals=example.home_goals,
        away_goals=example.away_goals,
        r22=example.r22,
        lead_byte=example.lead_byte,
        sentinel=example.sentinel,
        zero_byte=example.zero_byte,
    )


def results_payload(results: Sequence[ExampleResult]) -> bytes:
    """The result records back to back, separated so each reads as its own record."""
    if not results:
        return b""
    return span_payloads(
        *(result_blob(example) for example in results), separator_bytes=RESULT_SEPARATOR_BYTES
    )


# Extra calendar records the league-table tests add, so every club of the example table plays
# in the same competition. Without them the vote sees competitions 900 and 901 covering two of
# the three members each and settles the tie on the lower id, which is a poor thing for a test
# of the vote to rest on.
TABLE_VOTE_FIXTURES = (
    ExampleFixture(
        FIXTURE_STAGE_ID, ATHLETIC_TEAM_A, SOUTHPORT_TEAM, 135, LEAGUE_KICK_OFF_SLOT, 13, True, 10
    ),
    ExampleFixture(
        FIXTURE_STAGE_ID,
        NORTHBRIDGE_TEAM_A,
        ATHLETIC_TEAM_A,
        142,
        LEAGUE_KICK_OFF_SLOT,
        14,
        True,
        HOME_STADIUM_ORDINAL,
    ),
)

# League tables: the blocks sit in the span after the fixture records. Each block stores its
# own place in its table in the first of its head bytes, counting 0 upwards and starting again
# where the next table begins, and that is the only thing that tells one table from the next.
TABLE_SEPARATOR_BYTES = 64
# Plain spacing between two tables. The distance between blocks is deliberately not what
# separates them, so this is only realistic padding and no reader consults it.
BETWEEN_TABLE_BYTES = 4096
TABLE_HEAD_BYTES = bytes(range(19))
# A second copy of a block, carrying different head bytes and identical in every field fmsave
# decodes, which is exactly how the save stores its own repeated copies of a block.
DUPLICATE_TABLE_HEAD_BYTES = bytes(range(19, 38))
TABLE_ROUNDS_PER_VENUE = 2
GROUP_B_ROUNDS_PER_VENUE = 1
# A team id above the layout's range, so no club can ever be joined to it.
OUT_OF_RANGE_TABLE_TEAM_ID = 3_000_000
DIVISION_FIRST_TEAM_ID = 71_001
DIVISION_CLUB_COUNT = 20


def stored_index_head_bytes(stored_index: int, head_bytes: bytes = TABLE_HEAD_BYTES) -> bytes:
    """`head_bytes` with the first byte set to the block's own place in its table.

    The save counts each block's place in its table there, from 0 upwards, and starts again at
    0 where the next table begins, so a table whose blocks do not count on is read as several
    tables and two tables whose counts happen to chain are read as one.
    """
    return bytes((stored_index,)) + head_bytes[1:]


def table_group_a_blocks(head_bytes: bytes = TABLE_HEAD_BYTES) -> list[bytes]:
    """One table of three clubs: Northbridge's first team, Southport and Example Athletic.

    The three blocks carry stored indexes 0, 1 and 2, which is what makes them one table
    rather than three tables of one club each.

    Only the first block takes `head_bytes`, so passing different bytes gives a copy of that
    block which differs from the original in nothing fmsave decodes.
    """
    return [
        table_block_bytes(
            team_id=NORTHBRIDGE_TEAM_A,
            rounds_per_venue=TABLE_ROUNDS_PER_VENUE,
            total={
                "played": 4,
                "won": 3,
                "lost": 1,
                "goals_for": 9,
                "goals_against": 4,
                "points": 9,
            },
            home={"played": 2, "won": 2, "goals_for": 5, "goals_against": 2, "points": 6},
            away={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 4,
                "goals_against": 2,
                "points": 3,
            },
            first_half={"played": 2, "won": 2, "goals_for": 5, "goals_against": 2, "points": 6},
            second_half={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 4,
                "goals_against": 2,
                "points": 3,
            },
            matches=[
                {
                    "key": SOUTHPORT_TEAM,
                    "played": 1,
                    "won": 1,
                    "goals_for": 3,
                    "goals_against": 1,
                    "points": 3,
                },
                {
                    "key": SOUTHPORT_TEAM,
                    "played": 1,
                    "won": 1,
                    "goals_for": 2,
                    "goals_against": 1,
                    "points": 3,
                },
                None,
                {
                    "key": ATHLETIC_TEAM_A,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 1,
                    "goals_against": 2,
                    "points": 0,
                },
            ],
            head_bytes=head_bytes,
        ),
        table_block_bytes(
            team_id=SOUTHPORT_TEAM,
            rounds_per_venue=TABLE_ROUNDS_PER_VENUE,
            total={
                "played": 4,
                "won": 1,
                "lost": 3,
                "goals_for": 5,
                "goals_against": 9,
                "points": 3,
            },
            home={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 4,
                "points": 3,
            },
            away={
                "played": 2,
                "won": 0,
                "lost": 2,
                "goals_for": 2,
                "goals_against": 5,
                "points": 0,
            },
            first_half={
                "played": 2,
                "won": 0,
                "lost": 2,
                "goals_for": 2,
                "goals_against": 5,
                "points": 0,
            },
            second_half={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 4,
                "points": 3,
            },
            matches=[
                {
                    "key": NORTHBRIDGE_TEAM_A,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 1,
                    "goals_against": 2,
                    "points": 0,
                },
                {
                    "key": ATHLETIC_TEAM_A,
                    "played": 1,
                    "won": 1,
                    "goals_for": 2,
                    "goals_against": 1,
                    "points": 3,
                },
                {
                    "key": NORTHBRIDGE_TEAM_A,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 1,
                    "goals_against": 3,
                    "points": 0,
                },
                None,
            ],
            head_bytes=stored_index_head_bytes(1),
        ),
        table_block_bytes(
            team_id=ATHLETIC_TEAM_A,
            rounds_per_venue=TABLE_ROUNDS_PER_VENUE,
            total={
                "played": 4,
                "won": 2,
                "lost": 2,
                "goals_for": 6,
                "goals_against": 7,
                "points": 6,
            },
            home={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 3,
                "points": 3,
            },
            away={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 4,
                "points": 3,
            },
            first_half={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 3,
                "points": 3,
            },
            second_half={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 3,
                "goals_against": 4,
                "points": 3,
            },
            matches=[
                {
                    "key": NORTHBRIDGE_TEAM_A,
                    "played": 1,
                    "won": 1,
                    "goals_for": 2,
                    "goals_against": 1,
                    "points": 3,
                },
                None,
                {
                    "key": SOUTHPORT_TEAM,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 1,
                    "goals_against": 2,
                    "points": 0,
                },
                None,
            ],
            head_bytes=stored_index_head_bytes(2),
        ),
    ]


def table_group_b_blocks() -> list[bytes]:
    """A second table, of Northbridge's reserve team alone, whose one match was drawn."""
    return [
        table_block_bytes(
            team_id=NORTHBRIDGE_TEAM_B,
            rounds_per_venue=GROUP_B_ROUNDS_PER_VENUE,
            total={
                "played": 1,
                "drawn": 1,
                "won": 0,
                "goals_for": 1,
                "goals_against": 1,
                "points": 1,
            },
            home={
                "played": 1,
                "drawn": 1,
                "won": 0,
                "goals_for": 1,
                "goals_against": 1,
                "points": 1,
            },
            away={"played": 0, "won": 0},
            first_half={
                "played": 1,
                "drawn": 1,
                "won": 0,
                "goals_for": 1,
                "goals_against": 1,
                "points": 1,
            },
            second_half={"played": 0, "won": 0},
            matches=[
                {
                    "key": NORTHBRIDGE_TEAM_A,
                    "played": 1,
                    "drawn": 1,
                    "won": 0,
                    "goals_for": 1,
                    "goals_against": 1,
                    "points": 1,
                },
                None,
            ],
        )
    ]


def out_of_range_table_blocks() -> list[bytes]:
    """A table of one club whose team id is above the layout's range, so it joins to nothing."""
    return [
        table_block_bytes(
            team_id=OUT_OF_RANGE_TABLE_TEAM_ID,
            rounds_per_venue=GROUP_B_ROUNDS_PER_VENUE,
            total={"played": 1, "won": 1, "goals_for": 2, "goals_against": 0, "points": 3},
            home={"played": 1, "won": 1, "goals_for": 2, "goals_against": 0, "points": 3},
            away={"played": 0, "won": 0},
            first_half={"played": 1, "won": 1, "goals_for": 2, "goals_against": 0, "points": 3},
            second_half={"played": 0, "won": 0},
            matches=[None, None],
        )
    ]


def division_table_blocks(
    *, club_count: int = DIVISION_CLUB_COUNT, rounds_per_venue: int = DIVISION_CLUB_COUNT - 1
) -> list[bytes]:
    """A table shaped like a division: `club_count` clubs each playing the others twice.

    The blocks carry stored indexes 0 upwards, so they are one table however many there are.

    With `rounds_per_venue` one short of `club_count - 1` the same clubs no longer have that
    shape, which is what the division count must notice.
    """
    return [
        table_block_bytes(
            team_id=DIVISION_FIRST_TEAM_ID + position,
            rounds_per_venue=rounds_per_venue,
            total={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 2,
                "goals_against": 2,
                "points": 3,
            },
            home={"played": 1, "won": 1, "goals_for": 2, "goals_against": 1, "points": 3},
            away={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 1,
                "points": 0,
            },
            first_half={"played": 1, "won": 1, "goals_for": 2, "goals_against": 1, "points": 3},
            second_half={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 1,
                "points": 0,
            },
            matches=[None] * (2 * rounds_per_venue),
            head_bytes=stored_index_head_bytes(position),
        )
        for position in range(club_count)
    ]


def twin_table_blocks() -> list[bytes]:
    """A second table holding the same three clubs as group A, with results of its own.

    The counters differ from group A's in every row, so nothing here is dropped as a repeated
    copy; what the two tables share is only their set of member clubs, which is what makes a
    run of these blocks match two tables at once and so name no competition.
    """
    return [
        table_block_bytes(
            team_id=team_id,
            rounds_per_venue=GROUP_B_ROUNDS_PER_VENUE,
            total={"played": 2, "won": 2, "goals_for": 6, "goals_against": 0, "points": 6},
            home={"played": 1, "won": 1, "goals_for": 3, "goals_against": 0, "points": 3},
            away={"played": 1, "won": 1, "goals_for": 3, "goals_against": 0, "points": 3},
            first_half={"played": 1, "won": 1, "goals_for": 3, "goals_against": 0, "points": 3},
            second_half={"played": 1, "won": 1, "goals_for": 3, "goals_against": 0, "points": 3},
            matches=[None, None],
            head_bytes=stored_index_head_bytes(position),
        )
        for position, team_id in enumerate((NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, ATHLETIC_TEAM_A))
    ]


# A table whose rows account for exactly the matches the calendar holds for their clubs, which
# is what puts a table in step with one season and so lets the calendar decide its venues. The
# two clubs meet twice in competition 902, once at each ground, and each row's two slots carry
# the scores of those two meetings.
VENUE_TABLE_TEAM_A = NORTHBRIDGE_TEAM_B
VENUE_TABLE_TEAM_B = 70004
VENUE_STAGE_ID = 6
VENUE_ROUNDS_PER_VENUE = 1
VENUE_FIRST_MATCH_DAY = 100
VENUE_SECOND_MATCH_DAY = 107
VENUE_FIRST_MATCH_GOALS = (2, 0)
VENUE_SECOND_MATCH_GOALS = (1, 0)
VENUE_EARLIER_SEASON = FIXTURE_SEASON_START_YEAR - 1
VENUE_EARLIER_FIRST_MATCH_DAY = 20
VENUE_EARLIER_SECOND_MATCH_DAY = 27


def venue_table_blocks() -> list[bytes]:
    """Two blocks, stored indexes 0 and 1, whose four slots the calendar can all decide."""
    return [
        table_block_bytes(
            team_id=VENUE_TABLE_TEAM_A,
            rounds_per_venue=VENUE_ROUNDS_PER_VENUE,
            total={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 2,
                "goals_against": 1,
                "points": 3,
            },
            home={"played": 1, "won": 1, "goals_for": 2, "goals_against": 0, "points": 3},
            away={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 1,
                "points": 0,
            },
            first_half={"played": 1, "won": 1, "goals_for": 2, "goals_against": 0, "points": 3},
            second_half={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 1,
                "points": 0,
            },
            matches=[
                {
                    "key": VENUE_TABLE_TEAM_B,
                    "played": 1,
                    "won": 1,
                    "goals_for": 2,
                    "goals_against": 0,
                    "points": 3,
                },
                {
                    "key": VENUE_TABLE_TEAM_B,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 0,
                    "goals_against": 1,
                    "points": 0,
                },
            ],
            head_bytes=stored_index_head_bytes(0),
        ),
        table_block_bytes(
            team_id=VENUE_TABLE_TEAM_B,
            rounds_per_venue=VENUE_ROUNDS_PER_VENUE,
            total={
                "played": 2,
                "won": 1,
                "lost": 1,
                "goals_for": 1,
                "goals_against": 2,
                "points": 3,
            },
            home={"played": 1, "won": 1, "goals_for": 1, "goals_against": 0, "points": 3},
            away={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 2,
                "points": 0,
            },
            first_half={"played": 1, "won": 1, "goals_for": 1, "goals_against": 0, "points": 3},
            second_half={
                "played": 1,
                "won": 0,
                "lost": 1,
                "goals_for": 0,
                "goals_against": 2,
                "points": 0,
            },
            matches=[
                {
                    "key": VENUE_TABLE_TEAM_A,
                    "played": 1,
                    "won": 1,
                    "goals_for": 1,
                    "goals_against": 0,
                    "points": 3,
                },
                {
                    "key": VENUE_TABLE_TEAM_A,
                    "played": 1,
                    "won": 0,
                    "lost": 1,
                    "goals_for": 0,
                    "goals_against": 2,
                    "points": 0,
                },
            ],
            head_bytes=stored_index_head_bytes(1),
        ),
    ]


VENUE_TABLE_BLOCKS = venue_table_blocks()
# The two meetings the table above accounts for, both played, one at each club's own ground.
VENUE_FIXTURES = (
    ExampleFixture(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_A,
        VENUE_TABLE_TEAM_B,
        VENUE_FIRST_MATCH_DAY,
        LEAGUE_KICK_OFF_SLOT,
        20,
        True,
        HOME_STADIUM_ORDINAL,
    ),
    ExampleFixture(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_B,
        VENUE_TABLE_TEAM_A,
        VENUE_SECOND_MATCH_DAY,
        LEAGUE_KICK_OFF_SLOT,
        21,
        True,
        AWAY_STADIUM_ORDINAL,
    ),
)
# The scores of those two meetings. Without them both meetings are played and unscored, so no
# slot of the table can be decided from a score at all.
VENUE_RESULTS = (
    ExampleResult(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_A,
        VENUE_TABLE_TEAM_B,
        VENUE_FIRST_MATCH_DAY,
        *VENUE_FIRST_MATCH_GOALS,
    ),
    ExampleResult(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_B,
        VENUE_TABLE_TEAM_A,
        VENUE_SECOND_MATCH_DAY,
        *VENUE_SECOND_MATCH_GOALS,
    ),
)
# The same two clubs meeting twice a season earlier, so the venue table's row counts account
# for two seasons rather than one and no season can be said to be the one it describes.
VENUE_EARLIER_SEASON_FIXTURES = (
    ExampleFixture(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_A,
        VENUE_TABLE_TEAM_B,
        VENUE_EARLIER_FIRST_MATCH_DAY,
        LEAGUE_KICK_OFF_SLOT,
        22,
        True,
        HOME_STADIUM_ORDINAL,
        VENUE_EARLIER_SEASON,
    ),
    ExampleFixture(
        VENUE_STAGE_ID,
        VENUE_TABLE_TEAM_B,
        VENUE_TABLE_TEAM_A,
        VENUE_EARLIER_SECOND_MATCH_DAY,
        LEAGUE_KICK_OFF_SLOT,
        23,
        True,
        AWAY_STADIUM_ORDINAL,
        VENUE_EARLIER_SEASON,
    ),
)


def career_table_payload(
    *,
    duplicate_head_bytes: Sequence[bytes] = (),
    extra_groups: Sequence[Sequence[bytes]] = (),
    leading_rules_blocks: Sequence[bytes] = (),
) -> bytes:
    """The example tables, each starting its own run of stored indexes at zero.

    A copy named in `duplicate_head_bytes` is written inside the first table, right where the
    save writes its own copies: immediately after the block it repeats, where its own stored
    index breaks the run and would split the table around it were it not dropped first.

    A block named in `leading_rules_blocks` is written immediately in front of the table of the
    same position, which is how a real save interleaves its rules blocks with its tables.
    """
    first_group = table_group_a_blocks()
    for position, head_bytes in enumerate(duplicate_head_bytes, start=1):
        first_group.insert(position, table_group_a_blocks(head_bytes=head_bytes)[0])
    groups = [first_group, table_group_b_blocks(), *(list(group) for group in extra_groups)]
    payloads: list[bytes] = []
    for position, group in enumerate(groups):
        payload = span_payloads(*group, separator_bytes=TABLE_SEPARATOR_BYTES)
        if position < len(leading_rules_blocks):
            payload = leading_rules_blocks[position] + bytes(RULES_SEPARATOR_BYTES) + payload
        payloads.append(payload)
    return bytes(BETWEEN_TABLE_BYTES).join(payloads)


# Competition rules: two preamble blocks sit in the span after the league tables. The first
# writes its promotion quad twice, as the save does on about 95% of blocks, and the second
# writes two copies that differ, which is what leaves the four quad fields empty.
RULES_SEPARATOR_BYTES = 256
RULES_PROMOTION_PLACES = 2
RULES_PLAYOFF_PLACES = 4
RULES_PROMOTION_BYTE2 = 1
RULES_RELEGATION_PLACES = 3
RULES_TIE_BREAKS = (1, 5, 9)
RULES_PRIZE_MONEY = (1_000_000, 500_000, 250_000)
RULES_ROUND_YEAR = 2031
# Day 51 of 2031 is 20 February; the rounds run a week apart and the last is a match short.
RULES_ROUND_DAYS = (51, 58, 65)
RULES_ROUND_MATCH_COUNTS = (10, 10, 9)


def career_rules_rounds() -> list[dict[str, int]]:
    return [
        {"day_of_year": day, "year": RULES_ROUND_YEAR, "match_count": match_count}
        for day, match_count in zip(RULES_ROUND_DAYS, RULES_ROUND_MATCH_COUNTS, strict=True)
    ]


def career_rules_blocks() -> list[bytes]:
    """One rules preamble whose quad is doubled, then one whose two copies differ."""
    rounds = career_rules_rounds()
    return [
        rules_preamble_bytes(
            promotion=RULES_PROMOTION_PLACES,
            playoff=RULES_PLAYOFF_PLACES,
            promotion_byte2=RULES_PROMOTION_BYTE2,
            relegation=RULES_RELEGATION_PLACES,
            tie_breaks=RULES_TIE_BREAKS,
            prize_money=RULES_PRIZE_MONEY,
            rounds=rounds,
            double_quad=double_quad,
        )
        for double_quad in (True, False)
    ]


def career_rules_payload() -> bytes:
    """Both rules preambles back to back, which is where a save with no table would hold them."""
    return span_payloads(*career_rules_blocks(), separator_bytes=RULES_SEPARATOR_BYTES)


def career_span_payload(
    extra_fixtures: Sequence[ExampleFixture] = (),
    extra_strays: Sequence[ExampleFixture] = (),
    *,
    table_duplicate_head_bytes: Sequence[bytes] = (),
    extra_table_groups: Sequence[Sequence[bytes]] = (),
    span_results: Sequence[ExampleResult] = (),
    interleave_rules: bool = False,
) -> bytes:
    """The calendar, a gap, a stray copy of two, the league tables, the rules, then any results.

    With `interleave_rules` the two rules preambles move in front of the first two tables
    instead, one each, which is the order a real save lays them out in: the run of table blocks
    that follows a preamble is then the table that preamble belongs to.
    """
    calendar_blobs = [
        fixture_blob(example, FIRST_MATCH_RECORD_ID + position)
        for position, example in enumerate((*MAIN_CLUSTER_FIXTURES, *extra_fixtures))
    ]
    stray_blobs = [
        fixture_blob(example, STRAY_MATCH_RECORD_ID + position)
        for position, example in enumerate((*STRAY_FIXTURES, *extra_strays))
    ]
    payload = (
        span_payloads(*calendar_blobs, separator_bytes=FIXTURE_SEPARATOR_BYTES)
        + bytes(STRAY_CLUSTER_GAP_BYTES)
        + span_payloads(*stray_blobs, separator_bytes=FIXTURE_SEPARATOR_BYTES)
        + bytes(STRAY_CLUSTER_GAP_BYTES)
        + career_table_payload(
            duplicate_head_bytes=table_duplicate_head_bytes,
            extra_groups=extra_table_groups,
            leading_rules_blocks=career_rules_blocks() if interleave_rules else (),
        )
    )
    if not interleave_rules:
        payload += bytes(BETWEEN_TABLE_BYTES) + career_rules_payload()
    if span_results:
        payload += bytes(RESULT_SEPARATOR_BYTES) + results_payload(span_results)
    return payload


# Two transfer windows, and a third dated record that carries no closing time, which is what
# most of the tagged stream's dated records look like and must not be read as a window.
SUMMER_WINDOW_OPENS = (1, 7, 2000)
SUMMER_WINDOW_CLOSES = (31, 8, 2000)
SUMMER_WINDOW_CLOSE_TIME = 2400
SUMMER_WINDOW_TYPE = 1
# The winter window opens in the calendar year after the season starts, so its year is 2001.
WINTER_WINDOW_OPENS = (1, 1, 2001)
WINTER_WINDOW_CLOSES = (31, 1, 2001)
WINTER_WINDOW_CLOSE_TIME = 2300
DATED_RECORD_OPENS = (5, 3, 2000)
DATED_RECORD_CLOSES = (6, 4, 2000)


def career_tagged_stream() -> bytes:
    """The rules database's tagged stream: two windows, then a dated record that is not one."""
    return (
        transfer_window_bytes(
            opens=SUMMER_WINDOW_OPENS,
            closes=SUMMER_WINDOW_CLOSES,
            close_time=SUMMER_WINDOW_CLOSE_TIME,
            window_type=SUMMER_WINDOW_TYPE,
        )
        + transfer_window_bytes(
            opens=WINTER_WINDOW_OPENS,
            closes=WINTER_WINDOW_CLOSES,
            close_time=WINTER_WINDOW_CLOSE_TIME,
        )
        + transfer_window_bytes(
            opens=DATED_RECORD_OPENS, closes=DATED_RECORD_CLOSES, close_time=None
        )
    )


def career_game_db(
    *,
    duplicate_club_name: bool = False,
    game_db_results: Sequence[ExampleResult] = (),
    stadium_table: bool = True,
    staff_affiliate: bool = False,
    extra_staff: bytes = b"",
) -> bytes:
    """The game database. `game_db_results` writes result records into a region no result
    reader may scan, so a reader that widened its regions is caught by the score appearing.
    `stadium_table=False` leaves the stadium table out, so every reader that needs a ground
    has nothing to read. `extra_staff` is written at the start of the staff region, in front
    of the example staff.
    """
    clubs = example_clubs(staff_affiliate=staff_affiliate, duplicate_club_name=duplicate_club_name)
    payload = (
        name_pools_bytes(FIRST_NAMES, SURNAMES, COMMON_NAMES)
        + clubs_region_bytes(clubs, competition_id_pairs=career_competition_id_pairs())
        + career_tagged_stream()
        + (stadium_table_bytes(career_stadium_rows()) if stadium_table else b"")
        + bytes(64)
        + results_payload(game_db_results)
        + bytes(64)
        + manager_region_bytes()
        + player_a_bytes()
        + player_b_bytes()
        + player_c_bytes()
        + player_d_bytes()
        + extra_staff
        + staff_region_bytes(staff_affiliate=staff_affiliate)
        # The save keeps its stage table in the last stretch of game_db, so it goes last here.
        + stage_table_bytes(career_stage_rows())
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


# The per-match directory entries. A save carries hundreds of them; the fragment carries the
# three shapes a reader of them has to tell apart: an entry that is not a match file at all, an
# `.apm` entry whose payload holds a shorter decoy chain before the table, and an `.scm` entry
# holding the same table.
PLAIN_ATTACHMENT_PAYLOAD = b"attachment"
CAREER_ATTACHMENTS: tuple[tuple[str, str, bytes], ...] = (
    ("1_2_3", ".apm", PLAIN_ATTACHMENT_PAYLOAD),
    (
        "1_2_4",
        ".apm",
        match_file_body(
            (injury_type_entries(CAREER_INJURY_TYPES),),
            decoy_entries=(injury_type_entries(DECOY_INJURY_TYPES),),
        ),
    ),
    (
        "1_2_5",
        ".scm",
        match_file_body((injury_type_entries(CAREER_INJURY_TYPES),), extension=".scm"),
    ),
)


# Affiliate groups. The first group pairs two clubs the example save lists; the second pairs a
# club it lists with a public club index no club record claims, so one member resolves to None.
FEEDER_SECTION_NAME = "feeder_man"
UNCLAIMED_CLUB_INDEX = 9
CAREER_AFFILIATE_GROUPS: tuple[tuple[int, ...], ...] = ((1, 2), (4, UNCLAIMED_CLUB_INDEX))

# The job centre. Three vacancies: one at a club with a competition, a league position and a
# time slot on both dates; one with no competition, no position and the 0/1 flag set; and one
# at a team no club lists. Every advertised date is on or before the in-game date of 1 March
# 2031 (day 60), and the three are written in ascending advertised order, as a save stores them.
JOB_CENTRE_SECTION_NAME = "job_centre"
FIRST_JOB_ROLE = 16
SECOND_JOB_ROLE = 14
THIRD_JOB_ROLE = 2
FIRST_JOB_ADVERTISED_DAY = 20
SECOND_JOB_ADVERTISED_DAY = 30
THIRD_JOB_ADVERTISED_DAY = 45
FIRST_JOB_ADVERTISED_SLOT = 33
FIRST_JOB_SECOND_DATE_SLOT = 5
JOB_YEAR = 2031
FIRST_JOB_U20 = 57
SECOND_JOB_U20 = 12
THIRD_JOB_U20 = 80
FIRST_JOB_POSITION = 3
THIRD_JOB_POSITION = 12


def career_job_records() -> tuple[bytes, ...]:
    """The three job-centre records, in the order the save stores them."""
    return (
        job_record_bytes(
            team_id=NORTHBRIDGE_TEAM_A,
            role=FIRST_JOB_ROLE,
            advertised=packed_date(FIRST_JOB_ADVERTISED_DAY, JOB_YEAR, FIRST_JOB_ADVERTISED_SLOT),
            date_12=packed_date(40, JOB_YEAR, FIRST_JOB_SECOND_DATE_SLOT),
            competition_id=FIRST_COMPETITION_ID,
            u20=FIRST_JOB_U20,
            league_position=FIRST_JOB_POSITION,
            flag=0,
        ),
        job_record_bytes(
            team_id=SOUTHPORT_TEAM,
            role=SECOND_JOB_ROLE,
            advertised=packed_date(SECOND_JOB_ADVERTISED_DAY, JOB_YEAR),
            date_12=packed_date(33, JOB_YEAR),
            competition_id=NO_JOB_COMPETITION,
            u20=SECOND_JOB_U20,
            league_position=0,
            flag=1,
        ),
        job_record_bytes(
            team_id=UNREGISTERED_FIXTURE_TEAM_ID,
            role=THIRD_JOB_ROLE,
            advertised=packed_date(THIRD_JOB_ADVERTISED_DAY, JOB_YEAR),
            date_12=packed_date(48, JOB_YEAR),
            competition_id=SECOND_COMPETITION_ID,
            u20=THIRD_JOB_U20,
            league_position=THIRD_JOB_POSITION,
            flag=0,
        ),
    )


# The tactics section. Two team blocks, one per Northbridge team: the first team carries a
# named selection, seven player selectors and two user tactics of eleven slots each, and the
# second carries nothing at all, which is what every team but the first looks like on a real
# save. Only the first team's routines are named.
TACTICS_SECTION_NAME = "tactics_man"
TACTICS_SELECTION_LABEL = "Example XI"
TACTICS_SELECTION_SLOTS = (12, 14, 15)
TACTICS_LIST_A = (14, 12)
TACTICS_LIST_B = (15,)
TACTICS_SINGLE_SELECTOR = 14
FIRST_TACTIC_NAME = "Example 442"
SECOND_TACTIC_NAME = "Example 433"
TACTIC_STYLE_NAME = "Example Style"
TACTIC_STYLE_CODE = b"EXMP"
FIRST_TACTIC_INSTRUCTIONS = bytes(
    [4, 21, 6, 6, 2, 3, 30, 48, 40, 41, 42, 84, 43, 44, 45, 46, 47, 0, 255]
)
SECOND_TACTIC_MENTALITY = 4
SECOND_TACTIC_INSTRUCTION_11 = 148
# One position bit per tactic slot, with the two centre-back slots and the two wide slots
# sharing a bit and telling each other apart by a column flag.
TACTIC_SLOT_BITS = (0, 5, 3, 3, 6, 10, 7, 7, 12, 14, 14)
TACTIC_LEFT_COLUMN_BIT = 20
TACTIC_RIGHT_COLUMN_BIT = 21
TACTIC_IN_POSSESSION_ROLE_BITS = 1 << 4
TACTIC_OUT_OF_POSSESSION_ROLE_BITS = 1 << 3
FIRST_UNIT_HEAD = 0
FIRST_UNIT_FIRST_BITS = 1
FIRST_UNIT_SECOND_BITS = 1 << 33
SECOND_UNIT_HEAD = 0x0A
SECOND_UNIT_FIRST_BITS = 0x0102
SECOND_UNIT_SECOND_BITS = 1 << 70
FIRST_ROUTINE_NAME = "Example Corner"
FOURTH_ROUTINE_NAME = "Example Free Kick"


def career_routine_names() -> tuple[str | None, ...]:
    """The first team's twenty routine slots: two named, the other eighteen empty."""
    names: list[str | None] = [None] * ROUTINE_COUNT
    names[0] = FIRST_ROUTINE_NAME
    names[3] = FOURTH_ROUTINE_NAME
    return tuple(names)


def career_tactic_slots() -> tuple[tuple[bytes, bytes], ...]:
    """The eleven slot-block pairs every career tactic carries, in stored order."""
    first_unit = setting_unit_bytes(
        head_byte=FIRST_UNIT_HEAD,
        first_bits=FIRST_UNIT_FIRST_BITS,
        second_bits=FIRST_UNIT_SECOND_BITS,
    )
    second_unit = setting_unit_bytes(
        head_byte=SECOND_UNIT_HEAD,
        first_bits=SECOND_UNIT_FIRST_BITS,
        second_bits=SECOND_UNIT_SECOND_BITS,
    )
    pairs: list[tuple[bytes, bytes]] = []
    for slot_number, position_bit in enumerate(TACTIC_SLOT_BITS):
        mask = 1 << position_bit
        if slot_number == 2:
            mask |= 1 << TACTIC_LEFT_COLUMN_BIT
        elif slot_number == 3:
            mask |= 1 << TACTIC_RIGHT_COLUMN_BIT
        pairs.append(
            (
                slot_block_bytes(
                    mask=mask,
                    units=(first_unit, second_unit),
                    role_bits=TACTIC_IN_POSSESSION_ROLE_BITS,
                ),
                slot_block_bytes(
                    mask=mask,
                    units=(first_unit,),
                    role_bits=TACTIC_OUT_OF_POSSESSION_ROLE_BITS,
                    position_index=slot_number,
                ),
            )
        )
    return tuple(pairs)


def career_tactic_records() -> tuple[bytes, ...]:
    """The first team's two user tactics, which differ in mentality and one further byte."""
    second_instructions = bytearray(FIRST_TACTIC_INSTRUCTIONS)
    second_instructions[2] = SECOND_TACTIC_MENTALITY
    second_instructions[11] = SECOND_TACTIC_INSTRUCTION_11
    slots = career_tactic_slots()
    return (
        tactic_record_bytes(
            name=FIRST_TACTIC_NAME,
            team_instructions=FIRST_TACTIC_INSTRUCTIONS,
            style_name=TACTIC_STYLE_NAME,
            style_code=TACTIC_STYLE_CODE,
            slots=slots,
        ),
        tactic_record_bytes(
            name=SECOND_TACTIC_NAME,
            team_instructions=bytes(second_instructions),
            style_name=TACTIC_STYLE_NAME,
            style_code=TACTIC_STYLE_CODE,
            slots=slots,
        ),
    )


def career_tactics_body(
    *,
    selector: int = MANAGER_SELECTOR,
    first_team_records: Sequence[bytes] | None = None,
    first_team_routines: Sequence[str | None] | None = None,
    second_team_routines: Sequence[str | None] = (None,) * ROUTINE_COUNT,
) -> bytes:
    """The whole `tactics_man` section of the career fragment.

    The tactic records and either team's routine slots can be replaced, so a test can give the
    reader a record whose walk breaks, a preset record or a block short of a routine.
    """
    records = career_tactic_records() if first_team_records is None else tuple(first_team_records)
    routines = career_routine_names() if first_team_routines is None else first_team_routines
    first_block = (
        selection_part_bytes(
            team_id=NORTHBRIDGE_TEAM_A,
            label=TACTICS_SELECTION_LABEL,
            slots=TACTICS_SELECTION_SLOTS,
            list_a=TACTICS_LIST_A,
            list_b=TACTICS_LIST_B,
            single=TACTICS_SINGLE_SELECTOR,
            tactics_value=HAS_TACTICS_VALUE,
            tactic_count=len(records),
        )
        + b"".join(records)
        + set_piece_area_bytes(routines)
    )
    second_block = selection_part_bytes(
        team_id=NORTHBRIDGE_TEAM_B,
        label="",
        slots=(),
        list_a=(),
        list_b=(),
        single=NO_SELECTOR,
        tactics_value=NO_TACTICS_VALUE,
        tactic_count=0,
    ) + set_piece_area_bytes(second_team_routines)
    return tactics_man_body(selector=selector, blocks=(first_block, second_block))


def career_club_section_frames(
    *, feeder: bytes | None = None, job_centre: bytes | None = None
) -> list[SectionFrame]:
    """The `feeder_man` and `job_centre` sections of the career fragment.

    Either body can be replaced, so a test can give the fragment a section the readers have to
    turn away or an empty one they have to accept.
    """
    return [
        SectionFrame(
            FEEDER_SECTION_NAME,
            feeder_body(CAREER_AFFILIATE_GROUPS) if feeder is None else feeder,
        ),
        SectionFrame(
            JOB_CENTRE_SECTION_NAME,
            job_centre_body(career_job_records()) if job_centre is None else job_centre,
        ),
    ]


# The injury history. Three log rows, oldest first as the save stores them: one at Southport
# for player A carrying both codes and a time slot, one at Northbridge for player C dated
# inside the last month, and one for a selector no player claims. Then three typed rows: one
# for player A dated after the in-game date of 1 March 2031, one for player C carrying a type
# the name table has no entry for, and one with no date at all. One window row goes in each
# window array, the first list holds player A's selector, and the third holds player C's with a
# flag byte, so that the list whose entries are five bytes rather than four is not empty.
INJURY_MANAGER_SECTION_NAME = "injury_manager"
NO_PLAYER_SELECTOR = 999
FIRST_INJURY_LOG_DAY = 306
FIRST_INJURY_LOG_YEAR = 2030
FIRST_INJURY_LOG_SLOT = 33
SECOND_INJURY_LOG_DAY = 51
THIRD_INJURY_LOG_DAY = 56
FIRST_TYPED_INJURY_DAY = 64
FIRST_TYPED_INJURY_SLOT = 33
SECOND_TYPED_INJURY_DAY = 55
INJURY_YEAR = 2031
NAMED_INJURY_TYPE_ID = CAREER_INJURY_TYPES[1][0]
UNNAMED_INJURY_TYPE_ID = 39
FIRST_INJURY_CAUSE = 1
FIRST_INJURY_SEVERITY = 2
SECOND_INJURY_SEVERITY = 3
FLAGGED_LIST_BYTE = 1


def career_injury_window_rows() -> tuple[bytes, ...]:
    """One row for each window array, whose contents no reader keeps."""
    return (
        injury_window_row_bytes(
            first=packed_date(20, INJURY_YEAR),
            second=packed_date(40, INJURY_YEAR),
            selector=PLAYER_A_PINDEX + SELECTOR_OFFSET,
        ),
    )


def career_injury_log_rows() -> tuple[bytes, ...]:
    """The three log rows, oldest first, as the save stores them."""
    return (
        injury_log_row_bytes(
            date=packed_date(FIRST_INJURY_LOG_DAY, FIRST_INJURY_LOG_YEAR, FIRST_INJURY_LOG_SLOT),
            selector=PLAYER_A_PINDEX + SELECTOR_OFFSET,
            team_id=SOUTHPORT_TEAM,
            cause=FIRST_INJURY_CAUSE,
            severity=FIRST_INJURY_SEVERITY,
        ),
        injury_log_row_bytes(
            date=packed_date(SECOND_INJURY_LOG_DAY, INJURY_YEAR),
            selector=PLAYER_C_PINDEX + SELECTOR_OFFSET,
            team_id=NORTHBRIDGE_TEAM_A,
            cause=0,
            severity=SECOND_INJURY_SEVERITY,
        ),
        injury_log_row_bytes(
            date=packed_date(THIRD_INJURY_LOG_DAY, INJURY_YEAR),
            selector=NO_PLAYER_SELECTOR,
            team_id=ATHLETIC_TEAM_A,
            cause=0,
            severity=0,
        ),
    )


def career_typed_injury_rows() -> tuple[bytes, ...]:
    """The three typed rows, in the order the save stores them."""
    return (
        injury_typed_row_bytes(
            date=packed_date(FIRST_TYPED_INJURY_DAY, INJURY_YEAR, FIRST_TYPED_INJURY_SLOT),
            selector=PLAYER_A_PINDEX + SELECTOR_OFFSET,
            type_id=NAMED_INJURY_TYPE_ID,
            r11=2,
            r12=14,
        ),
        injury_typed_row_bytes(
            date=packed_date(SECOND_TYPED_INJURY_DAY, INJURY_YEAR),
            selector=PLAYER_C_PINDEX + SELECTOR_OFFSET,
            type_id=UNNAMED_INJURY_TYPE_ID,
            r11=1,
            r12=3,
        ),
        injury_typed_row_bytes(
            date=NULL_DATE_WORD,
            selector=NO_PLAYER_SELECTOR,
            type_id=NAMED_INJURY_TYPE_ID,
            r11=3,
            r12=1,
        ),
    )


def career_injury_manager() -> bytes:
    """The whole `injury_manager` section body of the career fragment."""
    window_rows = career_injury_window_rows()
    return injury_manager_body(
        window_a=window_rows,
        window_b=window_rows,
        typed=career_typed_injury_rows(),
        log=career_injury_log_rows(),
        lists=(
            (PLAYER_A_PINDEX + SELECTOR_OFFSET,),
            (),
            ((PLAYER_C_PINDEX + SELECTOR_OFFSET, FLAGGED_LIST_BYTE),),
        ),
    )


# Training. One block per team of the managed club, in the order the save stores them: the
# reserve team first, then the first team, which is the one carrying mentoring groups. The
# calendars straddle the in-game date of 1 March 2031 (day 60), so the week starting on day 55
# is the active one for both teams, and the reserve calendar ends on a week with the null date.
# The saved-schedule library sits after the last block, past a run of bytes that is none of its
# own.
TRAINING_SECTION_NAME = "training_man"
TRAINING_YEAR = 2031
FIRST_TRAINING_WEEK_DAY = 48
SECOND_TRAINING_WEEK_DAY = 55
THIRD_TRAINING_WEEK_DAY = 62
TRAINING_WEEK_SLOT = 61
NULL_TRAINING_DATE = bytes(4)
LIGHT_SCHEDULE_NAME = "Example Light"
BALANCED_SCHEDULE_NAME = "Example Balanced"
RECOVERY_SCHEDULE_NAME = "Example Recovery"
TRAINING_HEADER_SELECTOR = 12
FIRST_MENTORING_LABEL = "Group 1"
SECOND_MENTORING_LABEL = "Group 2"
# Player C (pindex 13) and player A (pindex 11), each stored as its pindex plus one.
FIRST_MENTORING_SELECTORS = (14, 12)
# A selector no player record claims, so its member resolves to no player at all.
SECOND_MENTORING_SELECTORS = (999,)
CAREER_SCHEDULE_LIBRARY = (
    ("Example Folder", 17, LIGHT_SCHEDULE_NAME),
    ("Example Folder", 18, RECOVERY_SCHEDULE_NAME),
    ("Other Folder", 19, BALANCED_SCHEDULE_NAME),
)
TRAINING_FILLER_BYTES = b"\x77" * 64


def career_training_blocks() -> tuple[bytes, ...]:
    """The two team blocks, in the order the save stores them."""
    reserve_weeks = (
        training_week_bytes(
            week_start=packed_date(FIRST_TRAINING_WEEK_DAY, TRAINING_YEAR, TRAINING_WEEK_SLOT),
            schedule_name=LIGHT_SCHEDULE_NAME,
        ),
        training_week_bytes(
            week_start=packed_date(SECOND_TRAINING_WEEK_DAY, TRAINING_YEAR),
            schedule_name=LIGHT_SCHEDULE_NAME,
        ),
        # A week whose stored date is the null one, so it decodes to nothing: the reader has to
        # return the week, count it as undated and step over it when it measures week steps.
        training_week_bytes(week_start=NULL_TRAINING_DATE, schedule_name=LIGHT_SCHEDULE_NAME),
    )
    first_team_weeks = (
        training_week_bytes(
            week_start=packed_date(FIRST_TRAINING_WEEK_DAY, TRAINING_YEAR),
            schedule_name=BALANCED_SCHEDULE_NAME,
        ),
        training_week_bytes(
            week_start=packed_date(SECOND_TRAINING_WEEK_DAY, TRAINING_YEAR),
            schedule_name=RECOVERY_SCHEDULE_NAME,
        ),
        training_week_bytes(
            week_start=packed_date(THIRD_TRAINING_WEEK_DAY, TRAINING_YEAR),
            schedule_name=BALANCED_SCHEDULE_NAME,
        ),
    )
    first_team_groups = (
        mentoring_group_bytes(
            number=1,
            label=FIRST_MENTORING_LABEL,
            member_selectors=FIRST_MENTORING_SELECTORS,
        ),
        mentoring_group_bytes(
            number=2,
            label=SECOND_MENTORING_LABEL,
            member_selectors=SECOND_MENTORING_SELECTORS,
        ),
    )
    return (
        training_block_bytes(
            team_id=NORTHBRIDGE_TEAM_B, entries=1, weeks=reserve_weeks, groups=(), last=False
        ),
        training_block_bytes(
            team_id=NORTHBRIDGE_TEAM_A,
            entries=0,
            weeks=first_team_weeks,
            groups=first_team_groups,
            last=True,
        ),
    )


def career_training_section(*, library: bool = True) -> bytes:
    """The whole `training_man` section; without the library nothing after the blocks holds one."""
    after_blocks = TRAINING_FILLER_BYTES
    if library:
        after_blocks += schedule_library_bytes(CAREER_SCHEDULE_LIBRARY)
    return training_man_body(
        header_entries=(
            training_header_entry_bytes(
                selector=TRAINING_HEADER_SELECTOR,
                first_date=packed_date(50, TRAINING_YEAR),
                second_date=packed_date(57, TRAINING_YEAR),
            ),
        ),
        blocks=career_training_blocks(),
        after_blocks=after_blocks,
    )


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
    *,
    duplicate_club_name: bool = False,
    manager_between_jobs: bool = False,
    extra_fixtures: Sequence[ExampleFixture] = (),
    extra_strays: Sequence[ExampleFixture] = (),
    table_duplicate_head_bytes: Sequence[bytes] = (),
    extra_table_groups: Sequence[Sequence[bytes]] = (),
    interleave_rules: bool = False,
    span_results: Sequence[ExampleResult] = (),
    news_results: Sequence[ExampleResult] = (),
    game_db_results: Sequence[ExampleResult] = (),
    attachments: tuple[tuple[str, str, bytes], ...] = CAREER_ATTACHMENTS,
    feeder_section: bytes | None = None,
    job_centre_section: bytes | None = None,
    injury_manager_section: bytes | None = None,
    tactics_section: bytes | None = None,
    training_section: bytes | None = None,
    stadium_table: bool = True,
    staff_affiliate: bool = False,
    extra_staff: bytes = b"",
) -> ContainerFragment:
    """The whole career fragment.

    Args:
        duplicate_club_name: Add a second club (uid 5006) with the same name, "Northbridge FC",
            and the same short name, "Northbridge".
        manager_between_jobs: Give the one human manager no contract and no summary link, so
            no route finds a managed club.
        extra_fixtures: Extra records to add to the fixture calendar, after its own six.
        extra_strays: Extra records to add to the stray run, after its own two.
        table_duplicate_head_bytes: Head bytes for copies of the first league-table block,
            each written immediately after the block it repeats, inside the table that block
            belongs to.
        extra_table_groups: Further league tables, each written after the two the span already
            holds and each starting its own run of stored indexes at zero.
        interleave_rules: Write the two rules preambles in front of the first two tables, one
            each, instead of both after every table. That is the order a real save lays them
            out in, so the table blocks that follow a preamble are the table it belongs to.
        span_results: Stage-keyed result records to write into the span, after the tables.
        news_results: Stage-keyed result records to write into a `news` section, which the
            fragment carries only when this is given, so every other save holds no such
            section and every reader of one has to skip it.
        game_db_results: Stage-keyed result records to write into `game_db`, which no result
            reader may scan; a score from one of these means a reader widened its regions.
        attachments: The `(name, extension, payload)` directory entries that are not sections,
            in directory order. The default carries the three per-match entries
            `CAREER_ATTACHMENTS` describes; an empty tuple gives a save with none at all.
        feeder_section: The whole `feeder_man` section body, in place of the two affiliate
            groups the fragment writes.
        job_centre_section: The whole `job_centre` section body, in place of the three
            vacancies the fragment writes.
        tactics_section: The whole `tactics_man` section body, in place of the two team
            blocks the fragment writes.
        training_section: The whole `training_man` section body, in place of the two team
            blocks and the saved-schedule library the fragment writes.
        injury_manager_section: The whole `injury_manager` section body, in place of the
            three log rows and three typed rows the fragment writes.
        stadium_table: Write the stadium table into `game_db`. False leaves it out, so a
            reader that needs a ground finds no table at all.
        staff_affiliate: Add the B team Northbridge controls, which lists a person Northbridge
            itself pays, and that person's own object.
        extra_staff: Bytes to write at the start of the staff region, in front of the example
            staff objects.
    """
    selector = UNMATCHED_MANAGER_SELECTOR if manager_between_jobs else MANAGER_SELECTOR
    replacements = {
        "game_db": career_game_db(
            duplicate_club_name=duplicate_club_name,
            game_db_results=game_db_results,
            stadium_table=stadium_table,
            staff_affiliate=staff_affiliate,
            extra_staff=extra_staff,
        ),
        "humans": humans_body(count=1, selector=selector),
        "save_game_summary": career_summary(linked=not manager_between_jobs),
    }
    span = span_frames(
        [
            career_span_payload(
                extra_fixtures,
                extra_strays,
                table_duplicate_head_bytes=table_duplicate_head_bytes,
                extra_table_groups=extra_table_groups,
                interleave_rules=interleave_rules,
                span_results=span_results,
            )
        ]
    )
    sections = [
        SectionFrame(
            section.name,
            replacements.get(section.name, section.body),
            section.extension,
            span if section.name == SPAN_SECTION_NAME else section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    sections.extend(
        career_club_section_frames(feeder=feeder_section, job_centre=job_centre_section)
    )
    sections.append(
        SectionFrame(
            INJURY_MANAGER_SECTION_NAME,
            career_injury_manager() if injury_manager_section is None else injury_manager_section,
        )
    )
    sections.append(
        SectionFrame(
            TACTICS_SECTION_NAME,
            career_tactics_body(selector=selector) if tactics_section is None else tactics_section,
        )
    )
    sections.append(
        SectionFrame(
            TRAINING_SECTION_NAME,
            career_training_section() if training_section is None else training_section,
        )
    )
    if news_results:
        sections.append(
            SectionFrame(
                NEWS_SECTION_NAME,
                section_body(".dat", NEWS_SECTION_SCHEMA, results_payload(news_results)),
            )
        )
    return build_container_fragment(sections, attachments=attachments)
