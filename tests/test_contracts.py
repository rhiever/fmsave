from __future__ import annotations

import copy
import dataclasses
import pickle
import random
import struct
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave import Table
from fmsave._errors import CorruptSaveError
from fmsave._layouts import (
    ContractLayout,
    NamePoolLayout,
    PersonBlockLayout,
    PlayerRecordLayout,
    find_layout,
)
from fmsave._reader_stats import ClubStats
from fmsave._save import CONTRACTS_TABLE_CACHE_KEY, PLAYERS_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.models.common import CodedValue, ContractEndSource
from fmsave.models.contracts import (
    Clause,
    ClauseKind,
    Contract,
    ContractChainEntry,
    ContractType,
    SquadStatus,
)
from fmsave.models.players import Player
from fmsave.readers.clubs import ClubIndex, find_club_layouts, read_club_index
from fmsave.readers.contracts import (
    CHAIN_RECORD_END,
    CHAIN_RECORD_HAS_TERMS,
    ContractDecoder,
    build_contract_decoder,
)
from fmsave.readers.names import locate_name_pools
from fmsave.readers.player_scan import locate_player_records, window_end
from fmsave.readers.players import build_player_decoder
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    section_body,
)
from tests.fixtures.game_db import (
    CONTRACT_CLAUSE_MARKER,
    CONTRACT_TAG,
    STUB_STATUS_KIND,
    clause_bonus_lists_bytes,
    club_record_bytes,
    contract_bytes,
    fallback_contract_bytes,
    game_db_body,
    name_pools_bytes,
    player_record_bytes,
    status_record_bytes,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

EMPTY_CLUB_INDEX = ClubIndex(
    clubs=(),
    uid_by_club_index={},
    club_by_uid={},
    team_to_club={},
    affiliate_team_to_club={},
    stats=ClubStats(
        records=0,
        team_lists_found=0,
        status_normal=0,
        status_confirmed=0,
        affiliate_lists=0,
        affiliate_refs=0,
        affiliate_refs_linked=0,
        reputation_found=0,
        reputations_median=None,
    ),
    game_db_bytes=0,
    record_spans=(),
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
CLOCK = date(2031, 3, 1)

RATINGS = tuple([10] * 15)
RAW_ATTRIBUTES = tuple([50] * 54)

NORTHBRIDGE_CLUB_UID = 5001
NORTHBRIDGE_TEAM_A = 70001
NORTHBRIDGE_TEAM_B = 70002
NORTHBRIDGE_CLUB = club_record_bytes(
    club_index=1,
    uid=NORTHBRIDGE_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=70,
    name="Northbridge FC",
    short_name="Northbridge",
    team_ids=(NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B),
    float_anchor_only=True,
)
NORTHBRIDGE_STATUS = status_record_bytes(
    ordinal=51,
    club_index=1,
    uid=NORTHBRIDGE_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=6,
    reputation=4000,
)

SOUTHPORT_CLUB_UID = 5002
SOUTHPORT_TEAM_ID = 70003
SOUTHPORT_CLUB = club_record_bytes(
    club_index=2,
    uid=SOUTHPORT_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=78,
    name="Example Southport",
    short_name="Southport",
    team_ids=(SOUTHPORT_TEAM_ID,),
    float_anchor_only=True,
)
SOUTHPORT_STATUS = status_record_bytes(
    ordinal=52,
    club_index=2,
    uid=SOUTHPORT_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=5,
    reputation=3000,
)


EASTVALE_CLUB_UID = 5003
EASTVALE_TEAM_ID = 70004
EASTVALE_CLUB = club_record_bytes(
    club_index=3,
    uid=EASTVALE_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=79,
    name="Eastvale Rovers",
    short_name="Eastvale",
    team_ids=(EASTVALE_TEAM_ID,),
    float_anchor_only=True,
)
EASTVALE_STATUS = status_record_bytes(
    ordinal=53,
    club_index=3,
    uid=EASTVALE_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=4,
    reputation=2500,
)


def _player_bytes(*, pindex: int, uid: int, team_id: int, trailing: bytes = b"") -> bytes:
    return player_record_bytes(
        pindex=pindex,
        uid=uid,
        current_ability=120,
        potential_ability=140,
        bucket=100,
        home_reputation=5000,
        current_reputation=5200,
        world_reputation=5100,
        team_id=team_id,
        ratings=RATINGS,
        raw_attributes=RAW_ATTRIBUTES,
        transfer_value_raw=0xFFFFFFFF,
        join_date=packed_date(60, 2029),
        sharpness=7000,
        condition=9000,
        height_cm=180,
        trailing=trailing,
    )


PLAYER_A_UID = 900001
PLAYER_B_UID = 900002
PLAYER_C_UID = 900003
PLAYER_D_UID = 900004
PLAYER_E_UID = 900005  # no chain record and no fallback pair: contract stays None


def _player_a_trailing() -> bytes:
    """An ended spell at Northbridge, then the contract in effect at his own club."""
    record_one, _ = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=12000,
        start=packed_date(183, 2028),  # 2028-07-01
        tail={"end": packed_date(181, 2030), "status": 7},  # 2030-06-30, before the clock
        head={"type": 1},
        clauses=(),
    )
    record_two, _ = contract_bytes(
        selector=12,
        team_id=SOUTHPORT_TEAM_ID,
        wage=3000,
        start=packed_date(213, 2029),  # 2029-08-01
        tail={
            "end": packed_date(182, 2032),  # 2032-06-30
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
    decoy, _ = contract_bytes(
        selector=99,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1,
        start=packed_date(1, 2000),
        tail=None,
    )
    return record_one + record_two + decoy


def _player_b_trailing() -> bytes:
    return fallback_contract_bytes(
        end=packed_date(182, 2032),  # 2032-06-30
        start=packed_date(1, 2027),  # 2027-01-01
    ) + bytes(300)


def _player_c_trailing() -> bytes:
    record, _ = contract_bytes(
        selector=14,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2000,
        start=packed_date(1, 2027),
        tail={"end": None, "status": 5},
        head={"type": 2},
        clauses=(),
    )
    fallback = fallback_contract_bytes(
        end=packed_date(1, 2033),
        start=packed_date(1, 2026),
    )
    return record + fallback + bytes(300)


def _player_d_trailing() -> bytes:
    record, _ = contract_bytes(
        selector=15,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1500,
        start=packed_date(1, 2025),
        tail={"break_tail": True},
    )
    fallback = fallback_contract_bytes(
        end=packed_date(1, 2030),
        start=packed_date(1, 2024),
    )
    return record + fallback + bytes(300)


def player_region_bytes() -> bytes:
    return (
        _player_bytes(
            pindex=11, uid=PLAYER_A_UID, team_id=SOUTHPORT_TEAM_ID, trailing=_player_a_trailing()
        )
        + _player_bytes(
            pindex=12, uid=PLAYER_B_UID, team_id=0xFFFFFFFF, trailing=_player_b_trailing()
        )
        + _player_bytes(
            pindex=13,
            uid=PLAYER_C_UID,
            team_id=NORTHBRIDGE_TEAM_A,
            trailing=_player_c_trailing(),
        )
        + _player_bytes(
            pindex=14, uid=PLAYER_D_UID, team_id=0xFFFFFFFF, trailing=_player_d_trailing()
        )
        + _player_bytes(pindex=15, uid=PLAYER_E_UID, team_id=0xFFFFFFFF)
    )


def example_game_db() -> bytes:
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + player_region_bytes()
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def registered_player_layout() -> PlayerRecordLayout:
    return find_layout(PlayerRecordLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_name_pool_layout() -> NamePoolLayout:
    return find_layout(NamePoolLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_person_layout() -> PersonBlockLayout:
    return find_layout(PersonBlockLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_contract_layout() -> ContractLayout:
    return find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout


def build_index(game_db: bytes):
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    player_records = locate_player_records(
        game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME
    )
    club_index = read_club_index(game_db, find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME)
    return name_pools, player_records, club_index


def decode_all(game_db: bytes) -> list[tuple[Player, Contract | None]]:
    name_pools, player_records, club_index = build_index(game_db)
    decoder = build_player_decoder(
        player_records.layout,
        club_index,
        name_pools,
        CLOCK,
        registered_person_layout(),
        registered_contract_layout(),
        FILE_NAME,
    )
    record_offsets = player_records.record_offsets
    game_db_length = len(game_db)
    last_position = len(record_offsets) - 1
    return [
        decoder.decode(
            game_db,
            record_offset,
            window_end(player_records, position, game_db_length),
            is_last_record=position == last_position,
            suspension_entries=(),
        )
        for position, record_offset in enumerate(record_offsets)
    ]


def by_uid(
    decoded: list[tuple[Player, Contract | None]], uid: int
) -> tuple[Player, Contract | None]:
    for player, contract in decoded:
        if player.uid == uid:
            return player, contract
    raise AssertionError(f"no decoded player with uid {uid}")


def test_player_a_chain_record_assembly() -> None:
    decoded = decode_all(example_game_db())
    player, contract = by_uid(decoded, PLAYER_A_UID)
    assert contract is not None
    # Every field comes from the record in effect, the one at the player's own club.
    assert contract.wage == 3000
    assert contract.start == date(2029, 8, 1)
    assert contract.end == date(2032, 6, 30)
    assert contract.end_source == ContractEndSource.CONTRACT
    assert contract.squad_status is not None
    assert contract.squad_status.label is SquadStatus.REGULAR_STARTER
    assert contract.kind is not None
    assert contract.kind.label is ContractType.FULL_TIME
    assert len(contract.clauses) == 2
    assert contract.clauses[0].kind.label is ClauseKind.MINIMUM_FEE_RELEASE_DOMESTIC
    assert contract.clauses[0].parameter == 365
    assert contract.clauses[0].value == 250000
    assert contract.clauses[1].kind.label is ClauseKind.OPTIONAL_EXTENSION_BY_CLUB
    assert contract.clauses[1].parameter == 2
    assert contract.clauses[1].value is None
    assert contract.event_count == 1
    assert contract.unknown["money_a"] == 72000
    assert contract.unknown["e39"] == 0x40
    assert contract.club_uid == SOUTHPORT_CLUB_UID
    assert contract.on_loan is False
    assert contract.loan_parent_club_uid is None
    assert contract.loan_parent_club_name is None
    # The ended spell at Northbridge stays in the chain.
    assert contract.chain_club_uids == (NORTHBRIDGE_CLUB_UID, SOUTHPORT_CLUB_UID)
    assert contract.chain_club_uids_with_terms == (NORTHBRIDGE_CLUB_UID, SOUTHPORT_CLUB_UID)
    assert contract.chain_club_names_with_terms == ("Northbridge FC", "Example Southport")
    assert len(contract.chain) == 2
    assert contract.chain[0].wage == 12000
    assert contract.chain[1].wage == 3000
    assert player.on_loan is False
    assert player.loan_parent_club_uid is None
    assert player.loan_parent_club_name is None
    assert player.contract is contract


def test_player_b_fallback_only() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_B_UID)
    assert contract is not None
    assert contract.start == date(2027, 1, 1)
    assert contract.end == date(2032, 6, 30)
    assert contract.end_source == ContractEndSource.PLAYER_RECORD
    assert contract.wage is None
    assert contract.on_loan is None
    assert contract.chain == ()


def test_player_c_null_tail_end_skips_fallback() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_C_UID)
    assert contract is not None
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.kind is not None
    assert contract.kind.label is ContractType.UNKNOWN
    assert contract.kind.raw == 2


def test_player_d_broken_tail_and_stale_fallback() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_D_UID)
    assert contract is not None
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.chain[0].has_terms is False
    assert contract.squad_status is None
    assert contract.clauses == ()


UNREGISTERED_TEAM_ID = 79999  # no club in the fixture fields this team


@pytest.mark.parametrize(
    ("player_team_id", "chain_record_team_id", "player_club_uid", "chain_club_uids"),
    [
        pytest.param(
            UNREGISTERED_TEAM_ID,
            NORTHBRIDGE_TEAM_A,
            None,
            (NORTHBRIDGE_CLUB_UID,),
            id="player-team-unresolved",
        ),
        pytest.param(
            SOUTHPORT_TEAM_ID,
            UNREGISTERED_TEAM_ID,
            SOUTHPORT_CLUB_UID,
            (None,),
            id="first-record-team-unresolved",
        ),
    ],
)
def test_on_loan_is_none_unless_both_the_player_and_first_record_teams_resolve(
    player_team_id: int,
    chain_record_team_id: int,
    player_club_uid: int | None,
    chain_club_uids: tuple[int | None, ...],
) -> None:
    record, _ = contract_bytes(
        selector=71,
        team_id=chain_record_team_id,
        wage=2500,
        start=packed_date(1, 2029),
        tail={"end": packed_date(1, 2032), "status": 4},
        head={"type": 1},
        clauses=(),
    )
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=70, uid=900030, team_id=player_team_id, trailing=record)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    player, contract = by_uid(decoded, 900030)
    assert contract is not None
    # The other side of the pair does resolve, so only the unresolved side decides.
    assert player.club_uid == player_club_uid
    assert contract.chain_club_uids == chain_club_uids
    assert contract.on_loan is None
    assert contract.loan_parent_club_uid is None
    assert contract.loan_parent_club_name is None
    assert player.on_loan is None
    assert player.loan_parent_club_uid is None
    assert player.loan_parent_club_name is None


def test_no_record_and_no_fallback_gives_no_contract() -> None:
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=20, uid=900010, team_id=0xFFFFFFFF)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    player, contract = by_uid(decoded, 900010)
    assert contract is None
    assert player.contract is None


def test_unknown_clause_kind() -> None:
    record, _ = contract_bytes(
        selector=26,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1000,
        start=packed_date(1, 2028),
        tail={"end": packed_date(1, 2030), "status": 3},
        head={"type": 1},
        clauses=((100, 10, 0x2A),),
    )
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=25, uid=900011, team_id=0xFFFFFFFF, trailing=record)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    _player, contract = by_uid(decoded, 900011)
    assert contract is not None
    assert contract.clauses[0].kind.label is ClauseKind.UNKNOWN
    assert contract.clauses[0].kind.raw == 42


def test_no_head_leaves_type_and_money_absent_but_clauses_parse() -> None:
    record, _ = contract_bytes(
        selector=31,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1000,
        start=packed_date(1, 2028),
        tail={"end": packed_date(1, 2030), "status": 3},
        head=None,
        clauses=((100, 0xFFFF, 0x00),),
    )
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=30, uid=900012, team_id=0xFFFFFFFF, trailing=record)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    _player, contract = by_uid(decoded, 900012)
    assert contract is not None
    assert contract.kind is None
    assert contract.unknown.get("money_a") is None
    assert contract.unknown.get("money_b") is None
    assert contract.unknown.get("money_c") is None
    assert len(contract.clauses) == 1
    assert contract.clauses[0].kind.label is ClauseKind.MINIMUM_FEE_RELEASE


def test_chain_record_far_past_record_is_included_with_no_cap() -> None:
    record, _ = contract_bytes(
        selector=41,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=5000,
        start=packed_date(1, 2028),
        tail={"end": packed_date(1, 2030), "status": 3},
        head={"type": 1},
        clauses=(),
    )
    trailing = bytes(10_000) + record
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=40, uid=900013, team_id=0xFFFFFFFF, trailing=trailing)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    _player, contract = by_uid(decoded, 900013)
    assert contract is not None
    assert contract.wage == 5000


def test_head_null_date_tag_is_not_mistaken_for_a_second_chain_record() -> None:
    """A record with a head carries a second `01 00 6C 07` tag inside it (the null date at
    `base-20`); its selector never matches the player's own, so only one chain record
    is found.
    """
    record, _ = contract_bytes(
        selector=51,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=4000,
        start=packed_date(1, 2028),
        tail={"end": packed_date(1, 2030), "status": 3},
        head={"type": 1, "money_a": 1000},
        clauses=(),
    )
    assert record.count(CONTRACT_TAG) == 2  # the chain tag, plus the head's null-date tag
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=50, uid=900014, team_id=0xFFFFFFFF, trailing=record)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    decoded = decode_all(game_db)
    _player, contract = by_uid(decoded, 900014)
    assert contract is not None
    assert len(contract.chain) == 1
    assert contract.chain[0].wage == 4000


def one_player_game_db(*, pindex: int, uid: int, team_id: int, trailing: bytes) -> bytes:
    """The two example clubs and one player, with `trailing` bytes after his record."""
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(pindex=pindex, uid=uid, team_id=team_id, trailing=trailing)
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


DATE_MARKED_PINDEX = 80
DATE_MARKED_UID = 900080
# A date on or before the fixture's clock, as every date-marked record in a real save holds.
DATE_IN_THE_TAG_SLOT = packed_date(9, 2031)
NOT_A_DATE_IN_THE_TAG_SLOT = bytes.fromhex("01020304")


def date_marked_record(
    *,
    marker: bytes = DATE_IN_THE_TAG_SLOT,
    team_id: int = NORTHBRIDGE_TEAM_A,
    start: bytes = packed_date(1, 2029),
) -> bytes:
    """A chain record whose tag slot holds `marker`; no clause table, so no FF run.

    Without an FF run the fallback reader finds no dates either, so a record this decoder
    does not accept leaves the player with no contract at all.
    """
    record, _tag_offset = contract_bytes(
        selector=DATE_MARKED_PINDEX + 1,
        team_id=team_id,
        wage=6000,
        start=start,
        tail={"end": packed_date(182, 2033), "status": 3},
        clause_table=False,
        marker=marker,
    )
    return record


def test_a_chain_record_marked_with_a_date_is_found() -> None:
    game_db = one_player_game_db(
        pindex=DATE_MARKED_PINDEX,
        uid=DATE_MARKED_UID,
        team_id=NORTHBRIDGE_TEAM_A,
        trailing=date_marked_record(),
    )
    _player, contract = by_uid(decode_all(game_db), DATE_MARKED_UID)
    assert contract is not None
    assert len(contract.chain) == 1
    assert contract.wage == 6000
    assert contract.start == date(2029, 1, 1)
    assert contract.end == date(2033, 7, 1)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID


@pytest.mark.parametrize(
    "record_changes",
    [
        pytest.param({"marker": NOT_A_DATE_IN_THE_TAG_SLOT}, id="neither the tag nor a date"),
        pytest.param({"start": bytes(4)}, id="no start date"),
        pytest.param({"team_id": UNREGISTERED_TEAM_ID}, id="team that resolves to no club"),
    ],
)
def test_a_record_the_date_marked_checks_reject_is_not_a_chain_record(
    record_changes: dict[str, object],
) -> None:
    game_db = one_player_game_db(
        pindex=DATE_MARKED_PINDEX,
        uid=DATE_MARKED_UID,
        team_id=NORTHBRIDGE_TEAM_A,
        trailing=date_marked_record(**record_changes),  # pyright: ignore[reportArgumentType]
    )
    _player, contract = by_uid(decode_all(game_db), DATE_MARKED_UID)
    assert contract is None


def test_date_marked_records_are_counted_for_the_checks() -> None:
    game_db = one_player_game_db(
        pindex=DATE_MARKED_PINDEX,
        uid=DATE_MARKED_UID,
        team_id=NORTHBRIDGE_TEAM_A,
        trailing=date_marked_record(),
    )
    _name_pools, player_records, club_index = build_index(game_db)
    decoder = build_contract_decoder(registered_contract_layout(), club_index, CLOCK, FILE_NAME)
    decoder.decode(
        game_db,
        player_records.record_offsets[0],
        len(game_db),
        True,
        DATE_MARKED_PINDEX,
        DATE_MARKED_UID,
        None,
        NORTHBRIDGE_CLUB_UID,
    )
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.chain_records == 1
    assert stats.date_marked_chain_records == 1


SELECTION_PINDEX = 90
SELECTION_UID = 900090
# The fixture's clock is 2031-03-01 (day 60).
BEFORE_THE_CLOCK = packed_date(183, 2028)  # 2028-07-01
LATER_BEFORE_THE_CLOCK = packed_date(1, 2030)  # 2030-01-01
LATEST_BEFORE_THE_CLOCK = packed_date(31, 2031)  # 2031-01-31
AFTER_THE_CLOCK = packed_date(183, 2031)  # 2031-07-02
ENDS_AFTER_THE_CLOCK = packed_date(182, 2032)  # 2032-06-30
ENDED_BEFORE_THE_CLOCK = packed_date(181, 2030)  # 2030-06-30
ENDS_LATER_STILL = packed_date(182, 2035)  # 2035-07-01


def selection_record(
    *, team_id: int, wage: int, start: bytes, end: bytes | None = None, with_tail: bool = True
) -> bytes:
    """One chain record with no clause table, so no FF run reaches the fallback reader."""
    record, _tag_offset = contract_bytes(
        selector=SELECTION_PINDEX + 1,
        team_id=team_id,
        wage=wage,
        start=start,
        tail={"end": end, "status": 3} if with_tail else None,
        clause_table=False,
    )
    return record


def selection_game_db(records: bytes, *, team_id: int = NORTHBRIDGE_TEAM_A) -> bytes:
    return one_player_game_db(
        pindex=SELECTION_PINDEX, uid=SELECTION_UID, team_id=team_id, trailing=records
    )


def selected_contract(records: bytes, *, team_id: int = NORTHBRIDGE_TEAM_A) -> Contract:
    _player, contract = by_uid(
        decode_all(selection_game_db(records, team_id=team_id)), SELECTION_UID
    )
    assert contract is not None
    return contract


def away_selected_contract(records: bytes) -> Contract:
    """The contract of a player registered at Southport whose records are all elsewhere.

    Three clubs, so two of them can compete for a player who has no record at his own.
    """
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB, EASTVALE_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS, EASTVALE_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(
            pindex=SELECTION_PINDEX,
            uid=SELECTION_UID,
            team_id=SOUTHPORT_TEAM_ID,
            trailing=records,
        )
    )
    _player, contract = by_uid(
        decode_all(section_body(".dat", GAME_DB_SCHEMA, payload)), SELECTION_UID
    )
    assert contract is not None
    return contract


def test_an_agreed_future_move_is_not_the_contract_in_effect() -> None:
    in_effect = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=12000, start=BEFORE_THE_CLOCK, end=ENDS_AFTER_THE_CLOCK
    )
    future_move = selection_record(
        team_id=SOUTHPORT_TEAM_ID, wage=30000, start=AFTER_THE_CLOCK, end=ENDS_LATER_STILL
    )
    contract = selected_contract(in_effect + future_move)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 12000
    assert contract.start == date(2028, 7, 1)
    assert contract.end == date(2032, 6, 30)
    assert contract.end_source == ContractEndSource.CONTRACT
    # The future move is still one of the chain records.
    assert contract.chain_club_uids == (NORTHBRIDGE_CLUB_UID, SOUTHPORT_CLUB_UID)


def test_the_record_at_the_players_own_club_beats_one_that_started_later_elsewhere() -> None:
    at_own_club = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDS_AFTER_THE_CLOCK
    )
    later_elsewhere = selection_record(
        team_id=SOUTHPORT_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_LATER_STILL,
    )
    contract = selected_contract(at_own_club + later_elsewhere)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 11000
    assert contract.start == date(2028, 7, 1)
    assert contract.end == date(2032, 6, 30)


def test_an_ended_record_at_the_players_club_loses_to_a_current_one_elsewhere() -> None:
    ended_at_own_club = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDED_BEFORE_THE_CLOCK
    )
    current_elsewhere = selection_record(
        team_id=SOUTHPORT_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = selected_contract(ended_at_own_club + current_elsewhere)
    assert contract.club_uid == SOUTHPORT_CLUB_UID
    assert contract.wage == 25000
    assert contract.start == date(2030, 1, 1)


def test_the_earliest_record_that_has_not_ended_picks_the_club_when_none_is_at_his_club() -> None:
    """A player away from whoever pays him: the club of his oldest running spell wins.

    The records that start last at another club are offers made while he is away, so the
    latest start would take one of those instead of the deal he is really on.
    """
    earlier = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDS_LATER_STILL
    )
    later = selection_record(
        team_id=EASTVALE_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = away_selected_contract(earlier + later)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 11000
    assert contract.start == date(2028, 7, 1)
    assert contract.end == date(2035, 7, 1)


def test_the_latest_start_at_the_chosen_club_wins_over_its_own_older_record() -> None:
    """The earliest record only chooses the club; a renewal at that club still wins."""
    earlier = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDS_AFTER_THE_CLOCK
    )
    renewal = selection_record(
        team_id=NORTHBRIDGE_TEAM_A,
        wage=14000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_LATER_STILL,
    )
    later_elsewhere = selection_record(
        team_id=EASTVALE_TEAM_ID,
        wage=25000,
        start=LATEST_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = away_selected_contract(earlier + renewal + later_elsewhere)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 14000
    assert contract.start == date(2030, 1, 1)
    assert contract.end == date(2035, 7, 1)


def test_a_record_that_has_ended_does_not_pick_the_club() -> None:
    earlier_but_ended = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDED_BEFORE_THE_CLOCK
    )
    still_running = selection_record(
        team_id=EASTVALE_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = away_selected_contract(earlier_but_ended + still_running)
    assert contract.club_uid == EASTVALE_CLUB_UID
    assert contract.wage == 25000


def test_a_record_with_no_wage_end_or_type_does_not_pick_the_club() -> None:
    """A record holding none of a contract's content is an offer, and names no club.

    Starting first is otherwise enough to win, which would hand the contract in effect to a
    record with no end date and leave the player's own end date missing.
    """
    offer_shaped_but_earlier = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=0, start=BEFORE_THE_CLOCK, end=None
    )
    real_contract = selection_record(
        team_id=EASTVALE_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = away_selected_contract(offer_shaped_but_earlier + real_contract)
    assert contract.club_uid == EASTVALE_CLUB_UID
    assert contract.wage == 25000
    assert contract.start == date(2030, 1, 1)
    assert contract.end == date(2032, 6, 30)


def test_the_earliest_record_picks_the_club_when_none_of_them_carries_a_contract() -> None:
    """With every running record offer-shaped, the oldest one still names the club."""
    earlier = selection_record(team_id=NORTHBRIDGE_TEAM_A, wage=0, start=BEFORE_THE_CLOCK, end=None)
    later = selection_record(
        team_id=EASTVALE_TEAM_ID, wage=0, start=LATER_BEFORE_THE_CLOCK, end=None
    )
    contract = away_selected_contract(earlier + later)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.start == date(2028, 7, 1)


def test_a_record_that_has_ended_at_the_chosen_club_is_not_the_contract_in_effect() -> None:
    """Inside the chosen club an expired record loses, however late it started.

    Its later start would otherwise beat the record the player is really on, putting a dead
    record's wage, end and squad status in effect.
    """
    still_running = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDS_AFTER_THE_CLOCK
    )
    ended_but_later = selection_record(
        team_id=NORTHBRIDGE_TEAM_A,
        wage=19000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDED_BEFORE_THE_CLOCK,
    )
    contract = away_selected_contract(still_running + ended_but_later)
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 11000
    assert contract.start == date(2028, 7, 1)
    assert contract.end == date(2032, 6, 30)


def test_the_latest_start_wins_when_every_record_has_ended() -> None:
    earlier = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDED_BEFORE_THE_CLOCK
    )
    later = selection_record(
        team_id=EASTVALE_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDED_BEFORE_THE_CLOCK,
    )
    contract = away_selected_contract(earlier + later)
    assert contract.club_uid == EASTVALE_CLUB_UID
    assert contract.wage == 25000
    assert contract.start == date(2030, 1, 1)


def test_a_player_whose_own_club_is_unknown_keeps_the_latest_start() -> None:
    """With no club to be away from, there is nothing to say a later record is an offer."""
    earlier = selection_record(
        team_id=NORTHBRIDGE_TEAM_A, wage=11000, start=BEFORE_THE_CLOCK, end=ENDS_LATER_STILL
    )
    later = selection_record(
        team_id=SOUTHPORT_TEAM_ID,
        wage=25000,
        start=LATER_BEFORE_THE_CLOCK,
        end=ENDS_AFTER_THE_CLOCK,
    )
    contract = selected_contract(earlier + later, team_id=UNREGISTERED_TEAM_ID)
    assert contract.club_uid == SOUTHPORT_CLUB_UID
    assert contract.wage == 25000
    assert contract.start == date(2030, 1, 1)


def test_a_player_whose_records_all_start_after_the_clock_has_no_contract_in_effect() -> None:
    contract = selected_contract(
        selection_record(
            team_id=NORTHBRIDGE_TEAM_A, wage=9000, start=AFTER_THE_CLOCK, end=ENDS_LATER_STILL
        )
    )
    assert contract.club_uid is None
    assert contract.club_name is None
    assert contract.team_id is None
    assert contract.wage is None
    assert contract.start is None
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.squad_status is None
    assert contract.on_loan is None
    assert contract.chain_club_uids == (NORTHBRIDGE_CLUB_UID,)


def test_a_record_without_a_tail_is_in_effect_when_no_tailed_record_is() -> None:
    contract = selected_contract(
        selection_record(
            team_id=NORTHBRIDGE_TEAM_A, wage=2500, start=BEFORE_THE_CLOCK, with_tail=False
        )
    )
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 2500
    assert contract.start == date(2028, 7, 1)
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.squad_status is None


def test_players_with_no_contract_in_effect_are_counted_for_the_checks() -> None:
    game_db = selection_game_db(
        selection_record(
            team_id=NORTHBRIDGE_TEAM_A, wage=9000, start=AFTER_THE_CLOCK, end=ENDS_LATER_STILL
        )
    )
    _name_pools, player_records, club_index = build_index(game_db)
    decoder = build_contract_decoder(registered_contract_layout(), club_index, CLOCK, FILE_NAME)
    decoder.decode(
        game_db,
        player_records.record_offsets[0],
        len(game_db),
        True,
        SELECTION_PINDEX,
        SELECTION_UID,
        None,
        NORTHBRIDGE_CLUB_UID,
    )
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.players_with_chain == 1
    assert stats.without_contract_in_effect == 1


LOAN_PINDEX = 95
LOAN_UID = 900095
LOAN_BLOCK_START = packed_date(64, 2030)  # 2030-03-05, later than the record's own start
LOAN_BLOCK_END = packed_date(365, 2031)  # 2031-12-31, earlier than the contract's end
NORTHBRIDGE_WITH_AFFILIATE = club_record_bytes(
    club_index=1,
    uid=NORTHBRIDGE_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=70,
    name="Northbridge FC",
    short_name="Northbridge",
    team_ids=(NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B),
    affiliate_team_ids=(SOUTHPORT_TEAM_ID,),
    float_anchor_only=True,
)


def loan_game_db(*, trailing: bytes, affiliate: bool) -> bytes:
    """One player at Southport's team, which Northbridge controls when `affiliate`."""
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_WITH_AFFILIATE if affiliate else NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + _player_bytes(
            pindex=LOAN_PINDEX, uid=LOAN_UID, team_id=SOUTHPORT_TEAM_ID, trailing=trailing
        )
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def contract_club_record(*, wage: int = 20000) -> bytes:
    """The player's contract record at Northbridge: a tail, and a spell that has not ended."""
    record, _tag_offset = contract_bytes(
        selector=LOAN_PINDEX + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=wage,
        start=BEFORE_THE_CLOCK,
        tail={"end": ENDS_AFTER_THE_CLOCK, "status": 3},
        clause_table=False,
    )
    return record


def current_club_record(
    *,
    block_end: bytes = ENDS_AFTER_THE_CLOCK,
    block_start: bytes = LATER_BEFORE_THE_CLOCK,
    e24: int = 0xFFFFFFFF,
    with_tail: bool = False,
) -> bytes:
    """The record at the club the player is registered with.

    Its block carries the loan end at the tail's end position, the loan start four bytes
    later and the loan marker at the tail's e24; `break_tail` keeps the block from parsing
    as a tail of its own.
    """
    record, _tag_offset = contract_bytes(
        selector=LOAN_PINDEX + 1,
        team_id=SOUTHPORT_TEAM_ID,
        wage=1500,
        start=LATER_BEFORE_THE_CLOCK,
        tail={
            "end": block_end,
            "printed_start": block_start,
            "e24": e24,
            "status": 3,
            "break_tail": not with_tail,
        },
        clause_table=False,
    )
    return record


def loan_decoded(*, trailing: bytes, affiliate: bool) -> tuple[Player, Contract]:
    player, contract = by_uid(
        decode_all(loan_game_db(trailing=trailing, affiliate=affiliate)), LOAN_UID
    )
    assert contract is not None
    return player, contract


def test_a_registration_at_an_affiliate_team_is_a_spell_at_the_parent_club_not_a_loan() -> None:
    player, contract = loan_decoded(
        trailing=contract_club_record() + current_club_record(), affiliate=True
    )
    assert player.club_uid == NORTHBRIDGE_CLUB_UID
    assert player.club_name == "Northbridge FC"
    assert player.team_id == SOUTHPORT_TEAM_ID
    assert player.team_slot == 2
    assert player.team_club_uid == SOUTHPORT_CLUB_UID
    assert player.on_loan is False
    assert player.loan_parent_club_uid is None
    assert player.loan_parent_club_name is None
    assert player.loan_start is None
    assert player.loan_end is None
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 20000
    assert contract.on_loan is False
    assert contract.loan_start is None
    assert contract.loan_end is None


def test_a_loan_to_an_unrelated_club_is_a_loan_from_the_contract_club() -> None:
    player, contract = loan_decoded(
        trailing=contract_club_record() + current_club_record(), affiliate=False
    )
    assert player.club_uid == SOUTHPORT_CLUB_UID
    assert player.team_club_uid is None
    assert player.on_loan is True
    assert player.loan_parent_club_uid == NORTHBRIDGE_CLUB_UID
    assert player.loan_parent_club_name == "Northbridge FC"
    assert player.loan_start == date(2030, 1, 1)
    assert player.loan_end == date(2032, 6, 30)
    # The contract in effect stays the one at the club the player is on loan from.
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.wage == 20000
    assert contract.end == date(2032, 6, 30)
    assert contract.on_loan is True
    assert contract.loan_parent_club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.loan_start == date(2030, 1, 1)
    assert contract.loan_end == date(2032, 6, 30)


def test_the_loan_dates_are_read_from_the_block_before_the_loan_club_record() -> None:
    """The loan runs to its own dates, which are not the contract's and not the record's.

    The block's dates sit four bytes apart, the end first, so a block read one field out
    would return the record's own start or the contract's end instead.
    """
    player, contract = loan_decoded(
        trailing=contract_club_record()
        + current_club_record(block_end=LOAN_BLOCK_END, block_start=LOAN_BLOCK_START),
        affiliate=False,
    )
    assert player.on_loan is True
    assert contract.end == date(2032, 6, 30)  # the contract at the parent club runs longer
    assert contract.start == date(2028, 7, 1)
    assert contract.loan_start == date(2030, 3, 5)
    assert contract.loan_end == date(2031, 12, 31)
    assert player.loan_start == date(2030, 3, 5)
    assert player.loan_end == date(2031, 12, 31)


@pytest.mark.parametrize(
    "current_club_changes",
    [
        pytest.param({"block_end": ENDED_BEFORE_THE_CLOCK}, id="block ended before the clock"),
        pytest.param({"e24": 1234}, id="block marker is a team id"),
        pytest.param({"with_tail": True}, id="the record has a tail of its own"),
    ],
)
def test_a_player_away_from_his_contract_club_without_a_live_loan_block_is_not_on_loan(
    current_club_changes: dict[str, object],
) -> None:
    player, contract = loan_decoded(
        trailing=contract_club_record() + current_club_record(**current_club_changes),  # pyright: ignore[reportArgumentType]
        affiliate=False,
    )
    assert player.club_uid == SOUTHPORT_CLUB_UID
    assert player.on_loan is False
    assert player.loan_parent_club_uid is None
    assert player.loan_start is None
    assert player.loan_end is None
    assert contract.on_loan is False
    assert contract.loan_start is None
    assert contract.loan_end is None


def _test_contract_decoder(layout: ContractLayout) -> ContractDecoder:
    return build_contract_decoder(layout, EMPTY_CLUB_INDEX, date(2031, 1, 1), FILE_NAME)


def test_build_contract_decoder_rejects_a_non_adjacent_tail_sentinel() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    broken_layout = dataclasses.replace(layout, tail_sentinel_word_offset=99)
    with pytest.raises(ValueError, match="tail_sentinel_word_offset"):
        build_contract_decoder(broken_layout, EMPTY_CLUB_INDEX, date(2031, 1, 1), FILE_NAME)


def test_build_contract_decoder_rejects_an_overlapping_clause_entry() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    broken_layout = dataclasses.replace(layout, clause_parameter_offset=1)
    with pytest.raises(ValueError, match="'parameter' at offset 1 overlaps an earlier field"):
        build_contract_decoder(broken_layout, EMPTY_CLUB_INDEX, date(2031, 1, 1), FILE_NAME)


@pytest.mark.parametrize(
    ("layout_changes", "struct_description"),
    [
        pytest.param(
            {"clause_kind_offset": 0, "clause_parameter_offset": 2, "clause_value_offset": 4},
            "clause entry",
            id="clause-entry",
        ),
        pytest.param({"tail_e37_offset": 38, "tail_e38_offset": 37}, "tail", id="tail"),
        pytest.param({"head_money_a_offset": -28, "head_money_b_offset": -32}, "head", id="head"),
        pytest.param({"team_id_offset": 17, "wage_offset": 9}, "team and wage", id="team-wage"),
    ],
)
def test_build_contract_decoder_rejects_fields_not_laid_out_in_unpack_order(
    layout_changes: dict[str, int], struct_description: str
) -> None:
    """Each struct is unpacked into fixed names in one order, so a layout whose offsets
    reorder those fields, without overlapping them, must fail at build time instead of
    silently swapping values.
    """
    broken_layout = dataclasses.replace(registered_contract_layout(), **layout_changes)
    with pytest.raises(
        ValueError,
        match=f"the {struct_description} fields must be laid out in the order they are unpacked",
    ):
        _test_contract_decoder(broken_layout)


@pytest.mark.parametrize(
    ("layout_changes", "message"),
    [
        pytest.param(
            {"clause_zero_offset": -7},
            "clause_zero_offset .* must immediately follow the FF run",
            id="gap-after-ff-run",
        ),
        pytest.param(
            {"clause_ff_count": 7},
            "clause_zero_offset .* must immediately follow the FF run",
            id="short-ff-run",
        ),
        pytest.param(
            {"clause_count_offset": -4},
            "clause_count_offset .* must immediately follow the zero run",
            id="gap-after-zero-run",
        ),
    ],
)
def test_build_contract_decoder_rejects_a_non_contiguous_clause_prefix(
    layout_changes: dict[str, int], message: str
) -> None:
    broken_layout = dataclasses.replace(registered_contract_layout(), **layout_changes)
    with pytest.raises(ValueError, match=message):
        _test_contract_decoder(broken_layout)


@pytest.mark.parametrize(
    ("layout_changes", "message"),
    [
        pytest.param(
            {"clause_step_bytes": 9}, "clause_step_bytes", id="step-differs-from-entry-size"
        ),
        pytest.param(
            {"clause_entries_offset": -5},
            "empty bonus lists",
            id="entries-do-not-end-where-empty-lists-start",
        ),
        pytest.param({"clause_trailer_bytes": 3}, "empty bonus lists", id="trailer-size-differs"),
        pytest.param(
            {"clause_award_count_bytes": 3},
            "clause_award_count_bytes",
            id="unsupported-award-count-width",
        ),
        pytest.param(
            {"clause_competition_item_bytes": 5},
            "clause_competition_item_prefix",
            id="competition-prefix-longer-than-item",
        ),
        pytest.param(
            {"clause_award_item_bytes": 1},
            "clause_award_item_prefix",
            id="award-prefix-longer-than-item",
        ),
        pytest.param(
            {"clause_team_marker_id_bytes": 9},
            "clause_team_marker_id_bytes",
            id="team-id-longer-than-marker",
        ),
    ],
)
def test_build_contract_decoder_rejects_an_inconsistent_clause_table_layout(
    layout_changes: dict[str, int], message: str
) -> None:
    broken_layout = dataclasses.replace(registered_contract_layout(), **layout_changes)
    with pytest.raises(ValueError, match=message):
        _test_contract_decoder(broken_layout)


def test_build_contract_decoder_rejects_a_zero_fallback_nonzero_length() -> None:
    broken_layout = dataclasses.replace(registered_contract_layout(), fallback_nonzero_length=0)
    with pytest.raises(ValueError, match="fallback_nonzero_length .* must be at least 1"):
        _test_contract_decoder(broken_layout)


def test_fallback_all_zero_check_spans_fallback_nonzero_length_bytes() -> None:
    """Four zero bytes then four nonzero bytes at `j + fallback_nonzero_offset`: an 8-byte
    all-zero check accepts the pair, and a 4-byte one rejects it.
    """
    layout = registered_contract_layout()
    assert layout.fallback_nonzero_length == 8
    hit = layout.fallback_start_from_record
    pattern = (
        b"\xff\xff\xff\xff"
        + bytes(4)
        + packed_date(1, 2032)
        + packed_date(1, 2027)
        + bytes(4)
        + bytes([0x33] * 4)
    )
    game_db = bytes(hit) + pattern + bytes(200)
    record_window_end = len(game_db)

    eight_byte_decoder = _test_contract_decoder(layout)
    assert eight_byte_decoder._find_fallback_dates(game_db, 0, record_window_end) == (
        date(2027, 1, 1),
        date(2032, 1, 1),
    )

    four_byte_decoder = _test_contract_decoder(
        dataclasses.replace(layout, fallback_nonzero_length=4)
    )
    assert four_byte_decoder._find_fallback_dates(game_db, 0, record_window_end) == (None, None)


def test_fallback_gate_accepts_j_plus_16_at_limit_and_rejects_one_byte_further() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    hit = layout.fallback_start_from_record
    dates_offset = hit + 8  # "j" in ContractLayout's docstring
    end_bytes = packed_date(1, 2032)
    start_bytes = packed_date(1, 2027)
    pattern = b"\xff\xff\xff\xff" + bytes(4) + end_bytes + start_bytes + bytes([0x33] * 8)
    game_db = bytes(hit) + pattern + bytes(200)

    accepted_window_end = (dates_offset + layout.fallback_gate_length) + layout.fallback_end_margin
    start, end = decoder._find_fallback_dates(game_db, 0, accepted_window_end)
    assert start == date(2027, 1, 1)
    assert end == date(2032, 1, 1)

    rejected_window_end = accepted_window_end - 1
    start, end = decoder._find_fallback_dates(game_db, 0, rejected_window_end)
    assert start is None
    assert end is None


def test_only_parsed_tails_with_an_end_date_count_toward_the_past_dated_share() -> None:
    open_ended_record, open_ended_tag_offset = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2000,
        start=packed_date(1, 2027),
        tail={"end": None, "status": 5},
        head={"type": 2},
    )
    past_record, past_tag_offset = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=3000,
        start=packed_date(1, 2028),
        tail={"end": packed_date(181, 2030), "status": 3},  # 2030-06-30, before the clock
        head={"type": 1},
    )
    game_db = open_ended_record + past_record + bytes(64)
    decoder = _test_contract_decoder(registered_contract_layout())

    open_ended = decoder.decode_chain_record(game_db, open_ended_tag_offset)
    past = decoder.decode_chain_record(game_db, len(open_ended_record) + past_tag_offset)

    assert open_ended[CHAIN_RECORD_HAS_TERMS] and open_ended[CHAIN_RECORD_END] is None
    assert past[CHAIN_RECORD_HAS_TERMS] and past[CHAIN_RECORD_END] == date(2030, 6, 30)
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.tails_parsed == 2
    assert stats.tail_ends == 1
    assert stats.tail_ends_past == 1


def test_truncated_chain_record_raises_corrupt_save_error_with_file_context() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    tag_offset = 10
    needed_end = tag_offset + max(layout.team_id_offset, layout.wage_offset) + 4
    game_db = bytearray(needed_end - 1)  # one byte short of what the record needs
    game_db[tag_offset : tag_offset + 4] = CONTRACT_TAG
    struct.pack_into("<I", game_db, tag_offset + layout.selector_offset, 8)  # pindex 7 + 1
    with pytest.raises(CorruptSaveError, match=FILE_NAME):
        decoder.decode(bytes(game_db), 0, len(game_db), True, 7, 1, None, None)


def test_last_record_chain_window_reaches_the_end_of_game_db_not_end_minus_30() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    game_db_length = 100
    tag_offset = 75  # inside the final 30 bytes: a `next_record - 30` window would miss it
    game_db = bytearray(game_db_length)
    game_db[tag_offset : tag_offset + 4] = CONTRACT_TAG
    struct.pack_into("<I", game_db, tag_offset + layout.selector_offset, 8)
    struct.pack_into("<I", game_db, tag_offset + layout.team_id_offset, 12345)
    struct.pack_into("<I", game_db, tag_offset + layout.wage_offset, 999)
    contract, _on_loan, _loan_uid, _loan_name, _loan_start, _loan_end = decoder.decode(
        bytes(game_db), 0, game_db_length, True, 7, 1, None, None
    )
    assert contract is not None
    # The record carries no start date, so it fills the chain but is not in effect.
    assert [entry.wage for entry in contract.chain] == [999]


def test_last_player_chain_window_integration_through_fmsave_open(tmp_path: Path) -> None:
    """Pins the `is_last_record` plumbing from `Save._decode_player_tables` through
    `PlayerDecoder.decode` to `ContractDecoder.decode`: the sole (and so last) player's chain
    tag sits in the final bytes of `game_db`, where it fits (21 bytes needed after the tag)
    but is inside the last 30 bytes, so a `record_window_end - 30` window would miss it.
    """
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    player_bytes = _player_bytes(pindex=60, uid=900020, team_id=0xFFFFFFFF)
    minimal_chain_record = bytearray(21)
    minimal_chain_record[0:4] = CONTRACT_TAG
    struct.pack_into("<I", minimal_chain_record, layout.selector_offset, 61)  # pindex 60 + 1
    struct.pack_into("<I", minimal_chain_record, layout.team_id_offset, NORTHBRIDGE_TEAM_A)
    struct.pack_into("<I", minimal_chain_record, layout.wage_offset, 7000)
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body(
            [NORTHBRIDGE_CLUB, SOUTHPORT_CLUB],
            [NORTHBRIDGE_STATUS, SOUTHPORT_STATUS],
            gap_bytes=2000,
        )
        + player_bytes
        + bytes(minimal_chain_record)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    tag_offset_in_game_db = len(game_db) - len(minimal_chain_record)
    assert len(game_db) - tag_offset_in_game_db < 30

    sections = [
        SectionFrame("game_db", game_db) if section.name == "game_db" else section
        for section in default_sections()
    ]
    fragment_path = build_container_fragment(sections).write(
        tmp_path / "Private Folder" / FILE_NAME
    )
    with fmsave.open(fragment_path) as career_save:
        contracts_table = career_save.contracts()
        matching_contracts = [
            contract for contract in contracts_table if contract.player_uid == 900020
        ]
        assert len(matching_contracts) == 1
        assert [entry.wage for entry in matching_contracts[0].chain] == [7000]


def test_negative_chain_search_start_is_clamped_to_zero() -> None:
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    record_offset = 5  # record_offset + chain_window_start_offset (-30) is negative
    tag_offset = 2
    game_db_length = 100
    game_db = bytearray(game_db_length)
    game_db[tag_offset : tag_offset + 4] = CONTRACT_TAG
    struct.pack_into("<I", game_db, tag_offset + layout.selector_offset, 8)
    struct.pack_into("<I", game_db, tag_offset + layout.team_id_offset, 54321)
    struct.pack_into("<I", game_db, tag_offset + layout.wage_offset, 111)
    contract, _on_loan, _loan_uid, _loan_name, _loan_start, _loan_end = decoder.decode(
        bytes(game_db), record_offset, game_db_length, True, 7, 1, None, None
    )
    assert contract is not None
    assert [entry.wage for entry in contract.chain] == [111]


def _reference_locate_tail(
    game_db: bytes, chain_tag_offset: int, layout: ContractLayout
) -> int | None:
    """A straightforward, un-optimized port of the tail locator: try every event count from
    0 up, forward, checking each byte directly. Kept only as a reference for the
    differential test below; the shipped `ContractDecoder._locate_tail` must agree with it
    on every candidate.
    """
    game_db_length = len(game_db)
    for event_count in range(layout.tail_max_event_count + 1):
        candidate = (
            chain_tag_offset - layout.tail_base_offset - layout.tail_step_bytes * event_count
        )
        if candidate < 0:
            return None
        if candidate + 46 > game_db_length:
            continue
        if game_db[candidate] != 0:
            continue
        if game_db[candidate + 1] != 0:
            continue
        if game_db[candidate + 3] != 3:
            continue
        four_field = int.from_bytes(game_db[candidate + 4 : candidate + 8], "little")
        if four_field != 4:
            continue
        stored_event_count = int.from_bytes(
            game_db[
                candidate + layout.tail_event_count_offset : candidate
                + layout.tail_event_count_offset
                + 4
            ],
            "little",
        )
        if stored_event_count != event_count:
            continue
        return candidate
    return None


def _plant_tail_candidate(
    game_db: bytearray,
    chain_tag_offset: int,
    event_count: int,
    layout: ContractLayout,
    *,
    corrupt: str | None = None,
) -> int | None:
    """Write a real (or, with `corrupt`, a deliberately broken) tail candidate at
    `event_count`'s position. `corrupt` is one of "zero0", "zero1" or "count", each
    breaking exactly the check that name describes. Returns the candidate offset, or None
    when it does not fit the buffer.
    """
    candidate = chain_tag_offset - layout.tail_base_offset - layout.tail_step_bytes * event_count
    if candidate < 0 or candidate + 46 > len(game_db):
        return None
    game_db[candidate] = 1 if corrupt == "zero0" else 0
    game_db[candidate + 1] = 1 if corrupt == "zero1" else 0
    game_db[candidate + 3] = 3
    struct.pack_into("<I", game_db, candidate + 4, 4)
    stored_event_count = event_count + 1 if corrupt == "count" else event_count
    struct.pack_into("<I", game_db, candidate + layout.tail_event_count_offset, stored_event_count)
    return candidate


def test_tail_locator_matches_the_reference_loop_on_seeded_synthetic_buffers() -> None:
    """Differential test: the fast rfind-based locator must find exactly what the original
    forward, 201-step loop finds, for many random buffers, tag positions and planted decoys.

    A tiny byte alphabet (instead of the full 0-255 range) makes structural byte patterns,
    including whole signatures, recur by chance far more often than real save bytes would,
    so the fast locator's bounds and rejection checks get exercised on their own, not just
    on the scenarios this test deliberately plants.
    """
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    random_generator = random.Random(20260915)
    small_alphabet = bytes(range(6))
    step_bytes = layout.tail_step_bytes
    boundary_event_counts = range(195, 206)
    planted_boundary_event_counts: set[int] = set()

    for _trial in range(1000):
        boundary_event_count: int | None = None
        boundary_candidate: int | None = None
        scenario = random_generator.random()
        if scenario < 0.12:
            # A genuine tail near the event-count boundary (195-205; tail_max_event_count
            # is 200), which needs a large buffer and a far tag offset to fit.
            buffer_length = random_generator.randint(6200, 7200)
            chain_tag_offset = random_generator.randint(6100, buffer_length - 1)
        elif scenario < 0.30:
            # Tag offsets near and below 87: the rfind end is chain_tag_offset - 66 - 29 +
            # 3 + 5 = chain_tag_offset - 87 (tail_base_offset 66, tail_step_bytes 29, a
            # 5-byte signature at E+3), so it is zero or negative for offsets up to 87.
            buffer_length = random_generator.randint(120, 400)
            chain_tag_offset = random_generator.randint(0, 90)
        else:
            buffer_length = random_generator.randint(120, 3000)
            chain_tag_offset = random_generator.randint(0, buffer_length - 1)

        game_db = bytearray(random_generator.choice(small_alphabet) for _ in range(buffer_length))

        if scenario < 0.12:
            # Planted at the drawn count as is, including counts past tail_max_event_count,
            # which neither locator may accept.
            boundary_event_count = random_generator.randint(
                boundary_event_counts.start, boundary_event_counts.stop - 1
            )
            boundary_candidate = _plant_tail_candidate(
                game_db, chain_tag_offset, boundary_event_count, layout
            )
            assert boundary_candidate is not None
            planted_boundary_event_counts.add(boundary_event_count)
        elif scenario < 0.42:
            # Two valid tails: the nearer one (lower event_count) must win.
            near_count = random_generator.randint(0, 5)
            far_count = near_count + random_generator.randint(2, 10)
            _plant_tail_candidate(game_db, chain_tag_offset, near_count, layout)
            _plant_tail_candidate(game_db, chain_tag_offset, far_count, layout)
        elif scenario < 0.55:
            # An off-stride signature: real sentinel bytes, but not a whole number of
            # tail_step_bytes away from the event_count = 0 position, so it must be
            # rejected by the "% step_bytes == 0" check. Its stored event count is set to
            # what a modulo-less floor division would compute (aligned_event_count, since
            # the extra shift is smaller than one step), so an implementation that drops
            # the modulo check cannot be saved by the stored-count check alone.
            aligned_event_count = random_generator.randint(0, 20)
            aligned_candidate = (
                chain_tag_offset - layout.tail_base_offset - step_bytes * aligned_event_count
            )
            off_stride_candidate = aligned_candidate - random_generator.randint(1, step_bytes - 1)
            if 0 <= off_stride_candidate and off_stride_candidate + 46 <= buffer_length:
                game_db[off_stride_candidate] = 0
                game_db[off_stride_candidate + 1] = 0
                game_db[off_stride_candidate + 3] = 3
                struct.pack_into("<I", game_db, off_stride_candidate + 4, 4)
                struct.pack_into(
                    "<I",
                    game_db,
                    off_stride_candidate + layout.tail_event_count_offset,
                    aligned_event_count,
                )
        elif scenario < 0.68:
            # A genuine, well-formed tail somewhere in range.
            _plant_tail_candidate(
                game_db, chain_tag_offset, random_generator.randint(0, 20), layout
            )
        elif scenario < 0.85:
            # An on-stride signature with one check deliberately broken.
            _plant_tail_candidate(
                game_db,
                chain_tag_offset,
                random_generator.randint(0, 20),
                layout,
                corrupt=random_generator.choice(["zero0", "zero1", "count"]),
            )
        # The remaining share of trials plants nothing: pure small-alphabet noise.

        frozen_game_db = bytes(game_db)
        fast_result = decoder._locate_tail(frozen_game_db, chain_tag_offset)
        reference_result = _reference_locate_tail(frozen_game_db, chain_tag_offset, layout)
        if boundary_event_count is not None:
            expected_reference_result = (
                None if boundary_event_count > layout.tail_max_event_count else boundary_candidate
            )
            assert reference_result == expected_reference_result, (
                chain_tag_offset,
                buffer_length,
                boundary_event_count,
            )
        assert fast_result == reference_result, (chain_tag_offset, buffer_length, scenario)

    # Every count on both sides of tail_max_event_count was really planted.
    assert planted_boundary_event_counts == set(boundary_event_counts)


BONUS_RECORD_PINDEX = 7
BONUS_RECORD_PLAYER_UID = 900040
FICTIONAL_CLAUSES = (
    (0xFFFFFFFF, 25, 0x0F),
    (46000, 0xFFFF, 0x20),
    (500000, 0xFFFF, 0x00),
)
EXPECTED_FICTIONAL_CLAUSES = (
    ("TOP_DIVISION_RELEGATION_SALARY_DROP", 15, 25, None),
    ("APPEARANCE_FEE", 32, None, 46000),
    ("MINIMUM_FEE_RELEASE", 0, None, 500000),
)
ONE_COMPETITION_BONUS = clause_bonus_lists_bytes(competition_bonuses=((9001, 150000),))
ONE_AWARD_BONUS = clause_bonus_lists_bytes(award_bonuses=((4, 64000),))
TEAM_ID_CLAUSE_MARKER = struct.pack("<II", NORTHBRIDGE_TEAM_A, 0)


def _bonus_record(
    *,
    clause_suffix: bytes | None = None,
    clause_marker: bytes = CONTRACT_CLAUSE_MARKER,
    clauses: tuple[tuple[int, int, int], ...] = FICTIONAL_CLAUSES,
    events: int = 0,
) -> tuple[bytes, int]:
    return contract_bytes(
        selector=BONUS_RECORD_PINDEX + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2400,
        start=packed_date(1, 2029),
        tail={"end": packed_date(1, 2033), "status": 4},
        head={"type": 1, "money_a": 81000, "money_b": 3, "money_c": 7},
        clauses=clauses,
        events=events,
        clause_marker=clause_marker,
        clause_suffix=clause_suffix,
    )


def _decode_bonus_record(record: bytes) -> tuple[Contract, ContractDecoder]:
    decoder = _test_contract_decoder(registered_contract_layout())
    game_db = record + bytes(64)
    contract, _on_loan, _loan_uid, _loan_name, _loan_start, _loan_end = decoder.decode(
        game_db, 0, len(game_db), True, BONUS_RECORD_PINDEX, BONUS_RECORD_PLAYER_UID, None, None
    )
    assert contract is not None
    return contract, decoder


def _clause_rows(contract: Contract) -> tuple[tuple[str, int, int | None, int | None], ...]:
    return tuple(
        (clause.kind.label.name, clause.kind.raw, clause.parameter, clause.value)
        for clause in contract.clauses
    )


@pytest.mark.parametrize("events", [0, 2])
@pytest.mark.parametrize(
    "clause_suffix",
    [
        pytest.param(ONE_COMPETITION_BONUS, id="competition-list-only"),
        pytest.param(
            clause_bonus_lists_bytes(award_bonuses=((4, 64000), (5, 58000))),
            id="award-list-only",
        ),
        pytest.param(
            clause_bonus_lists_bytes(
                competition_bonuses=((9001, 150000), (9002, 90000), (9003, 45000)),
                award_bonuses=((4, 64000), (5, 58000), (6, 20000)),
            ),
            id="both-lists",
        ),
        pytest.param(clause_bonus_lists_bytes(award_bonuses=()), id="award-flag-with-no-awards"),
    ],
)
def test_a_clause_table_followed_by_bonus_lists_decodes_its_clauses_type_and_head(
    clause_suffix: bytes, events: int
) -> None:
    record, _tag_offset = _bonus_record(clause_suffix=clause_suffix, events=events)
    contract, decoder = _decode_bonus_record(record)
    assert _clause_rows(contract) == EXPECTED_FICTIONAL_CLAUSES
    assert contract.kind is not None
    assert contract.kind.label is ContractType.FULL_TIME
    assert contract.unknown["money_a"] == 81000
    assert contract.unknown["money_c"] == 7
    assert contract.event_count == events
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.tails_parsed == 1
    assert stats.tails_without_clause_table == 0
    assert stats.clause_tables == 1
    assert stats.clause_tables_ending_at_tail == 1
    assert stats.head_ok == 1


def test_an_empty_clause_table_followed_by_bonus_lists_is_found() -> None:
    record, _tag_offset = _bonus_record(clause_suffix=ONE_AWARD_BONUS, clauses=())
    contract, decoder = _decode_bonus_record(record)
    assert contract.clauses == ()
    assert contract.kind is not None
    assert contract.unknown["money_a"] == 81000
    assert decoder.stats(player_count=1, contract_count=1).clause_tables == 1


@pytest.mark.parametrize(
    "clause_suffix",
    [
        pytest.param(None, id="no-bonus-lists"),
        pytest.param(ONE_AWARD_BONUS, id="award-list"),
    ],
)
@pytest.mark.parametrize(
    "clause_marker",
    [
        pytest.param(struct.pack("<II", NORTHBRIDGE_TEAM_A, 0), id="own-team-id"),
        pytest.param(struct.pack("<II", SOUTHPORT_TEAM_ID, 0), id="another-team-id"),
    ],
)
def test_a_clause_table_marked_with_a_team_id_is_found(
    clause_marker: bytes, clause_suffix: bytes | None
) -> None:
    record, _tag_offset = _bonus_record(clause_marker=clause_marker, clause_suffix=clause_suffix)
    contract, decoder = _decode_bonus_record(record)
    assert _clause_rows(contract) == EXPECTED_FICTIONAL_CLAUSES
    assert contract.kind is not None
    assert contract.unknown["money_b"] == 3
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.clause_tables == 1
    assert stats.tails_without_clause_table == 0


def _with_byte(data: bytes, index: int, value: int) -> bytes:
    changed = bytearray(data)
    changed[index] = value
    return bytes(changed)


@pytest.mark.parametrize(
    ("clause_marker", "clause_suffix"),
    [
        pytest.param(
            CONTRACT_CLAUSE_MARKER,
            _with_byte(ONE_COMPETITION_BONUS, 6, 0x08),
            id="competition-item-prefix",
        ),
        pytest.param(
            CONTRACT_CLAUSE_MARKER, _with_byte(ONE_AWARD_BONUS, 6, 0x02), id="award-item-prefix"
        ),
        pytest.param(
            CONTRACT_CLAUSE_MARKER,
            _with_byte(clause_bonus_lists_bytes(award_bonuses=()), 1, 2),
            id="award-flag-neither-0-nor-1",
        ),
        pytest.param(
            CONTRACT_CLAUSE_MARKER,
            _with_byte(ONE_AWARD_BONUS, 2, 2),
            id="award-count-runs-past-the-tail",
        ),
        # Four bytes after the entries put a table with the FF marker where the fast path looks,
        # so these two use a team-id marker, which only the fallback accepts.
        pytest.param(
            TEAM_ID_CLAUSE_MARKER, bytes([1, 0, 0, 0]), id="competition-list-runs-past-the-tail"
        ),
        pytest.param(TEAM_ID_CLAUSE_MARKER, bytes([0, 0, 1, 0]), id="nonzero-trailer"),
        pytest.param(CONTRACT_CLAUSE_MARKER, bytes(5), id="ends-one-byte-before-the-tail"),
        pytest.param(b"\xff" * 7 + b"\xfe", None, id="marker-ff-run-broken-at-the-end"),
        pytest.param(b"\xfe" + b"\xff" * 7, None, id="marker-ff-run-broken-at-the-start"),
        pytest.param(b"\xff" * 4 + bytes(4), None, id="marker-team-id-all-ff"),
        pytest.param(bytes(8), None, id="marker-team-id-all-zero"),
        pytest.param(
            struct.pack("<II", NORTHBRIDGE_TEAM_A, 1), None, id="marker-team-id-without-zero-word"
        ),
        pytest.param(b"\xff" * 7 + b"\xfe", ONE_AWARD_BONUS, id="marker-broken-before-bonus-lists"),
    ],
)
def test_near_miss_clause_tables_are_rejected(clause_marker: bytes, clause_suffix: bytes) -> None:
    record, _tag_offset = _bonus_record(clause_marker=clause_marker, clause_suffix=clause_suffix)
    contract, decoder = _decode_bonus_record(record)
    assert contract.squad_status is not None  # the tail itself still parses
    assert contract.clauses == ()
    assert contract.kind is None
    assert "money_a" not in contract.unknown
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.tails_parsed == 1
    assert stats.clause_tables == 0
    assert stats.tails_without_clause_table == 1


def test_a_clause_table_with_a_broken_zero_run_is_rejected() -> None:
    record, _tag_offset = _bonus_record(clause_suffix=ONE_AWARD_BONUS)
    marker_offset = record.rfind(CONTRACT_CLAUSE_MARKER + bytes(3) + bytes([3]))
    assert marker_offset >= 0
    contract, decoder = _decode_bonus_record(_with_byte(record, marker_offset + 9, 1))
    assert contract.clauses == ()
    assert decoder.stats(player_count=1, contract_count=1).tails_without_clause_table == 1


def test_a_tail_with_no_clause_table_is_counted() -> None:
    record, _tag_offset = contract_bytes(
        selector=BONUS_RECORD_PINDEX + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=2400,
        start=packed_date(1, 2029),
        tail={"end": packed_date(1, 2033), "status": 4},
        clause_table=False,
    )
    contract, decoder = _decode_bonus_record(record)
    assert contract.clauses == ()
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.tails_parsed == 1
    assert stats.tails_without_clause_table == 1


def test_a_plain_clause_table_is_found_by_the_fast_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_fallback(
        self: ContractDecoder, game_db: bytes, tail_offset: int
    ) -> tuple[int, int] | None:
        raise AssertionError("the fallback ran although the fast path finds this table")

    monkeypatch.setattr(ContractDecoder, "_locate_clause_base_fallback", failing_fallback)
    record, _tag_offset = _bonus_record()
    contract, decoder = _decode_bonus_record(record)
    assert _clause_rows(contract) == EXPECTED_FICTIONAL_CLAUSES
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.clause_tables == 1
    assert stats.clause_tables_ending_at_tail == 1


def test_a_plain_table_with_nonzero_bytes_after_its_entries_is_found_but_not_counted_whole() -> (
    None
):
    record, _tag_offset = _bonus_record(clause_suffix=bytes([0, 0, 0, 1]))
    contract, decoder = _decode_bonus_record(record)
    assert _clause_rows(contract) == EXPECTED_FICTIONAL_CLAUSES
    stats = decoder.stats(player_count=1, contract_count=1)
    assert stats.clause_tables == 1
    assert stats.clause_tables_ending_at_tail == 0


@pytest.mark.parametrize("clause_count", [0, 1, 5, 23])
def test_the_fallback_finds_the_same_plain_table_as_the_fast_path(clause_count: int) -> None:
    clauses = tuple((1000 + index, 0xFFFF, 0x20 + index % 8) for index in range(clause_count))
    record, tag_offset = _bonus_record(clauses=clauses)
    decoder = _test_contract_decoder(registered_contract_layout())
    tail_offset = decoder._locate_tail(record, tag_offset)
    assert tail_offset is not None
    fast_path_result = decoder._locate_clause_base(record, tail_offset)
    assert fast_path_result is not None
    assert fast_path_result[1] == clause_count
    assert decoder._locate_clause_base_fallback(record, tail_offset) == fast_path_result


def test_the_fallback_agrees_with_the_fast_path_on_seeded_tables() -> None:
    """Seeded tables with realistic entries, random bonus lists and either marker form: every
    table decodes to its planted clauses, and wherever the fast path finds a table the fallback
    finds the same one.
    """
    layout = registered_contract_layout()
    decoder = _test_contract_decoder(layout)
    random_generator = random.Random(20260916)
    fast_path_agreements = 0
    for _trial in range(300):
        clause_count = random_generator.randint(0, layout.clause_max_count)
        clauses = tuple(
            (
                random_generator.choice((0xFFFFFFFF, random_generator.randint(1, 2**31))),
                random_generator.choice((0xFFFF, random_generator.randint(1, 400))),
                random_generator.randint(0, 0x3F),
            )
            for _clause in range(clause_count)
        )
        competition_bonuses = tuple(
            (random_generator.randint(1, 5000), random_generator.randint(1, 2**31))
            for _bonus in range(random_generator.choice((0, 0, 1, 2, 3)))
        )
        award_bonuses = (
            None
            if random_generator.random() < 0.5
            else tuple(
                (random_generator.randint(0, 4000), random_generator.randint(1, 2**31))
                for _bonus in range(random_generator.randint(0, 3))
            )
        )
        clause_marker = (
            CONTRACT_CLAUSE_MARKER
            if random_generator.random() < 0.7
            else struct.pack("<II", random_generator.randint(1, 3_000_000), 0)
        )
        record, tag_offset = _bonus_record(
            clauses=clauses,
            clause_marker=clause_marker,
            clause_suffix=clause_bonus_lists_bytes(
                competition_bonuses=competition_bonuses, award_bonuses=award_bonuses
            ),
            events=random_generator.randint(0, 3),
        )
        contract, _decoder = _decode_bonus_record(record)
        expected_rows = tuple(
            (
                CodedValue.from_raw(ClauseKind, kind).label.name,
                kind,
                None if parameter == 0xFFFF else parameter,
                None if value == 0xFFFFFFFF else value,
            )
            for value, parameter, kind in clauses
        )
        assert _clause_rows(contract) == expected_rows

        tail_offset = decoder._locate_tail(record, tag_offset)
        assert tail_offset is not None
        fast_path_result = decoder._locate_clause_base(record, tail_offset)
        if fast_path_result is not None:
            assert decoder._locate_clause_base_fallback(record, tail_offset) == fast_path_result
            fast_path_agreements += 1
    # About one table in seven has the FF marker and empty bonus lists, where the fast path looks.
    assert fast_path_agreements > 20


@pytest.mark.parametrize(
    ("raw_kind", "expected_name"),
    [
        (0x00, "MINIMUM_FEE_RELEASE"),
        (0x0F, "TOP_DIVISION_RELEGATION_SALARY_DROP"),
        (0x10, "MINIMUM_FEE_RELEASE_FOREIGN"),
        (0x12, "MINIMUM_FEE_RELEASE_DOMESTIC"),
        (0x16, "OPTIONAL_EXTENSION_BY_CLUB"),
        (0x20, "APPEARANCE_FEE"),
        (0x22, "SHUTOUT_BONUS"),
        (0x25, "INTERNATIONAL_CAP_BONUS"),
        (0x26, "UNUSED_SUBSTITUTE_FEE"),
        (0x29, "SEASONAL_LANDMARK_COMBINED_GOALS_AND_ASSISTS"),
        (0x01, "RELEGATION_RELEASE"),
        (0x02, "NON_PROMOTION_RELEASE"),
        (0x11, "MINIMUM_FEE_RELEASE_DOMESTIC_HIGHER_DIVISION"),
        (0x27, "UNKNOWN"),
    ],
)
def test_clause_kinds_confirmed_in_game_are_named(raw_kind: int, expected_name: str) -> None:
    kind = CodedValue.from_raw(ClauseKind, raw_kind)
    assert kind.label.name == expected_name
    assert kind.raw == raw_kind


@pytest.mark.parametrize(
    ("raw_status", "expected_name"),
    [
        (1, "STAR_PLAYER"),
        (2, "IMPORTANT_PLAYER"),
        (9, "EMERGENCY_BACKUP"),
        (14, "B_TEAM_REGULAR"),
        (15, "FIRST_CHOICE_GOALKEEPER"),
        (16, "CUP_GOALKEEPER"),
        (17, "DOMESTIC_CUP_GOALKEEPER"),
        (18, "CONTINENTAL_CUP_GOALKEEPER"),
        (20, "BACKUP"),
        # 9 and 21 both show "Emergency Backup"; the code says which list it came from.
        (21, "GOALKEEPER_EMERGENCY_BACKUP"),
        (22, "SURPLUS_TO_REQUIREMENTS"),
        # No holder of 6, 8, 12 or 19 exists in any corpus save, so no label confirms them.
        (6, "UNKNOWN"),
        (8, "UNKNOWN"),
        (12, "UNKNOWN"),
        (19, "UNKNOWN"),
    ],
)
def test_squad_statuses_confirmed_in_game_are_named(raw_status: int, expected_name: str) -> None:
    status = CodedValue.from_raw(SquadStatus, raw_status)
    assert status.label.name == expected_name
    assert status.raw == raw_status


def test_field_status_resolves_contract_wage_through_contract_class() -> None:
    assert field_status(Player, "contract.wage") == "unconfirmed"
    assert field_status(Player, "on_loan") == "verified"
    assert field_status(Player, "loan_start") == "verified"
    assert field_status(Player, "loan_end") == "verified"
    assert field_status(Contract, "loan_start") == "verified"
    assert field_status(Contract, "loan_end") == "verified"
    assert field_status(Clause, "kind") == "verified"
    assert field_status(ContractChainEntry, "wage") == "unconfirmed"


def test_a_derived_field_carries_the_status_of_what_it_is_taken_from() -> None:
    """A copy never claims more than its source, and one value never gets two answers.

    The loan parent club is the contracting club under another name, and the contract start
    and end are the chain record's own start and end.
    """
    for copied_field, source_field in (
        ("loan_parent_club_uid", "club_uid"),
        ("loan_parent_club_name", "club_name"),
    ):
        assert field_status(Contract, copied_field) == field_status(Contract, source_field)
        assert field_status(Contract, copied_field) == "unconfirmed", copied_field
        assert field_status(Player, copied_field) == "unconfirmed", copied_field
    assert field_status(Contract, "start") == field_status(ContractChainEntry, "start")
    assert field_status(Contract, "start") == "unconfirmed"
    assert field_status(Contract, "end") == field_status(ContractChainEntry, "end")
    assert field_status(Contract, "end") == "verified"
    assert field_status(Clause, "parameter") == "unconfirmed"
    assert field_status(Clause, "value") == "verified"


def test_pickle_and_deepcopy_round_trip_contract_records() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_A_UID)
    assert contract is not None
    assert pickle.loads(pickle.dumps(contract)) == contract
    assert copy.deepcopy(contract) == contract
    assert pickle.loads(pickle.dumps(contract.clauses[0])) == contract.clauses[0]
    assert copy.deepcopy(contract.clauses[0]) == contract.clauses[0]
    assert pickle.loads(pickle.dumps(contract.chain[0])) == contract.chain[0]
    assert copy.deepcopy(contract.chain[0]) == contract.chain[0]

    player, _contract = by_uid(decoded, PLAYER_A_UID)
    assert pickle.loads(pickle.dumps(player)) == player
    assert copy.deepcopy(player) == player

    table = Table((contract,), Contract)
    assert pickle.loads(pickle.dumps(table)) == table
    assert copy.deepcopy(table) == table


@pytest.fixture
def contracts_fragment_path(tmp_path: Path) -> Path:
    sections = [
        SectionFrame("game_db", example_game_db()) if section.name == "game_db" else section
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def test_contracts_returns_uids_in_player_order_and_filters_by_club(
    contracts_fragment_path: Path,
) -> None:
    with fmsave.open(contracts_fragment_path) as career_save:
        contracts_table = career_save.contracts()
        assert isinstance(contracts_table, Table)
        assert contracts_table.record_type is Contract
        assert [contract.player_uid for contract in contracts_table] == [
            PLAYER_A_UID,
            PLAYER_B_UID,
            PLAYER_C_UID,
            PLAYER_D_UID,
        ]
        # Each row's club is the club of its contract in effect.
        assert [contract.player_uid for contract in contracts_table.where(club_uid=5002)] == [
            PLAYER_A_UID
        ]
        filtered = contracts_table.where(club_uid=NORTHBRIDGE_CLUB_UID)
        assert [contract.player_uid for contract in filtered] == [PLAYER_C_UID, PLAYER_D_UID]


def _counting_player_decode(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap PlayerDecoder.decode with a call counter.

    Returns a one-item list holding the running count, so the test can read it after
    each Save call without needing a nonlocal or a class. Counting the per-record decode
    method, rather than a specific contract helper, keeps the test valid regardless of how
    the contract decode itself is structured.
    """
    from fmsave.readers.players import PlayerDecoder

    call_count = [0]
    original_decode = PlayerDecoder.decode

    def counting_decode(self: PlayerDecoder, *args: object, **kwargs: object) -> object:
        call_count[0] += 1
        return original_decode(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PlayerDecoder, "decode", counting_decode)
    return call_count


def test_contracts_called_first_also_builds_players_from_one_pass(
    contracts_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = _counting_player_decode(monkeypatch)
    with fmsave.open(contracts_fragment_path) as career_save:
        contracts_table = career_save.contracts()
        assert call_count[0] == 5  # every player is decoded exactly once
        assert career_save._context._cache[PLAYERS_TABLE_CACHE_KEY] is not None
        players_table = career_save.players()
        assert call_count[0] == 5  # players() does not decode again
        assert players_table is career_save._context._cache[PLAYERS_TABLE_CACHE_KEY]
        assert career_save.contracts() is contracts_table
        assert call_count[0] == 5


def test_players_called_first_also_builds_contracts_from_one_pass(
    contracts_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = _counting_player_decode(monkeypatch)
    with fmsave.open(contracts_fragment_path) as career_save:
        players_table = career_save.players()
        assert call_count[0] == 5
        assert career_save._context._cache[CONTRACTS_TABLE_CACHE_KEY] is not None
        contracts_table = career_save.contracts()
        assert call_count[0] == 5  # contracts() does not decode again
        assert contracts_table is career_save._context._cache[CONTRACTS_TABLE_CACHE_KEY]
        assert career_save.players() is players_table


def test_only_players_with_a_contract_appear_in_contracts_table(
    contracts_fragment_path: Path,
) -> None:
    with fmsave.open(contracts_fragment_path) as career_save:
        contracts_table = career_save.contracts()
        players_table = career_save.players()
        assert len(players_table) == 5
        assert len(contracts_table) == 4
        assert all(contract is not None for contract in contracts_table)
        assert PLAYER_E_UID not in [contract.player_uid for contract in contracts_table]
        excluded_player = players_table.by_uid(PLAYER_E_UID)
        assert excluded_player.contract is None


def test_export_flattens_contract_clauses_and_chain(contracts_fragment_path: Path) -> None:
    with fmsave.open(contracts_fragment_path) as career_save:
        contracts_table = career_save.contracts()

    columns = contracts_table.to_columns()
    assert "wage" in columns
    assert "clauses" in columns
    assert "chain" in columns

    records = list(contracts_table)
    assert_matches_json_normalize(records, Contract)

    with_clause_and_chain = next(
        record for record in records if record.clauses and len(record.chain) >= 2
    )
    assert with_clause_and_chain.player_uid == PLAYER_A_UID
    written_csv_path = contracts_fragment_path.parent / "contracts.csv"
    contracts_table.write_csv(written_csv_path)
    assert written_csv_path.exists()
