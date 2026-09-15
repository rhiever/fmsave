from __future__ import annotations

import copy
import dataclasses
import pickle
from datetime import date
from pathlib import Path

import pytest

import fmsave
import fmsave._context as context_module
from fmsave import Table
from fmsave._container import ContainerIndex
from fmsave._context import CLUB_INDEX_CACHE_KEY
from fmsave._errors import CorruptSaveError, ReaderCheckError
from fmsave._layouts import NamePoolLayout, PlayerRecordLayout, find_layout
from fmsave._save import PLAYERS_TABLE_CACHE_KEY
from fmsave.models.common import TransferValueState
from fmsave.models.players import Attributes, Personality, Player
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.names import NAME_POOLS_CACHE_KEY, locate_name_pools
from fmsave.readers.players import (
    PLAYER_RECORDS_CACHE_KEY,
    build_player_decoder,
    locate_player_records,
    window_end,
)
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    section_body,
)
from tests.fixtures.game_db import (
    STUB_STATUS_KIND,
    club_record_bytes,
    game_db_body,
    name_pools_bytes,
    player_record_bytes,
    status_record_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000

A_RATINGS = (1, 1, 18, 20, 15, 18, 2, 16, 3, 4, 5, 6, 7, 8, 9)
_A_RAW_ATTRIBUTES = [48] * 54
_A_RAW_ATTRIBUTES[0] = 1
_A_RAW_ATTRIBUTES[1] = 2
_A_RAW_ATTRIBUTES[2] = 3
_A_RAW_ATTRIBUTES[3] = 98
_A_RAW_ATTRIBUTES[4] = 100
_A_RAW_ATTRIBUTES[24] = 88
_A_RAW_ATTRIBUTES[25] = 33
A_RAW_ATTRIBUTES = tuple(_A_RAW_ATTRIBUTES)

SOUTHPORT_CLUB_UID = 5002
SOUTHPORT_TEAM_ID = 70003
SOUTHPORT_CLUB = club_record_bytes(
    club_index=1,
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
    ordinal=51,
    club_index=1,
    uid=SOUTHPORT_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=5,
    reputation=3000,
)

PLAYER_A = {
    "pindex": 11,
    "uid": 900001,
    "current_ability": 140,
    "potential_ability": 165,
    "bucket": 120,
    "home_reputation": 8000,
    "current_reputation": 8200,
    "world_reputation": 7900,
    "team_id": SOUTHPORT_TEAM_ID,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 4_500_000,
    "join_date": packed_date(60, 2029),
    "sharpness": 7000,
    "condition": 9500,
    "height_cm": 181,
}
PLAYER_B = {
    "pindex": 12,
    "uid": 900002,
    "current_ability": 100,
    "potential_ability": -8,
    "bucket": 90,
    "home_reputation": 5000,
    "current_reputation": 5100,
    "world_reputation": 4900,
    "team_id": 0xFFFFFFFF,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 0xFFFFFFFF,
    "join_date": packed_date(10, 2028),
    "sharpness": 6000,
    "condition": 8000,
    "height_cm": 175,
}
PLAYER_C = {
    "pindex": 13,
    "uid": 900003,
    "current_ability": 110,
    "potential_ability": 130,
    "bucket": 80,
    "home_reputation": 4000,
    "current_reputation": 4200,
    "world_reputation": 4100,
    "team_id": 99999,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 300_000_000,
    "join_date": packed_date(20, 2027),
    "sharpness": 5000,
    "condition": 7000,
    "height_cm": 178,
    "marker": packed_date(45, 2010),
}
PLAYER_D = {
    "pindex": 14,
    "uid": 900004,
    "current_ability": 95,
    "potential_ability": 105,
    "bucket": 70,
    "home_reputation": 3000,
    "current_reputation": 3200,
    "world_reputation": 3100,
    "team_id": 0xFFFFFFFF,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 0,
    "join_date": packed_date(30, 2026),
    "sharpness": 4000,
    "condition": 6000,
    "height_cm": 170,
}
REJECT_ZERO_CA = {
    "pindex": 15,
    "uid": 900005,
    "current_ability": 0,
    "potential_ability": 100,
    "bucket": 50,
    "home_reputation": 1000,
    "current_reputation": 1100,
    "world_reputation": 1200,
    "team_id": 0xFFFFFFFF,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 0,
    "join_date": packed_date(1, 2020),
    "sharpness": 1000,
    "condition": 1000,
    "height_cm": 180,
}
REJECT_UID_MISMATCH = {
    "pindex": 16,
    "uid": 900006,
    "current_ability": 100,
    "potential_ability": 100,
    "bucket": 50,
    "home_reputation": 1000,
    "current_reputation": 1100,
    "world_reputation": 1200,
    "team_id": 0xFFFFFFFF,
    "ratings": A_RATINGS,
    "raw_attributes": A_RAW_ATTRIBUTES,
    "transfer_value_raw": 0,
    "join_date": packed_date(1, 2020),
    "sharpness": 1000,
    "condition": 1000,
    "height_cm": 180,
    "doubled_uid": False,
}
STRAY_BLOCK = bytes([5]) * 69

# Distinct raw value per index (1..54): a wrong foot-index splice or attribute reorder
# changes at least one of the assertions in test_attribute_splice_keeps_each_value_in_place.
FOOT_SPLICE_RAW_ATTRIBUTES = tuple(range(1, 55))


def _scaled(raw_value: int) -> int:
    return max(1, (raw_value + 2) // 5)


def player_region_bytes() -> bytes:
    return (
        player_record_bytes(**PLAYER_A)
        + player_record_bytes(**PLAYER_B)
        + player_record_bytes(**PLAYER_C)
        + player_record_bytes(**PLAYER_D)
        + player_record_bytes(**REJECT_ZERO_CA)
        + player_record_bytes(**REJECT_UID_MISMATCH)
        + STRAY_BLOCK
    )


def example_game_db(*, leading_payload: bytes = b"") -> bytes:
    payload = (
        leading_payload
        + name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_region_bytes()
    )
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def registered_player_layout() -> PlayerRecordLayout:
    return find_layout(PlayerRecordLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_name_pool_layout() -> NamePoolLayout:
    return find_layout(NamePoolLayout, "game_db", GAME_DB_SCHEMA, "").layout


def build_index(game_db: bytes):
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    player_records = locate_player_records(
        game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME
    )
    club_index = read_club_index(game_db, find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME)
    return name_pools, player_records, club_index


def decode_all(game_db: bytes) -> list[Player]:
    _, player_records, club_index = build_index(game_db)
    decoder = build_player_decoder(player_records.layout, club_index)
    return [
        decoder.decode(game_db, record_offset) for record_offset in player_records.record_offsets
    ]


def by_uid(players: list[Player], uid: int) -> Player:
    for player in players:
        if player.uid == uid:
            return player
    raise AssertionError(f"no decoded player with uid {uid}")


def test_records_are_found_in_offset_order_with_the_right_markerless_count() -> None:
    game_db = example_game_db()
    _, player_records, _ = build_index(game_db)
    assert list(player_records.uids) == [900001, 900002, 900003, 900004]
    assert player_records.markerless_count == 1
    assert player_records.position_by_pindex[13] == 2
    assert player_records.position_by_uid[900003] == 2


def test_zero_current_ability_is_rejected() -> None:
    game_db = example_game_db()
    _, player_records, _ = build_index(game_db)
    assert 900005 not in player_records.uids


def test_doubled_uid_mismatch_is_rejected() -> None:
    game_db = example_game_db()
    _, player_records, _ = build_index(game_db)
    assert 900006 not in player_records.uids


def test_stray_block_with_no_valid_uid_is_rejected() -> None:
    game_db = example_game_db()
    _, player_records, _ = build_index(game_db)
    # Distinct from the offset-order test: the stray block must not shift a later record's
    # position or get inserted anywhere in the index.
    assert player_records.position_by_uid[900004] == 3
    assert len(player_records.record_offsets) == 4


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"potential_ability": -11}, id="PA below range"),
        pytest.param({"potential_ability": 201}, id="PA above range"),
        pytest.param({"bucket": 201}, id="bucket above range"),
        pytest.param({"uid": 0, "doubled_uid": True}, id="uid zero"),
        pytest.param({"uid": 0xFFFFFFFF, "doubled_uid": True}, id="uid missing-reference"),
    ],
)
def test_out_of_range_scalar_candidates_are_rejected(override: dict[str, object]) -> None:
    candidate = dict(PLAYER_D)
    candidate.update(override)
    candidate["pindex"] = 50
    candidate["uid"] = override.get("uid", 900050)
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**candidate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError):
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)


@pytest.mark.parametrize(
    ("rating_index", "bad_rating"),
    [pytest.param(0, 0, id="rating below range"), pytest.param(0, 21, id="rating above range")],
)
def test_out_of_range_rating_is_rejected(rating_index: int, bad_rating: int) -> None:
    ratings: list[int] = list(A_RATINGS)
    ratings[rating_index] = bad_rating
    candidate = dict(PLAYER_D)
    candidate["ratings"] = tuple(ratings)
    candidate["pindex"] = 51
    candidate["uid"] = 900051
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**candidate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError):
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)


@pytest.mark.parametrize(
    ("attribute_index", "bad_value"),
    [
        pytest.param(5, 0, id="attribute below range"),
        pytest.param(5, 101, id="attribute above range"),
    ],
)
def test_out_of_range_attribute_is_rejected(attribute_index: int, bad_value: int) -> None:
    raw_attributes = list(A_RAW_ATTRIBUTES)
    raw_attributes[attribute_index] = bad_value
    candidate = dict(PLAYER_D)
    candidate["raw_attributes"] = tuple(raw_attributes)
    candidate["pindex"] = 52
    candidate["uid"] = 900052
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**candidate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError):
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)


def test_marker_within_102_bytes_of_offset_zero_is_handled_cleanly() -> None:
    # A marker this close to the start of game_db makes marker_hit - 102 negative; the scan
    # must reject it without raising, and keep scanning the rest of the buffer normally.
    leading_payload = bytes(50) + bytes.fromhex("01006c07") + bytes(20)
    game_db = example_game_db(leading_payload=leading_payload)
    _, player_records, _ = build_index(game_db)
    assert list(player_records.uids) == [900001, 900002, 900003, 900004]


def test_valid_marker_less_block_before_name_pools_end_is_not_found() -> None:
    early_candidate = dict(PLAYER_D)
    early_candidate["pindex"] = 99
    early_candidate["uid"] = 900099
    early_candidate["marker"] = packed_date(1, 2000)  # not the scan marker: no false accept
    game_db = example_game_db(leading_payload=player_record_bytes(**early_candidate))
    _, player_records, _ = build_index(game_db)
    assert 900099 not in player_records.uids
    assert list(player_records.uids) == [900001, 900002, 900003, 900004]


def test_truncated_final_record_raises_corrupt_save_error() -> None:
    truncated_candidate = dict(PLAYER_D)
    truncated_candidate["pindex"] = 77
    truncated_candidate["uid"] = 900077
    full_record_bytes = player_record_bytes(**truncated_candidate)
    # The record starts 26 bytes in; keep bytes up to +100 (past attributes_end at +93, short
    # of decode_extent at +122).
    truncated_record_bytes = full_record_bytes[: 26 + 100]
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + truncated_record_bytes
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(CorruptSaveError) as error_info:
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message


def test_attribute_field_order_matches_the_attributes_dataclass() -> None:
    layout = registered_player_layout()
    assert layout.attribute_field_order == tuple(
        attribute_field.name for attribute_field in dataclasses.fields(Attributes)
    )


def test_attribute_splice_keeps_each_value_in_place() -> None:
    candidate = dict(PLAYER_A)
    candidate["raw_attributes"] = FOOT_SPLICE_RAW_ATTRIBUTES
    candidate["pindex"] = 60
    candidate["uid"] = 900060
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**candidate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    players = decode_all(game_db)
    player = by_uid(players, 900060)

    expected_raw = tuple(
        value for index, value in enumerate(FOOT_SPLICE_RAW_ATTRIBUTES) if index not in (24, 25)
    )
    expected_scaled = tuple(_scaled(value) for value in expected_raw)
    assert dataclasses.astuple(player.raw_attributes) == expected_raw
    assert dataclasses.astuple(player.attributes) == expected_scaled
    assert player.attributes.flair == _scaled(FOOT_SPLICE_RAW_ATTRIBUTES[26])
    assert player.attributes.concentration == _scaled(FOOT_SPLICE_RAW_ATTRIBUTES[53])
    assert player.raw_left_foot == FOOT_SPLICE_RAW_ATTRIBUTES[24]
    assert player.raw_right_foot == FOOT_SPLICE_RAW_ATTRIBUTES[25]
    assert player.left_foot == _scaled(FOOT_SPLICE_RAW_ATTRIBUTES[24])
    assert player.right_foot == _scaled(FOOT_SPLICE_RAW_ATTRIBUTES[25])


def test_player_a_ability_positions_and_attributes() -> None:
    players = decode_all(example_game_db())
    player_a = by_uid(players, 900001)
    assert player_a.natural_positions == ("DC", "DL", "DM")
    assert player_a.accomplished_positions == ("MC", "DR")
    assert player_a.attributes.crossing == 1
    assert player_a.attributes.dribbling == 1
    assert player_a.attributes.finishing == 1
    assert player_a.attributes.heading == 20
    assert player_a.attributes.long_shots == 20
    assert player_a.attributes.marking == 10
    assert player_a.raw_attributes.heading == 98
    assert player_a.left_foot == 18
    assert player_a.raw_left_foot == 88
    assert player_a.right_foot == 7
    assert player_a.transfer_value == 4_500_000
    assert player_a.transfer_value_state == TransferValueState.OK
    assert player_a.club_reputation is None
    assert player_a.club_fa_nation_id == 4
    assert player_a.team_slot == 0
    assert player_a.club_uid == SOUTHPORT_CLUB_UID
    assert player_a.club_name == "Example Southport"
    assert player_a.club_short_name == "Southport"
    assert player_a.club_nation_id == 3
    assert player_a.club_last_league_position is None
    assert player_a.club_join_date == date(2029, 3, 1)
    assert player_a.height_cm == 181


def test_player_b_negative_potential_and_free_agent() -> None:
    players = decode_all(example_game_db())
    player_b = by_uid(players, 900002)
    assert player_b.ability.potential is None
    assert player_b.ability.potential_range_code == -8
    assert player_b.team_id is None
    assert player_b.club_uid is None
    assert player_b.club_name is None
    assert player_b.club_short_name is None
    assert player_b.club_nation_id is None
    assert player_b.club_fa_nation_id is None
    assert player_b.club_reputation is None
    assert player_b.club_last_league_position is None
    assert player_b.team_slot is None
    assert player_b.transfer_value is None
    assert player_b.transfer_value_state == TransferValueState.UNSET


def test_player_c_is_markerless_with_an_unresolved_team() -> None:
    players = decode_all(example_game_db())
    player_c = by_uid(players, 900003)
    assert player_c.team_id == 99999
    assert player_c.club_uid is None
    assert player_c.club_name is None
    assert player_c.transfer_value is None
    assert player_c.transfer_value_state == TransferValueState.PLACEHOLDER


def test_player_d_has_a_zero_transfer_value() -> None:
    players = decode_all(example_game_db())
    player_d = by_uid(players, 900004)
    assert player_d.transfer_value is None
    assert player_d.transfer_value_state == TransferValueState.ZERO


def test_person_fields_are_empty_in_this_task() -> None:
    players = decode_all(example_game_db())
    player_a = by_uid(players, 900001)
    assert player_a.name is None
    assert player_a.first_name is None
    assert player_a.last_name is None
    assert player_a.common_name is None
    assert player_a.full_name is None
    assert player_a.legal_name is None
    assert player_a.birth_date is None
    assert player_a.age is None
    assert player_a.nation_id is None
    assert player_a.second_nation_ids == ()
    assert player_a.home_grown_nation_ids == ()
    assert player_a.home_grown_club_uids == ()
    assert player_a.home_grown_club_names == ()
    assert player_a.personality is None
    assert player_a.traits == ()
    assert player_a.trait_bits is None


def test_window_end_is_the_next_record_start_or_the_buffer_length() -> None:
    game_db = example_game_db()
    _, player_records, _ = build_index(game_db)
    assert window_end(player_records, 0, len(game_db)) == player_records.record_offsets[1]
    assert window_end(player_records, 3, len(game_db)) == len(game_db)


def test_no_player_records_found_raises_reader_check() -> None:
    game_db = section_body(".dat", GAME_DB_SCHEMA, name_pools_bytes([], [], []) + bytes(4096))
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError) as error_info:
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message


def test_repeated_uid_raises_reader_check() -> None:
    duplicate = dict(REJECT_ZERO_CA)
    duplicate["current_ability"] = 120
    duplicate["uid"] = 900001
    duplicate["pindex"] = 21
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**PLAYER_A)
        + player_record_bytes(**duplicate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError) as error_info:
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)
    message = str(error_info.value)
    assert "900001" in message
    assert FILE_NAME in message
    assert "game_db" in message


def test_repeated_pindex_raises_reader_check() -> None:
    duplicate = dict(REJECT_ZERO_CA)
    duplicate["current_ability"] = 120
    duplicate["pindex"] = 11
    duplicate["uid"] = 900022
    payload = (
        name_pools_bytes([], [], [])
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + player_record_bytes(**PLAYER_A)
        + player_record_bytes(**duplicate)
    )
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    with pytest.raises(ReaderCheckError) as error_info:
        locate_player_records(game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME)
    message = str(error_info.value)
    assert "pindex 11" in message
    assert FILE_NAME in message
    assert "game_db" in message


def test_player_and_related_records_survive_pickle_and_deepcopy() -> None:
    players = decode_all(example_game_db())
    player_a = by_uid(players, 900001)
    for example in (
        player_a,
        player_a.ability,
        player_a.reputation,
        player_a.attributes,
        player_a.positions,
    ):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)
    personality = Personality(10, 10, 10, 10, 10, 10, 10, 10)
    assert pickle.loads(pickle.dumps(personality)) == personality
    assert copy.deepcopy(personality) == personality
    players_table = Table(players, Player)
    assert pickle.loads(pickle.dumps(players_table)) == players_table
    assert copy.deepcopy(players_table) == players_table


def test_players_are_frozen() -> None:
    players = decode_all(example_game_db())
    player_a = by_uid(players, 900001)
    with pytest.raises(AttributeError):
        player_a.uid = 999999  # type: ignore[misc]
    with pytest.raises(AttributeError):
        player_a.ability.current = 1  # type: ignore[misc]


@pytest.fixture
def players_fragment_path(tmp_path: Path) -> Path:
    sections = [
        SectionFrame("game_db", example_game_db()) if section.name == "game_db" else section
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def test_save_players_returns_a_cached_table(players_fragment_path: Path) -> None:
    with fmsave.open(players_fragment_path) as career_save:
        players_table = career_save.players()
        assert isinstance(players_table, Table)
        assert players_table.record_type is Player
        assert [player.uid for player in players_table] == [900001, 900002, 900003, 900004]
        assert career_save.players() is players_table
        assert PLAYER_RECORDS_CACHE_KEY == "player_records"
        assert PLAYERS_TABLE_CACHE_KEY == "table:players"
        assert career_save._context._cache[PLAYERS_TABLE_CACHE_KEY] is players_table
        assert PLAYER_RECORDS_CACHE_KEY in career_save._context._cache
        assert NAME_POOLS_CACHE_KEY in career_save._context._cache
        assert CLUB_INDEX_CACHE_KEY in career_save._context._cache
        assert career_save._context.name_pools() is career_save._context.name_pools()
        assert career_save._context.player_records() is career_save._context.player_records()
        assert (
            career_save._context.player_records()
            is career_save._context._cache[PLAYER_RECORDS_CACHE_KEY]
        )
    assert career_save.closed
    with pytest.raises(fmsave.SaveClosedError):
        career_save.players()
    with pytest.raises(fmsave.SaveClosedError):
        career_save._context.name_pools()
    with pytest.raises(fmsave.SaveClosedError):
        career_save._context.player_records()
    assert len(players_table) == 4


def test_cold_players_decompresses_game_db_exactly_once(
    players_fragment_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section_reads: list[str] = []
    original_read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        section_reads.append(name)
        return original_read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)
    with fmsave.open(players_fragment_path) as career_save:
        career_save.players()
        assert section_reads == ["game_db"]
