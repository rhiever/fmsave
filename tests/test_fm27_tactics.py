"""Fictional zero-tactic FM27 blocks and fail-closed populated-shape probes."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._layouts.fm26_26_3_2 import TACTICS as FM26_TACTICS
from fmsave.readers.tactics import (
    _read_routine_name,  # pyright: ignore[reportPrivateUsage]
    walk_tactic_blocks,
)
from tests.fixtures.tactics import selection_part_bytes, set_piece_area_bytes, tactics_man_body

LAYOUT = replace(
    FM26_TACTICS,
    selection_end_marker=b"\x44\x00",
    tactic_records_supported=False,
    named_routines_supported=False,
)
TEAMS = (71001, 71002, 71003)


def selection(
    team_id: int,
    *,
    tactic_count: int = 0,
    tactics_value: int = 0xFFFFFFFF,
    marker: bytes = b"\x44\x00",
) -> bytes:
    # The existing byte builder imports no production code; the one changed constant is
    # supplied independently here rather than copied out of the layout under test.
    data = selection_part_bytes(
        team_id=team_id,
        label="Example selection",
        slots=(),
        list_a=(),
        list_b=(),
        single=0xFFFFFFFF,
        tactics_value=tactics_value,
        tactic_count=tactic_count,
    )
    return data.replace(b"\x42\x00", marker, 1)


def section_with(
    *,
    tactic_count: int = 0,
    tactics_value: int = 0xFFFFFFFF,
    routine_names: tuple[str | None, ...] = (None,) * 20,
) -> bytes:
    block = selection(TEAMS[0], tactic_count=tactic_count, tactics_value=tactics_value)
    return tactics_man_body(
        selector=9901, blocks=(block + set_piece_area_bytes(routine_names),), after_blocks=b""
    )


def test_fm27_three_blocks_prove_zero_records_and_sixty_empty_slots() -> None:
    blocks = tuple(selection(team) + set_piece_area_bytes((None,) * 20) for team in TEAMS)
    section = tactics_man_body(selector=9901, blocks=blocks, after_blocks=b"")
    rows, counts = walk_tactic_blocks(section, TEAMS, LAYOUT, "fictional.bin")

    assert [row.team_id for row in rows] == list(TEAMS)
    assert all(row.tactics == () for row in rows)
    assert all(row.routine_names == (None,) * 20 for row in rows)
    assert counts.header_blocks == counts.stored_blocks == counts.stored_club_blocks == 3
    assert counts.blocks_found == counts.routine_blocks_complete == 3
    assert counts.tactic_blocks == counts.preset_tactics == 0


@pytest.mark.parametrize("tactic_count", (1, 65535))
@pytest.mark.parametrize("tactics_value", (0, 0xFFFFFFFF))
def test_fm27_nonzero_raw_count_cannot_be_hidden_by_no_tactics_override(
    tactic_count: int, tactics_value: int
) -> None:
    with pytest.raises(UnsupportedGameError, match="tactic"):
        walk_tactic_blocks(
            section_with(tactic_count=tactic_count, tactics_value=tactics_value),
            TEAMS[:1],
            LAYOUT,
            "fictional.bin",
        )


def test_fm27_zero_count_requires_explicit_consistent_no_tactics_flag() -> None:
    with pytest.raises(UnsupportedGameError, match="tactic"):
        walk_tactic_blocks(section_with(tactics_value=0), TEAMS[:1], LAYOUT, "fictional.bin")


@pytest.mark.parametrize("slot", (0, 9, 19))
def test_fm27_nonempty_default_or_user_routine_name_is_unsupported(slot: int) -> None:
    names: list[str | None] = [None] * 20
    names[slot] = "Example routine"
    with pytest.raises(UnsupportedGameError, match="routine"):
        walk_tactic_blocks(
            section_with(routine_names=tuple(names)), TEAMS[:1], LAYOUT, "fictional.bin"
        )


def test_fm27_nonempty_name_is_rejected_before_unobserved_utf8_decoding() -> None:
    data = struct.pack("<I", 1) + b"\xff" + b"\x01LLUN\x00"
    with pytest.raises(UnsupportedGameError, match="routine"):
        _read_routine_name(data, 5, LAYOUT)


@pytest.mark.parametrize("missing", (1, 12, 100))
def test_fm27_truncated_counted_routines_never_pass_complete_walk(missing: int) -> None:
    rows, counts = walk_tactic_blocks(section_with()[:-missing], TEAMS[:1], LAYOUT, "fictional.bin")
    assert len(rows) == 1
    assert counts.routine_blocks_complete == 0


def test_fm27_missing_counted_slot_never_passes_complete_walk() -> None:
    rows, counts = walk_tactic_blocks(
        section_with(routine_names=(None,) * 19), TEAMS[:1], LAYOUT, "fictional.bin"
    )
    assert len(rows) == 1
    assert counts.routine_blocks_complete == 0


def test_fm27_wrong_selection_marker_is_rejected() -> None:
    body = section_with().replace(b"\x44\x00", b"\x42\x00", 1)
    with pytest.raises(ReaderCheckError):
        walk_tactic_blocks(body, TEAMS[:1], LAYOUT, "fictional.bin")


def test_fm26_default_preserves_named_routines_and_sentinel_override() -> None:
    block = selection(TEAMS[0], tactic_count=1, marker=b"\x42\x00")
    names: tuple[str | None, ...] = ("Example routine",) + (None,) * 19
    body = tactics_man_body(
        selector=9901, blocks=(block + set_piece_area_bytes(names),), after_blocks=b""
    )
    rows, counts = walk_tactic_blocks(body, TEAMS[:1], FM26_TACTICS, "fictional.bin")
    assert rows[0].tactics == ()
    assert rows[0].routine_names == names
    assert counts.routine_blocks_complete == 1
