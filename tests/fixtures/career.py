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


def career_table_payload(
    *,
    duplicate_head_bytes: Sequence[bytes] = (),
    extra_groups: Sequence[Sequence[bytes]] = (),
) -> bytes:
    """The example tables, each starting its own run of stored indexes at zero.

    A copy named in `duplicate_head_bytes` is written inside the first table, right where the
    save writes its own copies: immediately after the block it repeats, where its own stored
    index breaks the run and would split the table around it were it not dropped first.
    """
    first_group = table_group_a_blocks()
    for position, head_bytes in enumerate(duplicate_head_bytes, start=1):
        first_group.insert(position, table_group_a_blocks(head_bytes=head_bytes)[0])
    groups = [first_group, table_group_b_blocks(), *(list(group) for group in extra_groups)]
    return bytes(BETWEEN_TABLE_BYTES).join(
        span_payloads(*group, separator_bytes=TABLE_SEPARATOR_BYTES) for group in groups
    )


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


def career_rules_payload() -> bytes:
    """One rules preamble whose quad is doubled, then one whose two copies differ."""
    rounds = career_rules_rounds()
    blocks = [
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
    return span_payloads(*blocks, separator_bytes=RULES_SEPARATOR_BYTES)


def career_span_payload(
    extra_fixtures: Sequence[ExampleFixture] = (),
    extra_strays: Sequence[ExampleFixture] = (),
    *,
    table_duplicate_head_bytes: Sequence[bytes] = (),
    extra_table_groups: Sequence[Sequence[bytes]] = (),
    span_results: Sequence[ExampleResult] = (),
) -> bytes:
    """The calendar, a gap, a stray copy of two, the league tables, the rules, then any results."""
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
            duplicate_head_bytes=table_duplicate_head_bytes, extra_groups=extra_table_groups
        )
        + bytes(BETWEEN_TABLE_BYTES)
        + career_rules_payload()
    )
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
    *, duplicate_club_name: bool = False, game_db_results: Sequence[ExampleResult] = ()
) -> bytes:
    """The game database. `game_db_results` writes result records into a region no result
    reader may scan, so a reader that widened its regions is caught by the score appearing.
    """
    clubs = EXAMPLE_CLUBS + ((SECOND_NORTHBRIDGE_CLUB,) if duplicate_club_name else ())
    payload = (
        name_pools_bytes(FIRST_NAMES, SURNAMES, COMMON_NAMES)
        + clubs_region_bytes(clubs, competition_id_pairs=career_competition_id_pairs())
        + career_tagged_stream()
        + bytes(64)
        + results_payload(game_db_results)
        + bytes(64)
        + manager_region_bytes()
        + player_a_bytes()
        + player_b_bytes()
        + player_c_bytes()
        + player_d_bytes()
        # The save keeps its stage table in the last stretch of game_db, so it goes last here.
        + stage_table_bytes(career_stage_rows())
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
    *,
    duplicate_club_name: bool = False,
    manager_between_jobs: bool = False,
    extra_fixtures: Sequence[ExampleFixture] = (),
    extra_strays: Sequence[ExampleFixture] = (),
    table_duplicate_head_bytes: Sequence[bytes] = (),
    extra_table_groups: Sequence[Sequence[bytes]] = (),
    span_results: Sequence[ExampleResult] = (),
    news_results: Sequence[ExampleResult] = (),
    game_db_results: Sequence[ExampleResult] = (),
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
        span_results: Stage-keyed result records to write into the span, after the tables.
        news_results: Stage-keyed result records to write into a `news` section, which the
            fragment carries only when this is given, so every other save holds no such
            section and every reader of one has to skip it.
        game_db_results: Stage-keyed result records to write into `game_db`, which no result
            reader may scan; a score from one of these means a reader widened its regions.
    """
    selector = UNMATCHED_MANAGER_SELECTOR if manager_between_jobs else MANAGER_SELECTOR
    replacements = {
        "game_db": career_game_db(
            duplicate_club_name=duplicate_club_name, game_db_results=game_db_results
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
    if news_results:
        sections.append(
            SectionFrame(
                NEWS_SECTION_NAME,
                section_body(".dat", NEWS_SECTION_SCHEMA, results_payload(news_results)),
            )
        )
    return build_container_fragment(sections)
