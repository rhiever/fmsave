"""Byte builders for the `tactics_man` section: team blocks, tactics and set-piece routines.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All ids, labels and names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import section_body

TACTICS_SCHEMA = 26
BLOCK_MARKER = b"\x09\x03"
SELECTION_END_MARKER = b"\x42\x00"
TAKER_MARKER = b"\x08\x05\x02"
ORDER_MARKER = b"\x08"
LIST_ITEM_LEAD = b"\x02"
SELECTION_SLOT_COUNT = 26
NO_SELECTOR = 0xFFFFFFFF
NO_TACTICS_VALUE = 0xFFFFFFFF
HAS_TACTICS_VALUE = 0
USER_SIGNATURE = bytes.fromhex("2242001a03000102")
PRESET_SIGNATURE = bytes.fromhex("2242001a03000101")
SLOT_TAG = bytes.fromhex("420002")
SLOT_CONSTANT = bytes.fromhex("ff000101")
UNIT_LEAD = bytes.fromhex("010202")
UNIT_SEPARATOR = b"\xff"
UNIT_BYTES = 24
ROUTINE_TERMINATOR = bytes.fromhex("014c4c554e")
ROUTINE_COUNT = 20
ROUTINE_FILLER = b"\x44" * 24
SET_PIECE_AREA_MARKER = bytes.fromhex("03001a")
SET_PIECE_AREA_FLAGS = bytes.fromhex("01000000") * 8

_UINT8 = struct.Struct("<B")
_UINT16 = struct.Struct("<H")
_UINT32 = struct.Struct("<I")


def _length_prefixed(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return _UINT32.pack(len(encoded)) + encoded


def selector_list_bytes(selectors: Sequence[int]) -> bytes:
    """A selector list: a u32 count, then the lead byte and a u32 for each selector."""
    payload = bytearray(_UINT32.pack(len(selectors)))
    for selector in selectors:
        payload.extend(LIST_ITEM_LEAD)
        payload.extend(_UINT32.pack(selector))
    return bytes(payload)


def selection_part_bytes(
    *,
    team_id: int,
    label: str,
    slots: Sequence[int],
    list_a: Sequence[int],
    list_b: Sequence[int],
    single: int,
    taker_lists: Sequence[Sequence[int]] = ((),) * 10,
    order_lists: Sequence[Sequence[int]] = ((),) * 8,
    tactics_value: int,
    tactic_count: int,
) -> bytes:
    """One team block's selection part, up to and including the tactic count.

    `slots` is padded to 26 entries with the missing-selector word. `tactics_value` is the
    word the save writes in front of the count, and `tactic_count` is how many tactic records
    the block claims.
    """
    if len(slots) > SELECTION_SLOT_COUNT:
        raise ValueError(f"a block holds {SELECTION_SLOT_COUNT} selection slots, not {len(slots)}")
    payload = bytearray(_UINT32.pack(team_id))
    payload.extend(BLOCK_MARKER)
    payload.extend(_length_prefixed(label))
    padded_slots = list(slots) + [NO_SELECTOR] * (SELECTION_SLOT_COUNT - len(slots))
    for selector in padded_slots:
        payload.extend(_UINT32.pack(selector))
    payload.extend(SELECTION_END_MARKER)
    payload.extend(selector_list_bytes(list_a))
    payload.extend(selector_list_bytes(list_b))
    payload.extend(LIST_ITEM_LEAD)
    payload.extend(_UINT32.pack(single))
    payload.extend(TAKER_MARKER)
    for taker_list in taker_lists:
        payload.extend(selector_list_bytes(taker_list))
    payload.extend(ORDER_MARKER)
    for order_list in order_lists:
        payload.extend(selector_list_bytes(order_list))
    payload.append(0)
    payload.extend(_UINT32.pack(tactics_value))
    payload.extend(_UINT16.pack(tactic_count))
    return bytes(payload)


def setting_unit_bytes(*, head_byte: int, first_bits: int, second_bits: int) -> bytes:
    """One 24-byte setting unit: the lead, a head byte, two bit fields and their separator."""
    unit = bytearray(UNIT_LEAD)
    unit.extend(_UINT8.pack(head_byte))
    unit.extend(first_bits.to_bytes(7, "little"))
    unit.extend(UNIT_SEPARATOR)
    unit.extend(second_bits.to_bytes(12, "little"))
    if len(unit) != UNIT_BYTES:
        raise ValueError(f"a setting unit is {UNIT_BYTES} bytes, not {len(unit)}")
    return bytes(unit)


def slot_block_bytes(
    *,
    mask: int,
    units: Sequence[bytes],
    role_bits: int,
    trail_bits: int = 0,
    position_index: int | None = None,
    stored_unit_count: int | None = None,
) -> bytes:
    """One slot block. The per-position index byte is written only when it is given.

    `stored_unit_count` overrides the count written in front of the units, so a block can
    claim more units than it holds and break the walk that follows it.
    """
    written_count = len(units) if stored_unit_count is None else stored_unit_count
    payload = bytearray(SLOT_TAG)
    payload.extend(_UINT32.pack(mask))
    payload.extend(SLOT_CONSTANT)
    payload.extend(_UINT32.pack(written_count))
    payload.extend(role_bits.to_bytes(8, "little"))
    for unit in units:
        payload.extend(unit)
    payload.extend(_UINT32.pack(trail_bits))
    if position_index is not None:
        payload.extend(_UINT8.pack(position_index))
    return bytes(payload)


def tactic_record_bytes(
    *,
    name: str,
    team_instructions: bytes,
    style_name: str,
    style_code: bytes,
    slots: Sequence[tuple[bytes, bytes]],
    tail: bytes = b"\xee" * 16,
    preset: bool = False,
) -> bytes:
    """One tactic record: the signature, the name, the instructions, the style and the slots.

    Each entry of `slots` is the pair of slot blocks for one tactic slot, in the order the save
    writes them: the in-possession block and then the out-of-possession block, which is the one
    carrying the per-position index byte.
    """
    payload = bytearray(PRESET_SIGNATURE if preset else USER_SIGNATURE)
    payload.extend(_length_prefixed(name))
    payload.extend(bytes(12))
    payload.extend(team_instructions)
    payload.extend(_length_prefixed(style_name))
    payload.extend(style_code)
    for in_possession, out_of_possession in slots:
        payload.extend(in_possession)
        payload.extend(out_of_possession)
    payload.extend(tail)
    return bytes(payload)


def routine_bytes(name: str | None) -> bytes:
    """One set-piece routine record: filler, its length-prefixed name and its terminator."""
    payload = bytearray(ROUTINE_FILLER)
    payload.extend(_length_prefixed("" if name is None else name))
    payload.extend(ROUTINE_TERMINATOR)
    payload.append(0)
    return bytes(payload)


def set_piece_area_bytes(names: Sequence[str | None]) -> bytes:
    """The area that follows a block's tactic records: its marker, its flags, its routines."""
    payload = bytearray(SET_PIECE_AREA_MARKER)
    payload.extend(SET_PIECE_AREA_FLAGS)
    for name in names:
        payload.extend(routine_bytes(name))
    return bytes(payload)


def tactics_man_body(
    *,
    selector: int,
    blocks: Sequence[bytes],
    after_blocks: bytes = bytes(64),
    schema: int = TACTICS_SCHEMA,
    human_count: int = 1,
    header_marker: int = 0x0D,
    stored_block_count: int | None = None,
) -> bytes:
    """The whole `tactics_man` section: its header, the team blocks, then any trailing bytes.

    `stored_block_count` overrides the count written in the header, so a body can claim more
    or fewer blocks than it holds.
    """
    written_count = len(blocks) if stored_block_count is None else stored_block_count
    payload = bytearray(_UINT16.pack(human_count))
    payload.extend(_UINT8.pack(header_marker))
    payload.extend(_UINT32.pack(selector))
    payload.extend(_UINT32.pack(written_count))
    for block in blocks:
        payload.extend(block)
    payload.extend(after_blocks)
    return section_body(".dat", schema, bytes(payload))
