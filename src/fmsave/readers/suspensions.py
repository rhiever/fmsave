"""Locating unserved suspension entries in `game_db` and joining them to their players.

A suspension entry is a short fixed-size record carrying a byte signature (see
`SuspensionLayout`). `locate_suspensions` finds every entry in one pass of a compiled regex over
the player region, from just before the first player record to the end of `game_db`, and gives
each entry to its owning player by bisecting the sorted record offsets. The pattern, the field
Struct, the offsets and the bounds are derived from the layout once per layout, and checked
for consistency at that point, so the search loop never reads the layout.
"""

from __future__ import annotations

import functools
import re
import struct
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from fmsave._frozen import FrozenMapping
from fmsave._layouts import SuspensionLayout
from fmsave._scan import decode_date
from fmsave.models.players import Player
from fmsave.models.suspensions import PlayerSuspension, Suspension
from fmsave.readers._common import build_gap_padded_struct
from fmsave.readers.player_scan import PlayerRecords


@dataclass(frozen=True, slots=True)
class SuspensionEntry:
    """One kept suspension entry, before it is joined to its player.

    Attributes:
        competition_id: The competition id, in the suspension id space.
        issued: The date the ban was issued.
        e7: The unidentified u16 exported as `unknown["e7"]`.
        e14: The unidentified u8 exported as `unknown["e14"]`.
    """

    competition_id: int
    issued: date
    e7: int
    e14: int


@dataclass(frozen=True, slots=True)
class _SuspensionSearch:
    """Everything `locate_suspensions` needs from a `SuspensionLayout`, derived once.

    `pattern` matches the signature from its first byte, which sits `pattern_offset` bytes
    after the entry start. `fields_struct` unpacks from the entry start, and the `*_index`
    fields give each value's position in its result.
    """

    pattern: re.Pattern[bytes]
    pattern_offset: int
    fields_struct: struct.Struct
    e7_index: int
    e14_index: int
    competition_id_index: int
    issued_date_offset: int
    owner_back_offset: int
    competition_id_lower_bound: int
    competition_id_upper_bound: int


def _build_signature_pattern(
    signature: tuple[tuple[int, int], ...],
) -> tuple[re.Pattern[bytes], int, int]:
    """(pattern, first_signature_offset, signature_end) for the signature's `(offset, value)`
    pairs: each signature byte literally, with `.{gap}` for the bytes between them.

    Raises:
        ValueError: The signature is empty, an offset is before the entry start, or an offset
            appears more than once.
    """
    if not signature:
        raise ValueError("the suspension signature must not be empty")
    sorted_signature = sorted(signature)
    first_offset = sorted_signature[0][0]
    if first_offset < 0:
        raise ValueError(
            f"signature offset {first_offset} is before the entry start; signature offsets "
            "count from the entry start"
        )
    pattern_parts: list[bytes] = []
    cursor = first_offset
    for offset, value in sorted_signature:
        gap = offset - cursor
        if gap < 0:
            raise ValueError(f"signature offset {offset} appears more than once")
        if gap:
            pattern_parts.append(b".{%d}" % gap)
        pattern_parts.append(re.escape(bytes((value,))))
        cursor = offset + 1
    return re.compile(b"".join(pattern_parts), re.DOTALL), first_offset, cursor


@functools.cache
def _suspension_search(layout: SuspensionLayout) -> _SuspensionSearch:
    """The layout's compiled search, built on first use for each layout.

    Raises:
        ValueError: The signature is empty, has an offset before the entry start or an offset
            listed twice; two fields overlap or a field starts before the entry start; a field
            ends past the last signature byte, so a signature match would not guarantee it is
            readable; or `competition_id_exclusive_range` leaves no id strictly between its
            bounds.
    """
    pattern, pattern_offset, signature_end = _build_signature_pattern(layout.signature)
    field_specs = [
        (layout.unknown_e7_offset, "H", "e7"),
        (layout.issued_date_offset, "I", "issued_date"),
        (layout.unknown_e14_offset, "B", "e14"),
        (layout.competition_id_offset, "H", "competition_id"),
    ]
    fields_struct, _start_offset, index_by_name = build_gap_padded_struct(
        field_specs, start_offset=0
    )
    for offset, format_code, field_name in field_specs:
        if offset + struct.calcsize(format_code) > signature_end:
            raise ValueError(
                f"field {field_name!r} at offset {offset} ends past the last signature byte "
                f"(offset {signature_end - 1}), so a signature match does not guarantee it is "
                "readable"
            )
    lower_bound, upper_bound = layout.competition_id_exclusive_range
    if upper_bound - lower_bound < 2:
        raise ValueError(
            f"competition_id_exclusive_range {layout.competition_id_exclusive_range} leaves no "
            "competition id strictly between its bounds"
        )
    return _SuspensionSearch(
        pattern=pattern,
        pattern_offset=pattern_offset,
        fields_struct=fields_struct,
        e7_index=index_by_name["e7"],
        e14_index=index_by_name["e14"],
        competition_id_index=index_by_name["competition_id"],
        issued_date_offset=layout.issued_date_offset,
        owner_back_offset=layout.owner_back_offset,
        competition_id_lower_bound=lower_bound,
        competition_id_upper_bound=upper_bound,
    )


def locate_suspensions(
    game_db: bytes, player_records: PlayerRecords, layout: SuspensionLayout
) -> Mapping[int, tuple[SuspensionEntry, ...]]:
    """Every kept suspension entry, keyed by the position of its owning player record.

    Positions index `player_records.record_offsets` and come in ascending order; each
    player's entries keep the order of their offsets. A player with no entry has no key.
    The search runs once over `game_db`, starting `owner_back_offset` bytes before the first
    record (or at 0); an entry is kept when it has an owner, a valid issued date (a readable
    game date, so day 366 of a non-leap year is rejected) and a competition id strictly inside
    the layout's range.

    Raises:
        ValueError: The layout is inconsistent (see `_suspension_search`).
    """
    search = _suspension_search(layout)
    record_offsets = player_records.record_offsets
    if not record_offsets:
        return {}
    pattern_offset = search.pattern_offset
    owner_back_offset = search.owner_back_offset
    unpack_from = search.fields_struct.unpack_from
    e7_index = search.e7_index
    e14_index = search.e14_index
    competition_id_index = search.competition_id_index
    issued_date_offset = search.issued_date_offset
    lower_bound = search.competition_id_lower_bound
    upper_bound = search.competition_id_upper_bound

    region_start = max(0, record_offsets[0] - owner_back_offset)
    entries_by_position: dict[int, list[SuspensionEntry]] = {}
    for match in search.pattern.finditer(game_db, region_start, len(game_db)):
        entry_offset = match.start() - pattern_offset
        if entry_offset < 0:
            continue
        position = bisect_right(record_offsets, entry_offset + owner_back_offset) - 1
        if position < 0:
            continue
        field_values = unpack_from(game_db, entry_offset)
        competition_id: int = field_values[competition_id_index]
        if not lower_bound < competition_id < upper_bound:
            continue
        issued = decode_date(game_db, entry_offset + issued_date_offset)
        if issued is None:
            continue
        entry = SuspensionEntry(
            competition_id, issued, field_values[e7_index], field_values[e14_index]
        )
        position_entries = entries_by_position.get(position)
        if position_entries is None:
            entries_by_position[position] = [entry]
        else:
            position_entries.append(entry)
    return {position: tuple(entries) for position, entries in entries_by_position.items()}


def player_suspensions(entries: Sequence[SuspensionEntry]) -> tuple[PlayerSuspension, ...]:
    """The `Player.suspensions` value for one player's located entries."""
    return tuple(PlayerSuspension(entry.competition_id, entry.issued) for entry in entries)


def suspension_rows(player: Player, entries: Sequence[SuspensionEntry]) -> list[Suspension]:
    """One `Suspension` row per entry, joined to the decoded player and its current club."""
    return [
        Suspension(
            player.uid,
            player.name,
            player.club_uid,
            player.club_name,
            entry.competition_id,
            entry.issued,
            FrozenMapping({"e7": entry.e7, "e14": entry.e14}),
        )
        for entry in entries
    ]
