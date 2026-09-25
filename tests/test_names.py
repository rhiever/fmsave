from __future__ import annotations

from pathlib import Path

import pytest

import fmsave
from fmsave._errors import CorruptSaveError, ReaderCheckError
from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, NamePoolLayout, find_layout
from fmsave.readers.names import NamePools, locate_name_pools
from tests.fixtures.container import SectionFrame, build_container_fragment, default_sections
from tests.fixtures.container import section_body as container_section_body
from tests.fixtures.game_db import NAME_POOL_SIGNATURE, name_pools_bytes

FILE_NAME = "career example.fm"
LEADING_BYTES = b"\x00" * 40
TRAILING_BYTES = b"\xff" * 16
TEST_LAYOUT = NamePoolLayout(
    signature=NAME_POOL_SIGNATURE,
    max_name_bytes=64,
)


def example_pools(id_override: dict[tuple[int, int], int] | None = None) -> bytes:
    return name_pools_bytes(
        ["Alex", "Sam", ""], ["Example", "Sample"], ["Exo", "Pim"], id_override=id_override
    )


def wrapped(pools: bytes) -> bytes:
    return LEADING_BYTES + pools + TRAILING_BYTES


def locate(game_db: bytes, layout: NamePoolLayout = TEST_LAYOUT) -> NamePools:
    return locate_name_pools(game_db, layout, FILE_NAME)


def test_locate_finds_entry_counts_and_end_offset() -> None:
    pools = example_pools()
    name_pools = locate(wrapped(pools))
    assert name_pools.first_names.entry_count == 3
    assert name_pools.surnames.entry_count == 2
    assert name_pools.common_names.entry_count == 2
    assert name_pools.end_offset == len(LEADING_BYTES) + len(pools)


def test_entry_offsets_point_at_length_words() -> None:
    game_db = wrapped(example_pools())
    name_pools = locate(game_db)
    first_entry_length_at = len(LEADING_BYTES) + len(NAME_POOL_SIGNATURE) + 4 + 4
    assert name_pools.first_names.entry_offsets.typecode == "Q"
    assert name_pools.first_names.entry_offsets[0] == first_entry_length_at
    assert len(name_pools.surnames.entry_offsets) == 2


def test_name_at_reads_names_by_index() -> None:
    game_db = wrapped(example_pools())
    name_pools = locate(game_db)
    assert name_pools.first_names.name_at(game_db, 0) == "Alex"
    assert name_pools.first_names.name_at(game_db, 1) == "Sam"
    assert name_pools.first_names.name_at(game_db, 2) is None
    assert name_pools.surnames.name_at(game_db, 0) == "Example"
    assert name_pools.surnames.name_at(game_db, 1) == "Sample"
    assert name_pools.common_names.name_at(game_db, 1) == "Pim"


@pytest.mark.parametrize("missing_index", [0xFFFFFFFF, 9, 2, -1])
def test_name_at_returns_none_outside_the_pool(missing_index: int) -> None:
    game_db = wrapped(example_pools())
    assert locate(game_db).common_names.name_at(game_db, missing_index) is None


def test_non_ascii_names_round_trip() -> None:
    game_db = wrapped(name_pools_bytes(["Łukasz", "Alex"], ["東京", "Sample"], ["Exo", "Pim"]))
    name_pools = locate(game_db)
    assert name_pools.first_names.name_at(game_db, 0) == "Łukasz"
    assert name_pools.surnames.name_at(game_db, 0) == "東京"


def test_missing_signature_raises_reader_check() -> None:
    other_signature = b"\x01" * len(NAME_POOL_SIGNATURE)
    game_db = wrapped(
        name_pools_bytes(
            ["Alex", "Sam"], ["Example", "Sample"], ["Exo", "Pim"], signature=other_signature
        )
    )
    with pytest.raises(ReaderCheckError, match="name pools not found"):
        locate(game_db)


def test_signature_twice_raises_reader_check() -> None:
    pools = example_pools()
    with pytest.raises(ReaderCheckError, match="name pools not found"):
        locate(wrapped(pools + pools))


def test_id_that_differs_from_its_index_raises_reader_check() -> None:
    game_db = wrapped(example_pools(id_override={(1, 1): 5}))
    with pytest.raises(ReaderCheckError):
        locate(game_db)


def test_name_longer_than_the_cap_raises_reader_check() -> None:
    long_name = "Example" * 10
    game_db = wrapped(name_pools_bytes(["Alex", long_name], ["Example", "Sample"], ["Exo", "Pim"]))
    with pytest.raises(ReaderCheckError):
        locate(game_db)


def test_name_at_the_cap_is_accepted() -> None:
    name_at_cap = "x" * 64
    game_db = wrapped(
        name_pools_bytes(["Alex", name_at_cap], ["Example", "Sample"], ["Exo", "Pim"])
    )
    assert locate(game_db).first_names.name_at(game_db, 1) == name_at_cap


def test_small_pools_in_a_full_size_game_db_are_read() -> None:
    registered_layout = find_layout(NamePoolLayout, "game_db", 4000, "").layout
    game_db = wrapped(example_pools()) + bytes(FULL_SAVE_MINIMUM_GAME_DB_BYTES)
    assert locate(game_db, registered_layout).common_names.entry_count == 2


def test_truncated_last_entry_raises_corrupt() -> None:
    pools = example_pools()
    with pytest.raises(CorruptSaveError):
        locate(LEADING_BYTES + pools[:-2])


@pytest.mark.parametrize("bytes_removed", [3, 5, 9, 12])
def test_walk_past_the_buffer_end_raises_corrupt(bytes_removed: int) -> None:
    pools = example_pools()
    with pytest.raises(CorruptSaveError):
        locate(LEADING_BYTES + pools[:-bytes_removed])


def test_implausible_entry_count_raises_corrupt() -> None:
    signature_and_count = NAME_POOL_SIGNATURE + (0xFFFFFFF0).to_bytes(4, "little")
    with pytest.raises(CorruptSaveError):
        locate(LEADING_BYTES + signature_and_count + bytes(64))


def test_invalid_utf8_makes_name_at_raise_corrupt() -> None:
    game_db = bytearray(wrapped(example_pools()))
    name_at = game_db.index(b"Sample")
    game_db[name_at + 1] = 0xFF
    patched_game_db = bytes(game_db)
    name_pools = locate(patched_game_db)
    assert name_pools.surnames.name_at(patched_game_db, 0) == "Example"
    with pytest.raises(CorruptSaveError) as error_info:
        name_pools.surnames.name_at(patched_game_db, 1)
    assert FILE_NAME in str(error_info.value)
    assert "game_db" in str(error_info.value)
    assert "Sample" not in str(error_info.value)


def test_name_at_on_a_shorter_buffer_raises_corrupt() -> None:
    game_db = wrapped(example_pools())
    name_pools = locate(game_db)
    with pytest.raises(CorruptSaveError, match="game_db"):
        name_pools.common_names.name_at(game_db[: name_pools.end_offset - 2], 1)
    with pytest.raises(CorruptSaveError, match="game_db"):
        name_pools.first_names.name_at(game_db[: len(LEADING_BYTES)], 0)


def test_buffer_ending_inside_a_pool_count_raises_corrupt() -> None:
    first_pool_bytes = 4 + (8 + len("Alex")) + (8 + len("Sam")) + 8
    count_cut_at = len(LEADING_BYTES) + len(NAME_POOL_SIGNATURE) + first_pool_bytes + 2
    with pytest.raises(CorruptSaveError, match="surnames"):
        locate(wrapped(example_pools())[:count_cut_at])


@pytest.mark.parametrize(
    "broken_game_db",
    [
        pytest.param(LEADING_BYTES, id="no signature"),
        pytest.param(wrapped(example_pools(id_override={(0, 0): 7})), id="wrong id"),
        pytest.param(LEADING_BYTES + example_pools()[:-2], id="truncated"),
    ],
)
def test_locate_errors_name_the_file_and_section(broken_game_db: bytes) -> None:
    with pytest.raises((ReaderCheckError, CorruptSaveError)) as error_info:
        locate(broken_game_db)
    assert FILE_NAME in str(error_info.value)
    assert "game_db" in str(error_info.value)


def test_reprs_hide_names_and_file_name() -> None:
    game_db = wrapped(example_pools())
    name_pools = locate(game_db)
    description = repr(name_pools)
    assert FILE_NAME not in description
    for fictional_name in ("Alex", "Sam", "Example", "Sample", "Exo", "Pim"):
        assert fictional_name not in description


def test_registered_layout_reads_a_small_fragment(tmp_path: Path) -> None:
    pools = example_pools()
    game_db_body = container_section_body(".dat", 4000, bytes(24) + pools + bytes(8))
    sections = [
        SectionFrame("game_db", game_db_body) if section.name == "game_db" else section
        for section in default_sections()
    ]
    fragment_path = build_container_fragment(sections).write(tmp_path / "fragment.bin")
    with fmsave.open(fragment_path) as career_save:
        registered_layout = find_layout(
            NamePoolLayout, "game_db", career_save.info.section_schemas["game_db"], ""
        ).layout
        with career_save._context.section("game_db") as game_db:
            name_pools = locate_name_pools(game_db, registered_layout, career_save.info.file_name)
            assert name_pools.surnames.name_at(game_db, 1) == "Sample"
    assert registered_layout.signature == NAME_POOL_SIGNATURE
    assert registered_layout.max_name_bytes == 64
