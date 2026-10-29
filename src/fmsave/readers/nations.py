"""The nation table, and the game-database id of each nation.

Every nation field fmsave reads elsewhere holds a nation's row in this table, counted from 0,
rather than the nation's id in the game's database. A row's closing header holds that database
id, which is the same on every save and is what an outside nation list is keyed on, so this
table is the join between the two.

Many other tables in `game_db` close their records with headers of the same shape, so the table
is told apart by walking its records whole, never by its closing headers alone. A walk is also
what puts each closing header at its own record's end: a record can hold a run of bytes shaped
like another row's closing header, and a search for those headers alone would read that run as
the row it names.
"""

from __future__ import annotations

import functools
import re
import struct
from dataclasses import dataclass

from fmsave._layouts import NationTableLayout, find_layout
from fmsave._reader_stats import NationStats
from fmsave.models.nations import Nation
from fmsave.readers._common import GAME_DB_SECTION

# The table's row count, then a zero byte.
_TABLE_HEAD = struct.Struct("<IB")
# The header that closes every record: its row position, its database id, and a third word.
_CLOSING_HEADER = struct.Struct("<III")
_STRING_LENGTH = struct.Struct("<I")
_COUNT_STRUCTS: dict[int, struct.Struct] = {
    1: struct.Struct("<B"),
    2: struct.Struct("<H"),
    4: struct.Struct("<I"),
}

# One walk step as the walk reads it: the count's struct (None for a single entry), then the
# entry's leading bytes, its string count and its trailing bytes.
type _Step = tuple[struct.Struct | None, int, int, int]
# One walked row: its database id and the third word of its closing header.
type _WalkedRow = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _NationScan:
    """Everything the nation search needs from a `NationTableLayout`, derived once.

    `search` matches the row count, the zero byte and the first record's opening byte, which
    is where every candidate table starts; its records start `records_offset` bytes later.
    """

    search: re.Pattern[bytes]
    records_offset: int
    row_count: int
    opening_byte: int
    steps: tuple[_Step, ...]
    max_entries: int
    max_string_bytes: int
    lowest_database_id: int
    highest_database_id: int


@functools.cache
def _nation_scan(layout: NationTableLayout) -> _NationScan:
    """The layout's derived search and walk steps, built on first use for each layout.

    Raises:
        ValueError: The row count is not a positive u32, the opening byte is not a byte, a
            step's count width is not 0, 1, 2 or 4, a step's byte or string count is negative,
            or the id range's upper bound is below its lower bound.
    """
    if not 0 < layout.row_count <= 0xFFFFFFFF:
        raise ValueError(f"the row count {layout.row_count} is not a positive u32")
    if not 0 <= layout.record_opening_byte <= 0xFF:
        raise ValueError(f"the opening byte {layout.record_opening_byte} is not a byte")
    steps: list[_Step] = []
    for step in layout.record_steps:
        if step.count_bytes and step.count_bytes not in _COUNT_STRUCTS:
            raise ValueError(f"a step's count is {step.count_bytes} bytes wide, not 1, 2 or 4")
        if min(step.lead_bytes, step.strings, step.tail_bytes) < 0:
            raise ValueError("a step's byte or string count is negative")
        count_struct = _COUNT_STRUCTS[step.count_bytes] if step.count_bytes else None
        steps.append((count_struct, step.lead_bytes, step.strings, step.tail_bytes))
    lowest_database_id, highest_database_id = layout.database_id_range
    if highest_database_id < lowest_database_id:
        raise ValueError("the database id range's upper bound is below its lower bound")
    table_start = _TABLE_HEAD.pack(layout.row_count, 0) + bytes((layout.record_opening_byte,))
    return _NationScan(
        search=re.compile(re.escape(table_start)),
        records_offset=_TABLE_HEAD.size,
        row_count=layout.row_count,
        opening_byte=layout.record_opening_byte,
        steps=tuple(steps),
        max_entries=layout.max_entries,
        max_string_bytes=layout.max_string_bytes,
        lowest_database_id=lowest_database_id,
        highest_database_id=highest_database_id,
    )


def find_nation_table_layout(game_db_schema: int | None, build: str) -> NationTableLayout:
    """Look up the nation-table layout for a `game_db` schema, falling back to the build."""
    return find_layout(NationTableLayout, GAME_DB_SECTION, game_db_schema, build).layout


def _closing_header_at(
    game_db: bytes, record_start: int, scan: _NationScan, buffer_length: int
) -> int | None:
    """Where the record at `record_start` ends and its closing header begins.

    None when the record does not open with the opening byte, a count or a string length lies
    past the end of `game_db` or over its ceiling, or the steps run past the end.
    """
    if record_start >= buffer_length or game_db[record_start] != scan.opening_byte:
        return None
    position = record_start + 1
    max_entries = scan.max_entries
    max_string_bytes = scan.max_string_bytes
    unpack_string_length = _STRING_LENGTH.unpack_from
    string_length_bytes = _STRING_LENGTH.size
    for count_struct, lead_bytes, strings, tail_bytes in scan.steps:
        if count_struct is None:
            entries = 1
        else:
            if position + count_struct.size > buffer_length:
                return None
            entries = count_struct.unpack_from(game_db, position)[0]
            if entries > max_entries:
                return None
            position += count_struct.size
        if not strings:
            position += entries * (lead_bytes + tail_bytes)
        else:
            for _ in range(entries):
                position += lead_bytes
                for _ in range(strings):
                    if position + string_length_bytes > buffer_length:
                        return None
                    string_bytes = unpack_string_length(game_db, position)[0]
                    if string_bytes > max_string_bytes:
                        return None
                    position += string_length_bytes + string_bytes
                position += tail_bytes
        if position > buffer_length:
            return None
    return position


def _walk_table(game_db: bytes, records_start: int, scan: _NationScan) -> list[_WalkedRow] | None:
    """Every row of the table whose first record starts at `records_start`, in table order.

    None unless every record walks, every closing header holds its own row position, and every
    database id is inside the layout's range and distinct.
    """
    buffer_length = len(game_db)
    unpack_closing_header = _CLOSING_HEADER.unpack_from
    closing_header_bytes = _CLOSING_HEADER.size
    lowest_database_id = scan.lowest_database_id
    highest_database_id = scan.highest_database_id
    rows: list[_WalkedRow] = []
    seen_database_ids: set[int] = set()
    position = records_start
    for row_position in range(scan.row_count):
        header_at = _closing_header_at(game_db, position, scan, buffer_length)
        if header_at is None or header_at + closing_header_bytes > buffer_length:
            return None
        stored_position, database_id, third_word = unpack_closing_header(game_db, header_at)
        if stored_position != row_position:
            return None
        if not lowest_database_id <= database_id <= highest_database_id:
            return None
        if database_id in seen_database_ids:
            return None
        seen_database_ids.add(database_id)
        rows.append((database_id, third_word))
        position = header_at + closing_header_bytes
    return rows


def read_nations(
    game_db: bytes, layout: NationTableLayout
) -> tuple[tuple[Nation, ...], NationStats]:
    """Find the nation table and read every nation's database id, in table order.

    Every candidate is walked whole, and rows are read only when exactly one candidate walks
    into a whole table. With none, or with more than one, nothing is read: no rows are better
    than rows from a table that may be the wrong one, and the table count in the stats is what
    says which of the two happened.

    Raises:
        ValueError: The layout is inconsistent (see `_nation_scan`).
    """
    scan = _nation_scan(layout)
    search = scan.search.search
    records_offset = scan.records_offset
    candidates = 0
    walked_tables: list[list[_WalkedRow]] = []
    match = search(game_db)
    while match is not None:
        candidates += 1
        candidate_at = match.start()
        # A table start whose count bytes could begin again inside itself would hide the second
        # candidate if the search stepped past the whole match, so it steps one byte on. The
        # pattern is a literal, which the regular expression engine searches for by its first
        # byte, so stepping on costs nothing worth saving.
        match = search(game_db, candidate_at + 1)
        rows = _walk_table(game_db, candidate_at + records_offset, scan)
        if rows is not None:
            walked_tables.append(rows)
    if len(walked_tables) != 1:
        stats = NationStats(
            candidates=candidates, tables=len(walked_tables), rows=0, database_id_copies=0
        )
        return (), stats
    (rows,) = walked_tables
    nations = tuple(
        Nation(nation_id=row_position, database_id=database_id)
        for row_position, (database_id, _third_word) in enumerate(rows)
    )
    database_id_copies = sum(1 for database_id, third_word in rows if third_word == database_id)
    stats = NationStats(
        candidates=candidates,
        tables=1,
        rows=len(nations),
        database_id_copies=database_id_copies,
    )
    return nations, stats
