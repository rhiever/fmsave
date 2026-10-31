"""Fictional FM27 tactic blocks: records the registered layout reads, and fail-closed probes."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._layouts import TacticsLayout, find_layout
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


# The registered FM27 layout, read against bytes spelled out here rather than copied from it.
FM27_BUILD = "27.0.0+2486695"
FM27_LAYOUT = find_layout(TacticsLayout, "tactics_man", 26, FM27_BUILD).layout
FM27_USER_SIGNATURE = bytes.fromhex("2244001b00000000")
FM27_PRESET_SIGNATURE = bytes.fromhex("2244001b00000001")
FM27_FIRST_TACTIC = "Example Shape"
FM27_STYLE = "Example Style"
FM27_INSTRUCTIONS = bytes([4, 21, 6, 6, 2, 3, 30, 48, 40, 41, 42, 84, 43, 44, 45, 46, 47, 0, 255])
# Position bits per slot: a goalkeeper, the back four, two wide midfielders, two defensive
# midfielders, a wide attacker who drops to the wide midfield out of possession, and two
# strikers. The column flags tell each pair apart.
FM27_SLOT_BITS = (
    (0, 0),
    (2, 2),
    (4, 4),
    (4, 4),
    (3, 3),
    (8, 8),
    (7, 7),
    (7, 7),
    (12, 9),
    (14, 14),
    (14, 14),
)
FM27_COLUMN_FLAGS = {2: 1 << 21, 3: 1 << 20, 6: 1 << 21, 7: 1 << 20, 9: 1 << 21, 10: 1 << 20}


def fm27_slot_block(mask: int, units: int, role_bit: int, index: int | None = None) -> bytes:
    unit = bytes.fromhex("020202") + b"\x00" + bytes(7) + b"\xff" + (1 << 85).to_bytes(12, "little")
    block = bytearray(bytes.fromhex("440002"))
    block += struct.pack("<I", mask) + bytes.fromhex("000101") + struct.pack("<I", units)
    block += (1 << role_bit).to_bytes(8, "little") + unit * units + struct.pack("<I", 0)
    if index is not None:
        block.append(index)
    return bytes(block)


def fm27_record(name: str, *, preset: bool = False) -> bytes:
    record = bytearray(FM27_PRESET_SIGNATURE if preset else FM27_USER_SIGNATURE)
    record += struct.pack("<I", len(name)) + name.encode() + bytes(12) + FM27_INSTRUCTIONS
    record += struct.pack("<I", len(FM27_STYLE)) + FM27_STYLE.encode() + b"EXMP"
    for number, (in_bit, out_bit) in enumerate(FM27_SLOT_BITS):
        flag = FM27_COLUMN_FLAGS.get(number, 0)
        record += fm27_slot_block((1 << in_bit) | flag, 2, 1)
        record += fm27_slot_block((1 << out_bit) | flag, 1, 3, number)
    return bytes(record)


def fm27_section(records: tuple[bytes, ...], after_blocks: bytes = b"") -> bytes:
    block = selection(TEAMS[0], tactic_count=len(records), tactics_value=0)
    return tactics_man_body(
        selector=9901,
        blocks=(block + b"".join(records) + set_piece_area_bytes((None,) * 20),),
        after_blocks=after_blocks,
    )


def test_fm27_user_record_decodes_its_name_mentality_and_eleven_slot_pairs() -> None:
    rows, counts = walk_tactic_blocks(
        fm27_section((fm27_record(FM27_FIRST_TACTIC),)), TEAMS[:1], FM27_LAYOUT, "fictional.bin"
    )

    (tactic,) = rows[0].tactics
    assert tactic.name == FM27_FIRST_TACTIC
    assert tactic.style_name == FM27_STYLE
    assert tactic.mentality_raw == 6
    assert tactic.walk_complete and tactic.oop_index_permutation
    assert [slot.in_possession_mask & 0xFFFF for slot in tactic.slots] == [
        1 << in_bit for in_bit, _out_bit in FM27_SLOT_BITS
    ]
    assert [slot.out_of_possession_mask & 0xFFFF for slot in tactic.slots] == [
        1 << out_bit for _in_bit, out_bit in FM27_SLOT_BITS
    ]
    assert rows[0].routine_names == (None,) * 20
    assert counts.tactic_blocks == counts.tactic_blocks_count_matching == 1
    assert counts.preset_tactics == 0
    assert counts.routine_blocks_complete == 1


def test_fm27_preset_library_after_the_routines_is_not_a_team_tactic() -> None:
    section = fm27_section(
        (fm27_record(FM27_FIRST_TACTIC),), after_blocks=fm27_record("4-4-2", preset=True)
    )
    rows, counts = walk_tactic_blocks(section, TEAMS[:1], FM27_LAYOUT, "fictional.bin")

    assert [tactic.name for tactic in rows[0].tactics] == [FM27_FIRST_TACTIC]
    assert counts.preset_tactics == 0
    assert counts.tactic_blocks_count_matching == 1


def test_fm27_claimed_record_with_an_fm26_signature_is_not_found() -> None:
    fm26_shaped = bytes.fromhex("2242001a03000102") + fm27_record(FM27_FIRST_TACTIC)[8:]
    rows, counts = walk_tactic_blocks(
        fm27_section((fm26_shaped,)), TEAMS[:1], FM27_LAYOUT, "fictional.bin"
    )

    assert rows[0].tactics == ()
    assert counts.tactic_blocks == 1
    assert counts.tactic_blocks_count_matching == 0


def test_fm27_slot_block_in_the_fm26_shape_ends_the_slot_walk() -> None:
    record = fm27_record(FM27_FIRST_TACTIC).replace(
        bytes.fromhex("000101"), bytes.fromhex("ff000101"), 1
    )
    rows, _counts = walk_tactic_blocks(
        fm27_section((record,)), TEAMS[:1], FM27_LAYOUT, "fictional.bin"
    )

    (tactic,) = rows[0].tactics
    assert not tactic.walk_complete
