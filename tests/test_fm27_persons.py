from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from fmsave._errors import CorruptSaveError
from fmsave._layouts import FALLBACK_BUILD, PersonBlockLayout, find_layout
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.names import locate_name_pools
from fmsave.readers.persons import PersonBlockDecoder, build_person_block_decoder
from tests.fixtures.container import packed_date
from tests.fixtures.game_db import (
    person_block_birth_offset,
    person_block_bytes,
    relation_entry_bytes,
)
from tests.test_persons import (
    DEFAULT_PERSONALITY,
    FILE_NAME,
    game_db_prefix,
    registered_name_pool_layout,
)


def shifted_block(*, legal_name: str | None = None, relations: bool = True) -> bytes:
    block = person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=legal_name,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=DEFAULT_PERSONALITY,
        trait_bits=1 << 27,
        relations=(relation_entry_bytes(12, 8, 9, 100),) if relations else (),
    )
    inserted_at = person_block_birth_offset(legal_name) + 4
    return block[:inserted_at] + b"\xa5" + block[inserted_at:]


def build_shifted_decoder(
    blocks: bytes, *, require_unique_candidate: bool = True
) -> tuple[bytes, int, PersonBlockDecoder]:
    prefix = game_db_prefix()
    game_db = prefix + blocks
    pools = locate_name_pools(game_db, registered_name_pool_layout(), FILE_NAME)
    clubs = read_club_index(game_db, find_club_layouts(4000, FALLBACK_BUILD), FILE_NAME)
    layout = replace(
        find_layout(PersonBlockLayout, "game_db", 4000, FALLBACK_BUILD).layout,
        personality_offset_from_birth=22,
        date_zero_bytes_offset_from_birth=15,
        nation_id_offset_from_birth=14,
        relation_present_offset_from_birth=38,
        relation_count_offset_from_birth=39,
        relation_entries_offset_from_birth=40,
        require_unique_candidate=require_unique_candidate,
    )
    return (
        game_db,
        len(prefix),
        build_person_block_decoder(layout, pools, clubs, date(2031, 3, 1), FILE_NAME),
    )


def relation_counts(decoder: PersonBlockDecoder) -> tuple[int, int, int, int]:
    return (
        decoder.relation_entry_count,
        decoder.relation_sentinel_ok_count,
        decoder.second_nation_entry_count,
        decoder.second_nation_qualifier_ok_count,
    )


@pytest.mark.parametrize("legal_name", [None, "Alexandra Example"])
def test_shifted_single_candidate_preserves_names_dates_and_relations(
    legal_name: str | None,
) -> None:
    game_db, start, decoder = build_shifted_decoder(shifted_block(legal_name=legal_name))

    person = decoder.decode(game_db, start, len(game_db))

    assert person is not None
    assert person[:8] == (
        "Alex Example",
        "Alex",
        "Example",
        None,
        "Alex Example",
        legal_name,
        date(2004, 2, 29),
        27,
    )
    assert person[8:13] == (44, (12,), (), (), ())
    assert person[13].adaptability == 15
    assert person[13].sportsmanship == 7
    assert person[14] == 1 << 27
    assert relation_counts(decoder) == (1, 1, 1, 1)
    assert decoder.last_block_start is not None


def test_unique_decode_omits_duplicate_candidates_and_restores_previous_counts() -> None:
    block = shifted_block()
    game_db, start, decoder = build_shifted_decoder(block + block + block)
    first_end = start + len(block)
    assert decoder.decode(game_db, start, first_end) is not None
    assert relation_counts(decoder) == (1, 1, 1, 1)

    assert decoder.decode(game_db, first_end, len(game_db)) is None

    assert decoder.last_block_start is None
    assert relation_counts(decoder) == (1, 1, 1, 1)


def test_nonunique_decode_keeps_existing_first_candidate_behavior() -> None:
    game_db, start, decoder = build_shifted_decoder(
        shifted_block() + shifted_block(legal_name="Other Example"),
        require_unique_candidate=False,
    )

    person = decoder.decode(game_db, start, len(game_db))

    assert person is not None
    assert person[5] is None
    assert relation_counts(decoder) == (1, 1, 1, 1)


def test_unique_decode_ignores_invalid_second_personality_candidate() -> None:
    valid = shifted_block()
    invalid = bytearray(valid)
    birth = person_block_birth_offset(None)
    invalid[birth + 17] = 5
    game_db, start, decoder = build_shifted_decoder(valid + bytes(invalid))

    person = decoder.decode(game_db, start, len(game_db))

    assert person is not None
    assert person[0] == "Alex Example"
    assert relation_counts(decoder) == (1, 1, 1, 1)


def test_unique_decode_raises_for_truncated_second_candidate_without_retaining_counts() -> None:
    block = shifted_block()
    game_db, start, decoder = build_shifted_decoder(block + block + block[:-1])
    first_end = start + len(block)
    assert decoder.decode(game_db, start, first_end) is not None

    with pytest.raises(CorruptSaveError, match="relation list"):
        decoder.decode(game_db, first_end, len(game_db))

    assert decoder.last_block_start is None
    assert relation_counts(decoder) == (1, 1, 1, 1)


def test_unique_decode_without_candidates_returns_no_person_or_counts() -> None:
    game_db, start, decoder = build_shifted_decoder(b"\xff" * 200)

    assert decoder.decode(game_db, start, len(game_db)) is None
    assert decoder.last_block_start is None
    assert relation_counts(decoder) == (0, 0, 0, 0)
