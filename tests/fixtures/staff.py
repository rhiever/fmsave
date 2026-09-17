"""Staff person objects for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail
tests built here. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

# One 7-byte entry of the list a staff object carries in front of its reputations.
STAFF_ENTRY_LEAD_BYTE = 0x01
STAFF_ENTRY_SEPARATOR_BYTE = 0x05
STAFF_ENTRY_BYTES = 7
# The word that follows the block of 1..100 bytes at the end of the object's fixed part.
STAFF_OBJECT_TRAILER = 0xFFFFFFFF
STAFF_PREFERENCE_COUNT = 26
STAFF_CODE_COUNT = 8
STAFF_BLOCK_40_COUNT = 26
# The one preference slot that holds a 0..100 number instead of a 1..20 one.
FREE_PREFERENCE_SLOT = 13

# Preferences for the example staff: each slot holds a distinct 1..20 value, so a reader that
# reads one slot for another has to fail, and slot 13 holds a number above 20.
CAREER_STAFF_PREFERENCES = tuple(
    75 if slot == FREE_PREFERENCE_SLOT else slot % 20 + 1 for slot in range(STAFF_PREFERENCE_COUNT)
)
# Eight codes from the set the save holds them in, in an order that repeats none of them.
CAREER_STAFF_CODES = (4, 22, 29, 28, 33, 30, 35, 3)
CAREER_STAFF_REPUTATIONS = (500, 450, 300)
CAREER_STAFF_SENTINEL = 12
CAREER_STAFF_BLOCK_40 = (50,) * STAFF_BLOCK_40_COUNT


def staff_entry_bytes(first: int, second: int) -> bytes:
    """One 7-byte entry: the lead byte, then each of the two words behind a separator byte."""
    return struct.pack(
        "<BBHBH",
        STAFF_ENTRY_LEAD_BYTE,
        STAFF_ENTRY_SEPARATOR_BYTE,
        first,
        STAFF_ENTRY_SEPARATOR_BYTE,
        second,
    )


def staff_object_bytes(
    *,
    person_id: int,
    uid: int,
    kind: int = 1,
    entries: Sequence[tuple[int, int]] = (),
    reputations: tuple[int, int, int] = CAREER_STAFF_REPUTATIONS,
    current_ability: int = 120,
    potential_ability: int = 140,
    r4: int = 16,
    codes: Sequence[int] = CAREER_STAFF_CODES,
    sentinel: int = CAREER_STAFF_SENTINEL,
    preferences: Sequence[int] = CAREER_STAFF_PREFERENCES,
    block_40: Sequence[int] = CAREER_STAFF_BLOCK_40,
    contract: bytes = b"",
    person_block: bytes = b"",
    padding_before_contract: int = 40,
    padding_after_contract: int = 24,
    trailing_bytes: int = 64,
) -> bytes:
    """One staff person object, written forward in the order the format lays it out.

    The header (the u32 person id, the uid twice, the object-kind byte, the entry count and a
    zero byte), then one `staff_entry_bytes` per entry, the three reputation words, the current
    and potential ability, the role-like byte, the eight codes, the sentinel byte, the 26
    preference slots, the block of 26 further bytes and the trailing word. Then
    `padding_before_contract` zero bytes, `contract` (a `contract_bytes` blob),
    `padding_after_contract` zero bytes, `person_block` and `trailing_bytes` zero bytes.

    The returned bytes start at the person header, so every offset a reader computes from the
    header counts from the start of the result.

    Raises:
        ValueError: A count differs from the number of values the format holds.
    """
    if len(codes) != STAFF_CODE_COUNT:
        raise ValueError(f"a staff object holds {STAFF_CODE_COUNT} codes, not {len(codes)}")
    if len(preferences) != STAFF_PREFERENCE_COUNT:
        raise ValueError(
            f"a staff object holds {STAFF_PREFERENCE_COUNT} preference slots, not "
            f"{len(preferences)}"
        )
    if len(block_40) != STAFF_BLOCK_40_COUNT:
        raise ValueError(
            f"a staff object holds {STAFF_BLOCK_40_COUNT} further bytes, not {len(block_40)}"
        )

    output = bytearray(struct.pack("<III", person_id, uid, uid))
    output.append(kind)
    output.append(len(entries))
    output.append(0)
    for first, second in entries:
        output.extend(staff_entry_bytes(first, second))
    output.extend(struct.pack("<HHH", *reputations))
    output.extend(struct.pack("<Hh", current_ability, potential_ability))
    output.append(r4)
    output.extend(bytes(codes))
    output.append(sentinel)
    output.extend(bytes(preferences))
    output.extend(bytes(block_40))
    output.extend(struct.pack("<I", STAFF_OBJECT_TRAILER))
    output.extend(bytes(padding_before_contract))
    output.extend(contract)
    output.extend(bytes(padding_after_contract))
    output.extend(person_block)
    output.extend(bytes(trailing_bytes))
    return bytes(output)
