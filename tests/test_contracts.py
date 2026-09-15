from __future__ import annotations

import copy
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
from fmsave._save import CONTRACTS_TABLE_CACHE_KEY, PLAYERS_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.models.common import ContractEndSource
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
from fmsave.readers.contracts import ContractDecoder, build_contract_decoder
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
    CONTRACT_TAG,
    STUB_STATUS_KIND,
    club_record_bytes,
    contract_bytes,
    fallback_contract_bytes,
    game_db_body,
    name_pools_bytes,
    player_record_bytes,
    status_record_bytes,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

EMPTY_CLUB_INDEX = ClubIndex(clubs=(), uid_by_club_index={}, club_by_uid={}, team_to_club={})

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
    record_one, _ = contract_bytes(
        selector=12,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=12000,
        start=packed_date(183, 2028),  # 2028-07-01
        tail={
            "end": packed_date(181, 2030),  # 2030-06-30
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
    record_two, _ = contract_bytes(
        selector=12,
        team_id=SOUTHPORT_TEAM_ID,
        wage=3000,
        start=packed_date(213, 2029),  # 2029-08-01
        tail={"end": packed_date(151, 2030), "status": 7},  # 2030-05-31
        head={"type": 1},
        clauses=(),
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
    assert contract.wage == 12000
    assert contract.start == date(2028, 7, 1)
    assert contract.end == date(2030, 6, 30)
    assert contract.end_source == ContractEndSource.TAIL
    assert contract.squad_status is not None
    assert contract.squad_status.label is SquadStatus.REGULAR_STARTER
    assert contract.type is not None
    assert contract.type.label is ContractType.FULL_TIME
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
    assert contract.club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.on_loan is True
    assert contract.loan_parent_club_uid == NORTHBRIDGE_CLUB_UID
    assert contract.loan_parent_club_name == "Northbridge FC"
    assert contract.chain_club_uids == (NORTHBRIDGE_CLUB_UID, SOUTHPORT_CLUB_UID)
    assert contract.tailed_chain_club_uids == (NORTHBRIDGE_CLUB_UID, SOUTHPORT_CLUB_UID)
    assert len(contract.chain) == 2
    assert contract.chain[1].wage == 3000
    assert player.on_loan is True
    assert player.loan_parent_club_uid == NORTHBRIDGE_CLUB_UID
    assert player.loan_parent_club_name == "Northbridge FC"
    assert player.contract is contract


def test_player_b_fallback_only() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_B_UID)
    assert contract is not None
    assert contract.start == date(2027, 1, 1)
    assert contract.end == date(2032, 6, 30)
    assert contract.end_source == ContractEndSource.FALLBACK
    assert contract.wage is None
    assert contract.on_loan is None
    assert contract.chain == ()


def test_player_c_null_tail_end_skips_fallback() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_C_UID)
    assert contract is not None
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.type is not None
    assert contract.type.label is ContractType.UNKNOWN
    assert contract.type.raw == 2


def test_player_d_broken_tail_and_stale_fallback() -> None:
    decoded = decode_all(example_game_db())
    _player, contract = by_uid(decoded, PLAYER_D_UID)
    assert contract is not None
    assert contract.end is None
    assert contract.end_source == ContractEndSource.NONE
    assert contract.chain[0].has_tail is False
    assert contract.squad_status is None
    assert contract.clauses == ()


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
        clauses=((100, 10, 0x01),),
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
    assert contract.type is None
    assert contract.unknown.get("money_a") is None
    assert contract.unknown.get("money_b") is None
    assert contract.unknown.get("money_c") is None
    assert len(contract.clauses) == 1
    assert contract.clauses[0].kind.label is ClauseKind.RELEGATION_RELEASE


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


def _test_contract_decoder(layout: ContractLayout) -> ContractDecoder:
    return build_contract_decoder(layout, EMPTY_CLUB_INDEX, date(2031, 1, 1), FILE_NAME)


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
    contract, _on_loan, _loan_uid, _loan_name = decoder.decode(
        bytes(game_db), 0, game_db_length, True, 7, 1, None, None
    )
    assert contract is not None
    assert contract.wage == 999


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
    contract, _on_loan, _loan_uid, _loan_name = decoder.decode(
        bytes(game_db), record_offset, game_db_length, True, 7, 1, None, None
    )
    assert contract is not None
    assert contract.wage == 111


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


def test_tail_locator_matches_the_reference_loop_on_seeded_synthetic_buffers() -> None:
    """Differential test: the fast rfind-based locator must find exactly what the original
    forward, 201-step loop finds, for many random buffers and tag positions.
    """
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout
    decoder = _test_contract_decoder(layout)
    random_generator = random.Random(20260915)
    for _trial in range(500):
        buffer_length = random_generator.randint(200, 6000)
        game_db = bytearray(random_generator.randbytes(buffer_length))
        chain_tag_offset = random_generator.randint(0, buffer_length - 1)

        # Bias roughly a third of trials toward a real, well-formed tail somewhere in
        # range, so the differential test also covers true positives, not only noise.
        if random_generator.random() < 0.34:
            event_count = random_generator.randint(0, min(20, layout.tail_max_event_count))
            candidate = (
                chain_tag_offset - layout.tail_base_offset - layout.tail_step_bytes * event_count
            )
            if 0 <= candidate and candidate + 46 <= buffer_length:
                game_db[candidate] = 0
                game_db[candidate + 1] = 0
                game_db[candidate + 3] = 3
                struct.pack_into("<I", game_db, candidate + 4, 4)
                struct.pack_into(
                    "<I", game_db, candidate + layout.tail_event_count_offset, event_count
                )

        frozen_game_db = bytes(game_db)
        fast_result = decoder._locate_tail(frozen_game_db, chain_tag_offset)
        reference_result = _reference_locate_tail(frozen_game_db, chain_tag_offset, layout)
        assert fast_result == reference_result, (chain_tag_offset, buffer_length)


def test_field_status_resolves_contract_wage_through_contract_class() -> None:
    assert field_status(Player, "contract.wage") == "unconfirmed"
    assert field_status(Player, "on_loan") == "verified"
    assert field_status(Contract, "start") == "verified"
    assert field_status(Clause, "kind") == "verified"
    assert field_status(ContractChainEntry, "wage") == "unconfirmed"


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
        filtered = contracts_table.where(club_uid=NORTHBRIDGE_CLUB_UID)
        assert [contract.player_uid for contract in filtered] == [
            PLAYER_A_UID,
            PLAYER_C_UID,
            PLAYER_D_UID,
        ]


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
