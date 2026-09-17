"""Reading the injury-type name table out of one of the save's per-match files.

No section of the save holds these names: every per-match directory entry carries one copy of
the table, a few hundred bytes into its payload. The table is found structurally and never by
its text, because the names are in whatever language the save was written in: a compiled seed
pattern finds every place a record of the right shape could start, each seed is walked as
strictly as the layout allows, and the longest chain of records is the table. Only as many
entries are read as it takes to find one, so a save with hundreds of them is never read whole.
"""

from __future__ import annotations

import functools
import re
import struct
from collections.abc import Callable, Sequence

from fmsave._container import DirectoryEntry
from fmsave._frozen import FrozenMapping
from fmsave._layouts import InjuryTypeTableLayout, find_layout
from fmsave._reader_stats import InjuryTypeStats
from fmsave.models.injuries import InjuryType
from fmsave.readers._common import MATCH_FILE_REGION

# (id, name, flag, second id) of one record of the table.
type InjuryTypeRecord = tuple[int, str, int, int]

_SECOND_ID = struct.Struct("<I")
# The flag that sits between a record's text and its second id.
_FLAG_BYTES = 1


def find_injury_type_layout(build: str) -> InjuryTypeTableLayout:
    """Look up the table layout for a build. A per-match entry carries no schema number."""
    return find_layout(InjuryTypeTableLayout, MATCH_FILE_REGION, None, build).layout


@functools.lru_cache(maxsize=8)
def _seed_pattern(layout: InjuryTypeTableLayout) -> re.Pattern[bytes]:
    """Every place a record of this layout's shape could start.

    The pattern is the lead byte, any id, and a length inside the layout's range read as a u32,
    which is the most of a record that can be matched without walking it.
    """
    lowest_length, highest_length = layout.length_range
    if not 0 < lowest_length <= highest_length < 256:
        raise ValueError(
            f"the injury type length range {layout.length_range} must be inside 1 to 255"
        )
    id_bytes = layout.length_offset - layout.id_offset
    return re.compile(
        re.escape(bytes((layout.lead_byte,)))
        + b".{%d}" % id_bytes
        + b"[%s-%s]" % (re.escape(bytes((lowest_length,))), re.escape(bytes((highest_length,))))
        + b"\x00\x00\x00",
        re.DOTALL,
    )


@functools.lru_cache(maxsize=8)
def _record_head_struct(layout: InjuryTypeTableLayout) -> struct.Struct:
    """The lead byte, the id and the length, read from a record start.

    The walk reads the flag as the first byte after the text and the second id as the u32 after
    it, so a layout whose head offsets or whose trailer differ from that shape is rejected here
    rather than read from the wrong bytes.
    """
    if (layout.id_offset, layout.length_offset) != (1, 3):
        raise ValueError(
            "the injury type record head is a lead byte, a u16 id and a u32 length, so the id "
            "sits at offset 1 and the length at offset 3"
        )
    if layout.trailer_bytes != _FLAG_BYTES + _SECOND_ID.size:
        raise ValueError(
            "the injury type record trailer is a flag byte and a u32 second id, so it is "
            f"{_FLAG_BYTES + _SECOND_ID.size} bytes, not {layout.trailer_bytes}"
        )
    return struct.Struct("<BHI")


def _walk_chain(
    payload: bytes, start: int, layout: InjuryTypeTableLayout
) -> tuple[list[InjuryTypeRecord], int]:
    """Every record from `start` on, and the offset the walk stopped at.

    A record is accepted on the layout's own tests, and a chain runs only while each record's
    id is higher than the one before it, so a run of look-alike bytes ends the walk instead of
    being read as more of the table.
    """
    head_struct = _record_head_struct(layout)
    lowest_length, highest_length = layout.length_range
    lowest_text_byte, highest_text_byte = layout.text_byte_range
    records: list[InjuryTypeRecord] = []
    cursor = start
    previous_id = -1
    while cursor + layout.record_overhead_bytes <= len(payload):
        record_head: tuple[int, int, int] = head_struct.unpack_from(payload, cursor)
        lead_byte, type_id, name_length = record_head
        if lead_byte != layout.lead_byte or not lowest_length <= name_length <= highest_length:
            break
        text_end = cursor + layout.text_offset + name_length
        if text_end + layout.trailer_bytes > len(payload):
            break
        name_bytes = payload[cursor + layout.text_offset : text_end]
        if min(name_bytes) < lowest_text_byte or max(name_bytes) > highest_text_byte:
            break
        flag = payload[text_end]
        if flag not in layout.flag_values or type_id <= previous_id:
            break
        second_id: int = _SECOND_ID.unpack_from(payload, text_end + 1)[0]
        records.append((type_id, name_bytes.decode("ascii"), flag, second_id))
        previous_id = type_id
        cursor = text_end + layout.trailer_bytes
    return records, cursor


def locate_injury_type_table(
    payload: bytes, layout: InjuryTypeTableLayout
) -> tuple[InjuryTypeRecord, ...]:
    """The injury-type table inside one per-match payload, empty when it holds none.

    Every seed is walked, except seeds inside a chain already walked, and the longest chain
    wins; two chains of the same length settle on the earlier one. A chain shorter than the
    layout's minimum is no table.
    """
    seed_pattern = _seed_pattern(layout)
    longest_chain: list[InjuryTypeRecord] = []
    walked_to = 0
    search_from = 0
    while (seed := seed_pattern.search(payload, search_from)) is not None:
        seed_start = seed.start()
        search_from = seed_start + 1
        if seed_start < walked_to:
            continue
        records, chain_end = _walk_chain(payload, seed_start, layout)
        if records:
            walked_to = chain_end
        if len(records) > len(longest_chain):
            longest_chain = records
    if len(longest_chain) < layout.minimum_chain_entries:
        return ()
    return tuple(longest_chain)


def read_injury_types(
    entries: Sequence[DirectoryEntry],
    read_entry: Callable[[DirectoryEntry], bytes],
    layout: InjuryTypeTableLayout,
) -> tuple[tuple[InjuryType, ...], InjuryTypeStats]:
    """The named injury types of the first per-match entry that holds the table.

    Entries are read in directory order and only until one holds a table: at most
    `layout.maximum_entries_tried` of those that carry the per-match magic, and at most
    `layout.maximum_entries_opened` entries decompressed whatever they hold, so a save listing
    hundreds of them is never read whole even when not one of them is a per-match file. An
    entry without the magic is not a per-match file: it is counted, skipped, and does not count
    against the first limit. A save with no such entry, and one whose entries hold no table,
    both give a table of no rows.
    """
    entries_with_magic_tried = 0
    entries_without_magic = 0
    records: tuple[InjuryTypeRecord, ...] = ()
    for entry in entries:
        entries_opened = entries_with_magic_tried + entries_without_magic
        if (
            entries_with_magic_tried >= layout.maximum_entries_tried
            or entries_opened >= layout.maximum_entries_opened
        ):
            break
        payload = read_entry(entry)
        if not payload.startswith(layout.payload_prefix):
            entries_without_magic += 1
            continue
        entries_with_magic_tried += 1
        records = locate_injury_type_table(payload, layout)
        if records:
            break
    injury_types = tuple(
        InjuryType(type_id, name, FrozenMapping({"flag": flag, "second_id": second_id}))
        for type_id, name, flag, second_id in records
    )
    stats = InjuryTypeStats(
        match_entries=len(entries),
        entries_with_magic_tried=entries_with_magic_tried,
        entries_without_magic=entries_without_magic,
        table_entries=len(injury_types),
    )
    return injury_types, stats
