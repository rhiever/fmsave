from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from fmsave._container import DirectoryEntry
from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._layouts.fm26_26_3_2 import INJURY_MANAGER, INJURY_TYPE_TABLE
from fmsave.readers.injuries import read_injury_types, walk_injury_manager
from tests.fixtures.container import packed_date
from tests.fixtures.injuries import (
    injury_log_row_bytes,
    injury_manager_body,
    injury_type_entries,
    injury_typed_row_bytes,
    match_file_body,
)

LOG_ROW = injury_log_row_bytes(
    date=packed_date(1, 2030), selector=11, team_id=70_001, cause=1, severity=2
)
TYPED_ROW = injury_typed_row_bytes(date=packed_date(3, 2030), selector=11, type_id=7, r11=0, r12=0)


def manager_layout():
    return replace(INJURY_MANAGER, allow_typed_rows=False, require_empty_lists=True)


def match_entry(extension: str = ".apm") -> DirectoryEntry:
    return DirectoryEntry("example_match", extension, 26, 16, 32, (0, 0))


def unexpected_match_read(_entry: DirectoryEntry) -> bytes:
    raise AssertionError("an unobserved match payload must not be read")


def test_absent_match_entries_return_explicit_empty_injury_types_without_reading_payload() -> None:
    layout = replace(INJURY_TYPE_TABLE, allow_match_entries=False)

    rows, stats = read_injury_types((), unexpected_match_read, layout)

    assert rows == ()
    assert stats.match_entries == 0
    assert stats.entries_with_magic_tried == 0
    assert stats.entries_without_magic == 0
    assert stats.table_entries == 0


@pytest.mark.parametrize("extension", [".apm", ".scm"])
def test_nonempty_match_directory_is_unsupported_before_payload_reads(extension: str) -> None:
    layout = replace(INJURY_TYPE_TABLE, allow_match_entries=False)

    with pytest.raises(UnsupportedGameError, match="injury.type"):
        read_injury_types((match_entry(extension),), unexpected_match_read, layout)


def test_default_injury_type_layout_still_decodes_nonempty_fictional_match_table() -> None:
    payload = match_file_body(
        [injury_type_entries(((7, "Example Knock", 0, 8), (9, "Example Strain", 1, 10)))]
    )

    rows, stats = read_injury_types((match_entry(),), lambda _entry: payload, INJURY_TYPE_TABLE)

    assert [(row.id, row.name) for row in rows] == [(7, "Example Knock"), (9, "Example Strain")]
    assert stats.match_entries == stats.entries_with_magic_tried == 1
    assert stats.table_entries == 2


def test_observed_log_only_section_must_be_consumed_exactly() -> None:
    section = injury_manager_body(
        window_a=(), window_b=(), typed=(), log=(LOG_ROW,), lists=((), (), ())
    )

    walk = walk_injury_manager(section, manager_layout(), "example.fm")

    assert walk.log_rows == 1
    assert walk.typed_rows == 0
    assert walk.list_entries == (0, 0, 0)


def test_unobserved_nonempty_typed_array_is_unsupported() -> None:
    section = injury_manager_body(
        window_a=(), window_b=(), typed=(TYPED_ROW,), log=(LOG_ROW,), lists=((), (), ())
    )

    with pytest.raises(UnsupportedGameError, match="typed"):
        walk_injury_manager(section, manager_layout(), "example.fm")


@pytest.mark.parametrize("nonempty_list", [0, 1, 2])
def test_unobserved_nonempty_injury_lists_are_unsupported(nonempty_list: int) -> None:
    lists = (
        (11,) if nonempty_list == 0 else (),
        (12,) if nonempty_list == 1 else (),
        ((13, 1),) if nonempty_list == 2 else (),
    )
    section = injury_manager_body(window_a=(), window_b=(), typed=(), log=(LOG_ROW,), lists=lists)

    with pytest.raises(UnsupportedGameError, match="list"):
        walk_injury_manager(section, manager_layout(), "example.fm")


@pytest.mark.parametrize("damage", ["oversized_count", "truncated_tail", "trailing_byte"])
def test_zero_typed_shape_does_not_turn_damaged_section_into_empty_history(damage: str) -> None:
    section = injury_manager_body(
        window_a=(),
        window_b=(),
        typed=(),
        log=(LOG_ROW,),
        lists=((), (), ()),
        log_count=5000 if damage == "oversized_count" else None,
        trailing_bytes=b"\x00" if damage == "trailing_byte" else b"",
    )
    if damage == "truncated_tail":
        section = section[:-1]

    with pytest.raises(ReaderCheckError):
        walk_injury_manager(section, manager_layout(), "example.fm")


def test_default_layout_preserves_nonempty_typed_rows_and_auxiliary_lists() -> None:
    section = injury_manager_body(
        window_a=(),
        window_b=(),
        typed=(TYPED_ROW,),
        log=(LOG_ROW,),
        lists=((11,), (12,), ((13, 1),)),
    )

    walk = walk_injury_manager(section, INJURY_MANAGER, "example.fm")

    assert walk.log_rows == walk.typed_rows == 1
    assert walk.list_entries == (1, 1, 1)


@pytest.mark.parametrize("count_offset", [20, 43])
def test_corrupt_typed_or_list_counts_keep_bounds_errors_before_unsupported_guards(
    count_offset: int,
) -> None:
    section = bytearray(
        injury_manager_body(window_a=(), window_b=(), typed=(), log=(LOG_ROW,), lists=((), (), ()))
    )
    # Header12, then four counted arrays; the sole15-byte log precedes the first list.
    struct.pack_into("<I", section, count_offset, 5000)

    with pytest.raises(ReaderCheckError):
        walk_injury_manager(bytes(section), manager_layout(), "example.fm")
