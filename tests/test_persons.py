from __future__ import annotations

import copy
import pickle
import random
import re
from datetime import date
from typing import NamedTuple

import pytest

import fmsave
from fmsave._errors import CorruptSaveError, ReaderCheckError
from fmsave._layouts import (
    ContractLayout,
    NamePoolLayout,
    PersonBlockLayout,
    PlayerRecordLayout,
    find_layout,
)
from fmsave.models.common import CodedValue
from fmsave.models.players import Personality, Trait
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.names import locate_name_pools
from fmsave.readers.persons import (
    _CHUNK_BYTES,
    PersonTuple,
    _build_marker_needle,
    _build_marker_table,
    build_person_block_decoder,
    iter_marker_run_starts,
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
    person_block_birth_offset,
    person_block_bytes,
    player_record_bytes,
    relation_entry_bytes,
    status_record_bytes,
)

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
CLOCK = date(2031, 3, 1)


class PersonView(NamedTuple):
    """A readable view onto `PersonBlockDecoder.decode`'s plain positional return tuple,
    for tests only; production code never builds this.
    """

    name: str | None
    first_name: str | None
    last_name: str | None
    common_name: str | None
    full_name: str | None
    legal_name: str | None
    birth_date: date | None
    age: int | None
    nation_id: int
    second_nation_ids: tuple[int, ...]
    home_grown_nation_ids: tuple[int, ...]
    home_grown_club_uids: tuple[int | None, ...]
    home_grown_club_names: tuple[str | None, ...]
    personality: Personality
    trait_bits: int
    traits: tuple[CodedValue[Trait], ...]


def as_person_view(result: PersonTuple | None) -> PersonView | None:
    return None if result is None else PersonView(*result)


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

RESERVE_CLUB_UID = 5004
RESERVE_CLUB_INDEX = 3
RESERVE_CLUB = club_record_bytes(
    club_index=RESERVE_CLUB_INDEX,
    uid=RESERVE_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=81,
    name="Example Reserve",
    short_name="Reserve",
    team_ids=(70050,),
    float_anchor_only=True,
)
RESERVE_STATUS = status_record_bytes(
    ordinal=52,
    club_index=RESERVE_CLUB_INDEX,
    uid=RESERVE_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=8,
    reputation=2000,
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
        [SOUTHPORT_CLUB, RESERVE_CLUB], [SOUTHPORT_STATUS, RESERVE_STATUS], gap_bytes=2000
    )


def build_decoder(game_db: bytes, *, clock: date = CLOCK):
    name_pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    club_index = read_club_index(game_db, find_club_layouts(GAME_DB_SCHEMA, ""), FILE_NAME)
    return build_person_block_decoder(
        registered_person_layout(), name_pools, club_index, clock, FILE_NAME
    )


def decode_block(block: bytes, *, clock: date = CLOCK) -> PersonView | None:
    prefix = game_db_prefix()
    game_db = prefix + block
    decoder = build_decoder(game_db, clock=clock)
    return as_person_view(decoder.decode(game_db, len(prefix), len(game_db)))


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
    birth_local_offset = person_block_birth_offset(None)  # PLAYER_A_BLOCK has no legal name.
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


def test_relation_count_byte_overrun_raises_corrupt_save_error() -> None:
    # present (p+37) is 1 on PLAYER_A_BLOCK; truncate the window right at the count byte
    # (p+38), so the present byte itself still fits but the count byte does not.
    #
    # PLAYER_A_BLOCK's real relation entries also extend past this same truncated window, so
    # a CorruptSaveError is raised either way: from this count-byte bound, or (if that bound
    # were missing) from the unrelated entries-list bound once a bogus count is read from
    # beyond the window. Asserting the exact count-byte offset in the message, rather than
    # just "an error was raised", is what pins this specific bound: removing it changes the
    # offset the message names (to the entries list's, much larger, end offset) even though
    # a CorruptSaveError still comes out.
    prefix = game_db_prefix()
    game_db = prefix + PLAYER_A_BLOCK
    layout = registered_person_layout()
    birth_absolute = len(prefix) + person_block_birth_offset(None)
    count_absolute = birth_absolute + layout.relation_count_offset_from_birth
    count_header_end = count_absolute + 1
    decoder = build_decoder(game_db)
    with pytest.raises(CorruptSaveError) as error_info:
        decoder.decode(game_db, len(prefix), count_absolute)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "game_db" in message
    assert str(count_header_end) in message


def test_relation_present_zero_gives_empty_relations_even_with_a_nonzero_count() -> None:
    prefix = game_db_prefix()
    mutable_game_db = bytearray(prefix + PLAYER_A_BLOCK)
    layout = registered_person_layout()
    birth_absolute = len(prefix) + person_block_birth_offset(None)
    present_absolute = birth_absolute + layout.relation_present_offset_from_birth
    mutable_game_db[present_absolute] = 0
    game_db = bytes(mutable_game_db)
    decoder = build_decoder(game_db)
    person = as_person_view(decoder.decode(game_db, len(prefix), len(game_db)))
    assert person is not None
    assert person.second_nation_ids == ()
    assert person.home_grown_nation_ids == ()
    assert person.home_grown_club_uids == ()
    assert person.home_grown_club_names == ()


def test_relation_present_zero_with_an_overrunning_count_raises_no_error() -> None:
    prefix = game_db_prefix()
    mutable_game_db = bytearray(prefix + PLAYER_A_BLOCK)
    layout = registered_person_layout()
    birth_absolute = len(prefix) + person_block_birth_offset(None)
    present_absolute = birth_absolute + layout.relation_present_offset_from_birth
    mutable_game_db[present_absolute] = 0
    game_db = bytes(mutable_game_db)
    decoder = build_decoder(game_db)
    # The window ends right after the present byte: reading the count byte or any entry
    # would overrun it, but present is 0 so neither is ever read.
    truncated_window_end = present_absolute + 1
    person = as_person_view(decoder.decode(game_db, len(prefix), truncated_window_end))
    assert person is not None
    assert person.second_nation_ids == ()


def test_unresolved_home_grown_club_keeps_its_list_position() -> None:
    relations = (
        relation_entry_bytes(SOUTHPORT_CLUB_INDEX, 1, 72),
        relation_entry_bytes(99, 1, 72),
        relation_entry_bytes(RESERVE_CLUB_INDEX, 1, 72),
    )
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=DEFAULT_PERSONALITY,
        trait_bits=0,
        relations=relations,
    )
    person = decode_block(block)
    assert person is not None
    assert person.home_grown_club_uids == (5002, None, 5004)
    assert person.home_grown_club_names == ("Southport Example", None, "Example Reserve")


def test_day_366_in_a_non_leap_year_is_accepted_with_null_birth_date() -> None:
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=None,
        birth=packed_date(366, 2003),  # 2003 is not a leap year: no day 366 exists.
        nation_id=44,
        personality=DEFAULT_PERSONALITY,
        trait_bits=0,
        relations=(),
    )
    person = decode_block(block)
    assert person is not None
    assert person.birth_date is None
    assert person.age is None


def test_invalid_utf8_legal_name_raises_corrupt_save_error() -> None:
    legal_name = "AAAA"
    mutable_block = bytearray(
        person_block_bytes(
            first_name_id=0,
            surname_id=0,
            common_name_id=0xFFFFFFFF,
            legal_name=legal_name,
            birth=packed_date(60, 2004),
            nation_id=44,
            personality=DEFAULT_PERSONALITY,
            trait_bits=0,
            relations=(),
        )
    )
    birth_local_offset = person_block_birth_offset(legal_name)
    legal_name_length = len(legal_name.encode("utf-8"))
    legal_name_start_local = birth_local_offset - legal_name_length
    mutable_block[legal_name_start_local : legal_name_start_local + legal_name_length] = (
        b"\x80" * legal_name_length
    )
    prefix = game_db_prefix()
    game_db = prefix + bytes(mutable_block)
    decoder = build_decoder(game_db)
    with pytest.raises(CorruptSaveError) as error_info:
        decoder.decode(game_db, len(prefix), len(game_db))
    message = str(error_info.value)
    assert FILE_NAME in message


def test_candidate_one_byte_before_window_start_is_skipped() -> None:
    prefix = game_db_prefix()
    game_db = prefix + PLAYER_A_BLOCK
    true_birth_absolute = len(prefix) + person_block_birth_offset(None)
    decoder = build_decoder(game_db)
    window_start = true_birth_absolute + 1
    assert decoder.decode(game_db, window_start, len(game_db)) is None


def test_in_window_false_personality_run_that_fails_validation_is_skipped() -> None:
    # A first, otherwise-real block whose own required zero region is corrupted (so it fails
    # validation once entered, not merely excluded by the window-start bound), followed by a
    # second, real, valid block in the same window.
    broken_block = bytearray(PLAYER_A_BLOCK)
    broken_birth_local_offset = person_block_birth_offset(None)
    broken_block[broken_birth_local_offset + 16] = 5
    combined_block = bytes(broken_block) + PLAYER_A_BLOCK
    person = decode_block(combined_block)
    assert person is not None
    assert person.nation_id == 44


_DIFFERENTIAL_PERSONALITY_RANGE = (1, 20)
_DIFFERENTIAL_PERSONALITY_COUNT = 8
_DIFFERENTIAL_REFERENCE_PATTERN = re.compile(rb"\x00[\x01-\x14]{8}")
_DIFFERENTIAL_DECOY_BYTES = (0, 1, 5, 15, 20, 21, 33, 100, 255)


def _reference_run_starts(buffer: bytes, start: int, end: int) -> list[int]:
    return [match.start() for match in _DIFFERENTIAL_REFERENCE_PATTERN.finditer(buffer, start, end)]


def _chunked_run_starts(buffer: bytes, start: int, end: int) -> list[int]:
    marker_table = _build_marker_table(_DIFFERENTIAL_PERSONALITY_RANGE)
    marker_needle = _build_marker_needle(_DIFFERENTIAL_PERSONALITY_COUNT)
    return list(iter_marker_run_starts(buffer, start, end, marker_table, marker_needle))


def test_chunked_search_matches_regex_on_many_seeded_synthetic_windows() -> None:
    random_generator = random.Random(20260915)
    trial_count = 300
    for _trial in range(trial_count):
        length = random_generator.randint(0, 3000)
        buffer = bytes(random_generator.choice(_DIFFERENTIAL_DECOY_BYTES) for _ in range(length))
        start = random_generator.randint(0, length)
        end = random_generator.randint(start, length)
        assert _chunked_run_starts(buffer, start, end) == _reference_run_starts(buffer, start, end)


def test_chunked_search_matches_regex_for_a_match_straddling_a_chunk_boundary() -> None:
    # A chunk overlaps the next by personality_count bytes, so a chunk's "owned" zone is
    # bytes [0, _CHUNK_BYTES - personality_count) relative to its own start. Put a real
    # 9-byte run (one zero byte then 8 in-range bytes) so it starts a few bytes either side
    # of that boundary, straddling into the next chunk, with random filler everywhere else.
    random_generator = random.Random(4242)
    run = bytes([0]) + bytes([7] * _DIFFERENTIAL_PERSONALITY_COUNT)
    owned_zone_boundary = _CHUNK_BYTES - _DIFFERENTIAL_PERSONALITY_COUNT
    buffer_length = _CHUNK_BYTES + 200
    for straddle_offset in range(-3, 4):
        run_start = owned_zone_boundary + straddle_offset
        buffer = bytearray(
            random_generator.choice(_DIFFERENTIAL_DECOY_BYTES) for _ in range(buffer_length)
        )
        buffer[run_start : run_start + len(run)] = run
        frozen_buffer = bytes(buffer)
        assert _chunked_run_starts(frozen_buffer, 0, len(frozen_buffer)) == _reference_run_starts(
            frozen_buffer, 0, len(frozen_buffer)
        )


def test_chunked_search_matches_regex_on_a_window_shorter_than_one_chunk() -> None:
    random_generator = random.Random(777)
    for _trial in range(50):
        length = random_generator.randint(0, _CHUNK_BYTES // 2)
        buffer = bytes(random_generator.choice(_DIFFERENTIAL_DECOY_BYTES) for _ in range(length))
        assert _chunked_run_starts(buffer, 0, length) == _reference_run_starts(buffer, 0, length)


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
        message = str(error_info.value)
        assert message.startswith(FILE_NAME)
        assert (
            "the save's in-game date is unreadable, so person blocks and ages cannot be "
            "decoded" in message
        )


PLAYER_FULL_RELATIONS = (
    relation_entry_bytes(12, 8, 9, 100),
    relation_entry_bytes(5, 8, 70),
    relation_entry_bytes(SOUTHPORT_CLUB_INDEX, 1, 72),
    relation_entry_bytes(99, 1, 72),
)

PLAYER_FULL_BLOCK = person_block_bytes(
    first_name_id=0,
    surname_id=0,
    common_name_id=1,
    legal_name="Legal Round Trip",
    birth=packed_date(60, 2004),
    nation_id=44,
    personality=DEFAULT_PERSONALITY,
    trait_bits=(1 << 13) | (1 << 40),
    relations=PLAYER_FULL_RELATIONS,
)

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
    payload = prefix + player_record_bytes(**_FULL_PLAYER_KWARGS, trailing=PLAYER_FULL_BLOCK)
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
        find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, "").layout,
        FILE_NAME,
    )
    record_offset = player_records.record_offsets[0]
    record_window_end = window_end(player_records, 0, len(game_db))
    player, _contract = decoder.decode(
        game_db, record_offset, record_window_end, is_last_record=True
    )

    assert player.name == "Pim"
    assert player.first_name == "Alex"
    assert player.last_name == "Example"
    assert player.common_name == "Pim"
    assert player.full_name == "Alex Example"
    assert player.legal_name == "Legal Round Trip"
    assert player.birth_date == date(2004, 2, 29)
    assert player.age == 27
    assert player.nation_id == 44
    assert player.second_nation_ids == (12,)
    assert player.home_grown_nation_ids == (5,)
    assert player.home_grown_club_uids == (5002, None)
    assert player.home_grown_club_names == ("Southport Example", None)
    assert player.personality is not None
    assert player.personality.pressure == 20
    assert player.trait_bits == (1 << 13) | (1 << 40)
    assert [trait.label for trait in player.traits] == [
        Trait.LIKES_TO_TRY_TO_BEAT_OFFSIDE_TRAP,
        Trait.UNKNOWN,
    ]

    copied = pickle.loads(pickle.dumps(player))
    assert copied == player
    assert type(copied) is type(player)
    deep_copied = copy.deepcopy(player)
    assert deep_copied == player
    assert type(deep_copied) is type(player)
