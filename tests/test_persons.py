from __future__ import annotations

import copy
import pickle
import re
from datetime import date

import pytest

import fmsave
from fmsave._errors import CorruptSaveError, ReaderCheckError
from fmsave._layouts import NamePoolLayout, PersonBlockLayout, PlayerRecordLayout, find_layout
from fmsave.models.players import Trait
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.names import locate_name_pools
from fmsave.readers.persons import (
    _personality_pattern,
    build_person_block_decoder,
)
from fmsave.readers.player_scan import locate_player_records, window_end
from fmsave.readers.players import build_player_decoder
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    packed_date,
    section_body,
)
from tests.fixtures.game_db import (
    STUB_STATUS_KIND,
    club_record_bytes,
    game_db_body,
    name_pools_bytes,
    person_block_bytes,
    player_record_bytes,
    relation_entry_bytes,
    status_record_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
CLOCK = date(2031, 3, 1)

FIRST_NAMES = ["Alex", "Sam", ""]
SURNAMES = ["Example", "Sample"]
COMMON_NAMES = ["Exo", "Pim"]

SOUTHPORT_CLUB_UID = 5002
SOUTHPORT_CLUB_INDEX = 2
SOUTHPORT_TEAM_ID = 70003
SOUTHPORT_CLUB = club_record_bytes(
    club_index=SOUTHPORT_CLUB_INDEX,
    uid=SOUTHPORT_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=78,
    name="Southport Example",
    short_name="Southport",
    team_ids=(SOUTHPORT_TEAM_ID,),
    float_anchor_only=True,
)
SOUTHPORT_STATUS = status_record_bytes(
    ordinal=51,
    club_index=SOUTHPORT_CLUB_INDEX,
    uid=SOUTHPORT_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=5,
    reputation=3000,
)

DEFAULT_PERSONALITY = (15, 12, 9, 20, 18, 7, 11, 3)

PLAYER_A_RELATIONS = (
    relation_entry_bytes(12, 8, 9, 100),
    relation_entry_bytes(40, 8, 9, 15),
    relation_entry_bytes(12, 8, 9, 100),
    relation_entry_bytes(5, 8, 70),
    relation_entry_bytes(2, 1, 72),
    relation_entry_bytes(7, 3, 1),
)

PLAYER_A_BLOCK = person_block_bytes(
    first_name_id=0,
    surname_id=0,
    common_name_id=0xFFFFFFFF,
    legal_name=None,
    birth=packed_date(60, 2004),
    nation_id=44,
    personality=DEFAULT_PERSONALITY,
    trait_bits=(1 << 13) | (1 << 40),
    relations=PLAYER_A_RELATIONS,
)

PLAYER_B_BLOCK = person_block_bytes(
    first_name_id=0,
    surname_id=0,
    common_name_id=1,
    legal_name="Alexander Sample Example",
    birth=packed_date(62, 2004),
    nation_id=44,
    personality=DEFAULT_PERSONALITY,
    trait_bits=0,
    relations=(),
)

PLAYER_C_BLOCK = person_block_bytes(
    first_name_id=1,
    surname_id=1,
    common_name_id=2,
    legal_name=None,
    birth=packed_date(60, 2004),
    nation_id=44,
    personality=DEFAULT_PERSONALITY,
    trait_bits=0,
    relations=(),
)

PLAYER_D_BLOCK = person_block_bytes(
    first_name_id=0xFFFFFFFF,
    surname_id=1,
    common_name_id=0xFFFFFFFF,
    legal_name="Legal Only",
    birth=packed_date(60, 2004),
    nation_id=44,
    personality=DEFAULT_PERSONALITY,
    trait_bits=0,
    relations=(),
)


def registered_person_layout() -> PersonBlockLayout:
    return find_layout(PersonBlockLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_name_pool_layout() -> NamePoolLayout:
    return find_layout(NamePoolLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_player_layout() -> PlayerRecordLayout:
    return find_layout(PlayerRecordLayout, "game_db", GAME_DB_SCHEMA, "").layout


def game_db_prefix() -> bytes:
    return name_pools_bytes(FIRST_NAMES, SURNAMES, COMMON_NAMES) + game_db_body(
        [SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000
    )


def build_decoder(game_db: bytes, *, clock: date = CLOCK):
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    club_index = read_club_index(game_db, find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME)
    return build_person_block_decoder(
        registered_person_layout(), name_pools, club_index, clock, FILE_NAME, game_db
    )


def decode_block(block: bytes, *, clock: date = CLOCK):
    prefix = game_db_prefix()
    game_db = prefix + block
    decoder = build_decoder(game_db, clock=clock)
    return decoder.decode(game_db, len(prefix), len(game_db))


def test_player_a_names_birth_nation_relations_personality_and_traits() -> None:
    person = decode_block(PLAYER_A_BLOCK)
    assert person is not None
    assert person.name == "Alex Example"
    assert person.full_name == "Alex Example"
    assert person.common_name is None
    assert person.legal_name is None
    assert person.birth_date == date(2004, 2, 29)
    assert person.age == 27
    assert person.nation_id == 44
    assert person.second_nation_ids == (12, 40)
    assert person.home_grown_nation_ids == (5,)
    assert person.home_grown_club_uids == (5002,)
    assert person.home_grown_club_names == ("Southport Example",)
    assert person.personality.pressure == 20
    assert person.trait_bits == (1 << 13) | (1 << 40)
    assert [trait.label for trait in person.traits] == [
        Trait.LIKES_TO_TRY_TO_BEAT_OFFSIDE_TRAP,
        Trait.UNKNOWN,
    ]
    assert person.traits[1].raw == 40


def test_player_b_common_name_wins_and_legal_name_and_age() -> None:
    person = decode_block(PLAYER_B_BLOCK)
    assert person is not None
    assert person.name == "Pim"
    assert person.legal_name == "Alexander Sample Example"
    assert person.age == 26


def test_player_c_common_name_unresolved_falls_back_to_first_and_last() -> None:
    person = decode_block(PLAYER_C_BLOCK)
    assert person is not None
    assert person.common_name is None
    assert person.name == "Sam Sample"


def test_player_d_uses_last_name_only_and_has_no_full_name() -> None:
    person = decode_block(PLAYER_D_BLOCK)
    assert person is not None
    assert person.name == "Sample"
    assert person.full_name is None


def test_birth_year_after_clock_year_is_rejected() -> None:
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(60, 2032),
        nation_id=44,
        personality=DEFAULT_PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    assert decode_block(block) is None


def test_nonzero_byte_in_the_required_zero_range_is_rejected() -> None:
    mutable = bytearray(PLAYER_A_BLOCK)
    birth_local_offset = 152  # PLAYER_A_BLOCK has no legal name, so L == 0.
    mutable[birth_local_offset + 16] = 5
    assert decode_block(bytes(mutable)) is None


def test_personality_byte_out_of_range_is_rejected() -> None:
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=(0, 12, 9, 20, 18, 7, 11, 3),
        trait_bits=0,
        relations=(),
    )
    assert decode_block(block) is None


def test_stray_in_range_run_before_the_block_is_skipped() -> None:
    decoy_clutter = bytes([5] * 8) + bytes(112)
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=DEFAULT_PERSONALITY,
        trait_bits=0,
        relations=(),
        clutter=decoy_clutter,
    )
    person = decode_block(block)
    assert person is not None
    assert person.nation_id == 44


def test_relation_list_overrun_raises_corrupt_save_error() -> None:
    prefix = game_db_prefix()
    game_db = prefix + PLAYER_A_BLOCK
    decoder = build_decoder(game_db)
    with pytest.raises(CorruptSaveError) as error_info:
        decoder.decode(game_db, len(prefix), len(game_db) - 1)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message


def test_non_ascii_legal_name_round_trips() -> None:
    block = person_block_bytes(
        first_name_id=0xFFFFFFFF,
        surname_id=0xFFFFFFFF,
        common_name_id=0xFFFFFFFF,
        legal_name="Łukasz Exämple",
        birth=packed_date(60, 2004),
        nation_id=1,
        personality=DEFAULT_PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    person = decode_block(block)
    assert person is not None
    assert person.legal_name == "Łukasz Exämple"


def test_personality_pattern_finds_overlapping_starts_a_consuming_pattern_would_miss() -> None:
    layout = registered_person_layout()
    overlapping_pattern = _personality_pattern(layout)
    lowest, highest = layout.personality_range
    consuming_pattern = re.compile(
        b"[" + bytes((lowest,)) + b"-" + bytes((highest,)) + b"]{" + b"8}"
    )
    # A run of 11 in-range bytes: a consuming (non-overlapping) pattern only ever reports the
    # leftmost 8-byte window, so it never reaches start position 3, the "true" candidate here.
    buffer = bytes([5] * 11)
    overlapping_starts = [match.start() for match in overlapping_pattern.finditer(buffer)]
    consuming_starts = [match.start() for match in consuming_pattern.finditer(buffer)]
    assert overlapping_starts == [0, 1, 2, 3]
    assert consuming_starts == [0]
    assert 3 in overlapping_starts
    assert 3 not in consuming_starts


def test_unreadable_clock_raises_reader_check_error_from_players(tmp_path) -> None:
    sections = [
        SectionFrame("game_info", game_info_body(game_day_of_year=60, game_year=1800))
        if section.name == "game_info"
        else section
        for section in default_sections()
    ]
    path = build_container_fragment(sections).write(tmp_path / FILE_NAME)
    with fmsave.open(path) as career_save:
        with pytest.raises(ReaderCheckError) as error_info:
            career_save.players()
        assert "in-game date is unreadable" in str(error_info.value)


_FULL_PLAYER_KWARGS = {
    "pindex": 21,
    "uid": 910001,
    "current_ability": 140,
    "potential_ability": 165,
    "bucket": 120,
    "home_reputation": 8000,
    "current_reputation": 8200,
    "world_reputation": 7900,
    "team_id": 0xFFFFFFFF,
    "ratings": (1, 1, 18, 20, 15, 18, 2, 16, 3, 4, 5, 6, 7, 8, 9),
    "raw_attributes": [48] * 54,
    "transfer_value_raw": 0xFFFFFFFF,
    "join_date": packed_date(60, 2029),
    "sharpness": 7000,
    "condition": 9500,
    "height_cm": 181,
}


def test_full_player_decode_merges_person_fields_and_round_trips() -> None:
    prefix = game_db_prefix()
    payload = prefix + player_record_bytes(**_FULL_PLAYER_KWARGS, trailing=PLAYER_A_BLOCK)
    game_db = section_body(".dat", GAME_DB_SCHEMA, payload)

    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    player_records = locate_player_records(
        game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME
    )
    club_index = read_club_index(game_db, find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME)
    decoder = build_player_decoder(
        player_records.layout,
        club_index,
        name_pools,
        CLOCK,
        registered_person_layout(),
        FILE_NAME,
        game_db,
    )
    record_offset = player_records.record_offsets[0]
    record_window_end = window_end(player_records, 0, len(game_db))
    player = decoder.decode(game_db, record_offset, record_window_end)

    assert player.name == "Alex Example"
    assert player.birth_date == date(2004, 2, 29)
    assert player.age == 27
    assert player.personality is not None
    assert player.personality.pressure == 20
    assert player.trait_bits == (1 << 13) | (1 << 40)
    assert player.home_grown_club_uids == (5002,)

    copied = pickle.loads(pickle.dumps(player))
    assert copied == player
    assert type(copied) is type(player)
    deep_copied = copy.deepcopy(player)
    assert deep_copied == player
    assert type(deep_copied) is type(player)
