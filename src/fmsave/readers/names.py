"""The three name pools in `game_db`: first names, surnames and common names.

A stored name id is an index into one pool. Locating the pools walks every entry once
and records where each one sits, without decoding any text; `PoolIndex.name_at` decodes
a single name when a reader asks for it.
"""

from __future__ import annotations

import struct
from array import array
from dataclasses import dataclass, field

from fmsave._errors import ISSUES_URL, CorruptSaveError, ReaderCheckError
from fmsave._layouts import NamePoolLayout

GAME_DB_SECTION = "game_db"
MISSING_NAME_INDEX = 0xFFFFFFFF
POOL_NAMES = ("first names", "surnames", "common names")
OFFSET_TYPECODE = "Q"

_COUNT_WORD = struct.Struct("<I")
_ENTRY_HEADER = struct.Struct("<II")
_LENGTH_WORD_AFTER_ENTRY_START = 4


def _section_label(file_name: str) -> str:
    return f"{file_name}: section {GAME_DB_SECTION!r}"


def _layout_mismatch(file_name: str, detail: str) -> ReaderCheckError:
    return ReaderCheckError(
        f"{_section_label(file_name)}: {detail}, so the save layout differs from what fmsave "
        f"expects. Please report it at {ISSUES_URL}"
    )


def _pool_overrun(file_name: str, pool_name: str) -> CorruptSaveError:
    return CorruptSaveError(
        f"{_section_label(file_name)}: the {pool_name} pool runs past the end of the section"
    )


@dataclass(frozen=True, slots=True)
class PoolIndex:
    """Where each entry of one name pool sits in `game_db`.

    `entry_offsets[i]` is the offset of entry i's byte length word; its UTF-8 text follows.
    """

    entry_offsets: array[int] = field(repr=False)
    entry_count: int
    file_name: str = field(repr=False)
    pool_name: str

    def name_at(self, buffer: bytes, index: int) -> str | None:
        """The name stored at `index`, or None for the missing id, an out-of-range index or a blank.

        Raises:
            CorruptSaveError: The name is not valid UTF-8 or lies outside `buffer`.
        """
        if index == MISSING_NAME_INDEX or not 0 <= index < self.entry_count:
            return None
        length_word_at = self.entry_offsets[index]
        text_start = length_word_at + _COUNT_WORD.size
        if text_start > len(buffer):
            raise self._name_error(index, "lies outside the section")
        name_length: int = _COUNT_WORD.unpack_from(buffer, length_word_at)[0]
        if name_length == 0:
            return None
        text_end = text_start + name_length
        if text_end > len(buffer):
            raise self._name_error(index, "lies outside the section")
        try:
            return buffer[text_start:text_end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise self._name_error(index, "is not valid UTF-8") from error

    def _name_error(self, index: int, problem: str) -> CorruptSaveError:
        return CorruptSaveError(
            f"{_section_label(self.file_name)}: name {index} of the {self.pool_name} pool {problem}"
        )


@dataclass(frozen=True, slots=True)
class NamePools:
    """The three pools in their stored order, and the first byte after the last one."""

    first_names: PoolIndex
    surnames: PoolIndex
    common_names: PoolIndex
    end_offset: int


def locate_name_pools(game_db: bytes, layout: NamePoolLayout, file_name: str) -> NamePools:
    """Find the pools after their signature and index every entry, decoding no text.

    Raises:
        ReaderCheckError: The signature is missing or appears more than once, an entry id
            differs from its index, a name is longer than the layout allows, or (on a
            full-size `game_db`) a pool has fewer entries than the layout requires.
        CorruptSaveError: A pool runs past the end of `game_db`.
    """
    signature_at = game_db.find(layout.signature)
    if signature_at < 0 or game_db.find(layout.signature, signature_at + 1) >= 0:
        raise _layout_mismatch(
            file_name, "name pools not found (their signature is missing or not unique)"
        )
    enforce_minimum = len(game_db) >= layout.minimum_applies_from_bytes
    cursor = signature_at + len(layout.signature)
    pool_indexes: list[PoolIndex] = []
    for pool_name in POOL_NAMES:
        pool_index, cursor = _index_pool(
            game_db, cursor, layout, file_name, pool_name, enforce_minimum=enforce_minimum
        )
        pool_indexes.append(pool_index)
    first_names, surnames, common_names = pool_indexes
    return NamePools(
        first_names=first_names, surnames=surnames, common_names=common_names, end_offset=cursor
    )


def _index_pool(
    game_db: bytes,
    count_word_at: int,
    layout: NamePoolLayout,
    file_name: str,
    pool_name: str,
    *,
    enforce_minimum: bool,
) -> tuple[PoolIndex, int]:
    """Walk one pool starting at its entry count; return its index and the offset after it."""
    buffer_length = len(game_db)
    position = count_word_at + _COUNT_WORD.size
    if position > buffer_length:
        raise _pool_overrun(file_name, pool_name)
    entry_count: int = _COUNT_WORD.unpack_from(game_db, count_word_at)[0]
    if entry_count * _ENTRY_HEADER.size > buffer_length - position:
        raise CorruptSaveError(
            f"{_section_label(file_name)}: the {pool_name} pool claims {entry_count} entries, "
            "more than the rest of the section can hold"
        )
    if enforce_minimum and entry_count < layout.minimum_entries_per_pool:
        raise _layout_mismatch(
            file_name,
            f"the {pool_name} pool has {entry_count} entries, fewer than the "
            f"{layout.minimum_entries_per_pool} a full save holds",
        )
    entry_offsets = array(OFFSET_TYPECODE)
    record_offset = entry_offsets.append
    read_entry_header = _ENTRY_HEADER.unpack_from
    max_name_bytes = layout.max_name_bytes
    header_size = _ENTRY_HEADER.size
    last_header_start = buffer_length - header_size
    for entry_index in range(entry_count):
        if position > last_header_start:
            raise _pool_overrun(file_name, pool_name)
        entry_id, name_length = read_entry_header(game_db, position)
        if entry_id != entry_index or name_length > max_name_bytes:
            raise _entry_mismatch(file_name, pool_name, entry_index, entry_id, name_length, layout)
        record_offset(position + _LENGTH_WORD_AFTER_ENTRY_START)
        position += header_size + name_length
    if position > buffer_length:
        raise _pool_overrun(file_name, pool_name)
    pool_index = PoolIndex(
        entry_offsets=entry_offsets,
        entry_count=entry_count,
        file_name=file_name,
        pool_name=pool_name,
    )
    return pool_index, position


def _entry_mismatch(
    file_name: str,
    pool_name: str,
    entry_index: int,
    entry_id: int,
    name_length: int,
    layout: NamePoolLayout,
) -> ReaderCheckError:
    if entry_id != entry_index:
        detail = f"entry {entry_index} of the {pool_name} pool has id {entry_id}"
    else:
        detail = (
            f"entry {entry_index} of the {pool_name} pool is {name_length} bytes long, more than "
            f"the {layout.max_name_bytes} allowed"
        )
    return _layout_mismatch(file_name, detail)
