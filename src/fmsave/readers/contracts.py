"""Decoding a player's contract chain in `game_db` into `Contract`.

A player's contract is assembled from a chain of registration records (the tag
`01 00 6c 07` plus a matching selector), searched for in the player's own record window.
`ContractDecoder`, built once per `players()`/`contracts()` call from the save's layout and
its `ClubIndex`, holds everything a single record's decode needs, the way
`readers/persons.py`'s `PersonBlockDecoder` does: every offset, size, sentinel, Struct and
needle the hot path (`decode`, `decode_chain_record` and the methods they call) uses is bound
as a plain field at build time, computed once from `ContractLayout`, so decoding never repeats
a layout lookup, a team-to-club join, or a struct-layout computation. `ContractDecoder` holds
no reference to the layout itself once built. `ContractDecoder.decode_chain_record` decodes a
single located chain record (its tail, its clauses, its head, and its resolved club) from its
tag offset alone, with no player window; `ContractDecoder.decode` finds every chain record for
one player and assembles the public `Contract` by the assembly rules documented on
`ContractLayout` and on the `Contract` and `ContractChainEntry` models.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import date
from typing import cast

from fmsave._errors import CorruptSaveError
from fmsave._frozen import FrozenMapping
from fmsave._layouts import ContractLayout
from fmsave._reader_stats import ContractStats
from fmsave._scan import decode_date
from fmsave.models.common import CodedValue, ContractEndSource
from fmsave.models.contracts import (
    Clause,
    ClauseKind,
    Contract,
    ContractChainEntry,
    ContractType,
    SquadStatus,
)
from fmsave.readers._common import build_gap_padded_struct, section_label
from fmsave.readers.clubs import ClubIndex

_U32 = struct.Struct("<I")
_FOUR_FF = b"\xff\xff\xff\xff"
_MISSING_U32 = 0xFFFFFFFF
_MISSING_U16 = 0xFFFF
_DATE_CACHE_MISS = object()
_AWARD_LIST_ABSENT = 0
_AWARD_LIST_PRESENT = 1
_UNSIGNED_FORMAT_BY_WIDTH = {1: "B", 2: "H", 4: "I"}

# One decoded chain record, before assembly, in this fixed field order: the first 7 fields
# match ContractChainEntry's own field order exactly (club_uid, club_name, team_id, wage,
# start, end, has_tail), so a ContractChainEntry can be built positionally straight from a
# record's first 7 items. When has_tail is False, squad_status_raw, event_count,
# contract_type_raw and unknown are None and clauses is (). When has_tail is True,
# squad_status_raw and event_count are ints and unknown is a dict of the tail's unknown
# fields; clauses is () unless a clause table was found, and contract_type_raw is None and
# unknown has no money_* keys unless the record's head was found.
type _ChainRecordTuple = tuple[
    "int | None",
    "str | None",
    int,
    int,
    "date | None",
    "date | None",
    bool,
    "int | None",
    "int | None",
    "tuple[Clause, ...]",
    "int | None",
    "dict[str, int] | None",
]

# Positions in a decoded chain record tuple, for readers outside this module.
CHAIN_RECORD_CLUB_UID = 0
CHAIN_RECORD_END = 5
CHAIN_RECORD_HAS_TAIL = 6


def _build_unpack_ordered_struct(
    struct_description: str,
    fields: list[tuple[int, str, str]],
    *,
    start_offset: int | None = None,
) -> tuple[struct.Struct, int]:
    """(struct, start_offset) for `fields`, which are listed in the order the decoder unpacks
    them into fixed names.

    Raises:
        ValueError: Two fields overlap, or the layout's offsets place the fields in a
            different order from the one listed, so a fixed-name unpack would misassign them.
    """
    struct_object, struct_start_offset, index_by_name = build_gap_padded_struct(
        fields, start_offset=start_offset
    )
    unpack_order = [field_name for _offset, _format_code, field_name in fields]
    layout_order = sorted(index_by_name, key=index_by_name.__getitem__)
    if layout_order != unpack_order:
        raise ValueError(
            f"the {struct_description} fields must be laid out in the order they are "
            f"unpacked ({', '.join(unpack_order)}), but the layout orders them "
            f"{', '.join(layout_order)}"
        )
    return struct_object, struct_start_offset


def _build_tail_struct(layout: ContractLayout) -> struct.Struct:
    """One struct spanning the whole tail block, from `E` (offset 0) through event_count.

    Reads e2, e8, e12, e16, e20, e24, the end date's raw u32 (kept raw for the date cache),
    squad status, e37, e38, e39 and event_count; skips the sentinel bytes the locator
    already checked and the excluded printed-start date at `tail_end_offset + 4`.

    Raises:
        ValueError: The tail fields overlap or are not laid out in unpack order.
    """
    fields = [
        (layout.tail_e2_offset, "H", "e2"),
        (layout.tail_e8_offset, "I", "e8"),
        (layout.tail_e12_offset, "I", "e12"),
        (layout.tail_e16_offset, "I", "e16"),
        (layout.tail_e20_offset, "I", "e20"),
        (layout.tail_e24_offset, "I", "e24"),
        (layout.tail_end_offset, "I", "raw_end"),
        (layout.tail_squad_status_offset, "B", "squad_status"),
        (layout.tail_e37_offset, "B", "e37"),
        (layout.tail_e38_offset, "B", "e38"),
        (layout.tail_e39_offset, "B", "e39"),
        (layout.tail_event_count_offset, "I", "event_count"),
    ]
    struct_object, _start_offset = _build_unpack_ordered_struct("tail", fields, start_offset=0)
    return struct_object


def _build_head_struct(layout: ContractLayout) -> tuple[struct.Struct, int]:
    """(struct, start_offset): one struct spanning the head gate through money_c.

    Raises:
        ValueError: The head fields overlap or are not laid out in unpack order.
    """
    fields = [
        (layout.head_gate_offset, "H", "gate"),
        (layout.head_type_offset, "B", "type"),
        (layout.head_money_a_offset, "I", "money_a"),
        (layout.head_money_b_offset, "I", "money_b"),
        (layout.head_money_c_offset, "I", "money_c"),
    ]
    return _build_unpack_ordered_struct("head", fields)


def _build_team_wage_struct(layout: ContractLayout) -> tuple[struct.Struct, int]:
    """(struct, start_offset): one struct reading team_id and wage together.

    Raises:
        ValueError: The two fields overlap or wage is laid out before team_id.
    """
    fields = [
        (layout.team_id_offset, "I", "team_id"),
        (layout.wage_offset, "I", "wage"),
    ]
    return _build_unpack_ordered_struct("team and wage", fields)


def _build_clause_entry_struct(layout: ContractLayout) -> struct.Struct:
    """One clause entry's struct (value, parameter, kind), starting at offset 0.

    Raises:
        ValueError: The entry's fields overlap, are not laid out in unpack order, or do
            not fit exactly in `clause_entry_bytes`.
    """
    fields = [
        (layout.clause_value_offset, "I", "value"),
        (layout.clause_parameter_offset, "H", "parameter"),
        (layout.clause_kind_offset, "H", "kind"),
    ]
    struct_object, _start_offset = _build_unpack_ordered_struct(
        "clause entry", fields, start_offset=0
    )
    if struct_object.size != layout.clause_entry_bytes:
        raise ValueError(
            f"a clause entry struct is {struct_object.size} bytes, not clause_entry_bytes "
            f"({layout.clause_entry_bytes})"
        )
    return struct_object


def _empty_bonus_lists_size(layout: ContractLayout) -> int:
    """How many bytes follow the last clause entry when both bonus lists are empty."""
    return (
        layout.clause_competition_count_bytes
        + layout.clause_award_flag_bytes
        + layout.clause_trailer_bytes
    )


def _build_clause_structs(
    layout: ContractLayout, entry_struct: struct.Struct
) -> tuple[struct.Struct, ...]:
    """One struct per possible clause count, each unpacking that many entries in a row and
    then, as raw bytes, the bytes empty bonus lists would fill right after the last entry.

    The fast path looks for a table exactly where one with empty bonus lists would sit, so a
    table it finds ends at the tail start only when those bytes are all zero.

    Raises:
        ValueError: `clause_entry_bytes` differs from `clause_step_bytes`, so the fast path's
            candidates would not step by whole entries; or `clause_entries_offset` is not minus
            the size of empty bonus lists, so a table with empty bonus lists at a fast-path
            candidate would not end at the tail start.
    """
    if layout.clause_entry_bytes != layout.clause_step_bytes:
        raise ValueError(
            f"clause_entry_bytes ({layout.clause_entry_bytes}) must equal clause_step_bytes "
            f"({layout.clause_step_bytes})"
        )
    empty_lists_size = _empty_bonus_lists_size(layout)
    if layout.clause_entries_offset != -empty_lists_size:
        raise ValueError(
            "the clause entries must end where empty bonus lists start: clause_entries_offset "
            f"({layout.clause_entries_offset}) must be minus the size of empty bonus lists "
            "(clause_competition_count_bytes + clause_award_flag_bytes + clause_trailer_bytes "
            f"= {empty_lists_size})"
        )
    entry_format = entry_struct.format
    if isinstance(entry_format, bytes):
        entry_format = entry_format.decode("ascii")
    entry_body = entry_format.removeprefix("<").removeprefix("=")
    return tuple(
        struct.Struct("<" + entry_body * count + f"{empty_lists_size}s")
        for count in range(layout.clause_max_count + 1)
    )


def _build_unsigned_struct(width: int, field_name: str) -> struct.Struct:
    """A little-endian unsigned integer struct `width` bytes wide.

    Raises:
        ValueError: `width` is not 1, 2 or 4.
    """
    format_code = _UNSIGNED_FORMAT_BY_WIDTH.get(width)
    if format_code is None:
        raise ValueError(f"{field_name} ({width}) must be 1, 2 or 4")
    return struct.Struct("<" + format_code)


def _check_item_prefix(prefix: bytes, item_bytes: int, prefix_name: str, size_name: str) -> bytes:
    """`prefix`, once checked to fit inside one item.

    Raises:
        ValueError: The prefix is longer than an item.
    """
    if len(prefix) > item_bytes:
        raise ValueError(
            f"{prefix_name} ({len(prefix)} bytes) must not be longer than {size_name} "
            f"({item_bytes})"
        )
    return prefix


def _build_team_marker_zero_run(layout: ContractLayout) -> bytes:
    """The zero bytes that fill a clause-table marker after its team id.

    Raises:
        ValueError: The team id would not leave at least one byte of the marker for zeros.
    """
    team_id_bytes = layout.clause_team_marker_id_bytes
    if not 0 < team_id_bytes < layout.clause_ff_count:
        raise ValueError(
            f"clause_team_marker_id_bytes ({team_id_bytes}) must be at least 1 and less than "
            f"clause_ff_count ({layout.clause_ff_count})"
        )
    return bytes(layout.clause_ff_count - team_id_bytes)


def _build_clause_prefixes(layout: ContractLayout) -> tuple[bytes, ...]:
    """`FF` x `clause_ff_count`, `00` x `clause_zero_count`, then the count byte, per count.

    Each needle is matched from `clause_ff_offset` as one contiguous run.

    Raises:
        ValueError: The zero run does not start right after the `FF` run, or the count byte
            does not sit right after the zero run.
    """
    zero_run_offset = layout.clause_ff_offset + layout.clause_ff_count
    if layout.clause_zero_offset != zero_run_offset:
        raise ValueError(
            f"clause_zero_offset ({layout.clause_zero_offset}) must immediately follow the FF "
            f"run (clause_ff_offset + clause_ff_count = {zero_run_offset})"
        )
    count_byte_offset = layout.clause_zero_offset + layout.clause_zero_count
    if layout.clause_count_offset != count_byte_offset:
        raise ValueError(
            f"clause_count_offset ({layout.clause_count_offset}) must immediately follow the "
            f"zero run (clause_zero_offset + clause_zero_count = {count_byte_offset})"
        )
    return tuple(
        b"\xff" * layout.clause_ff_count + b"\x00" * layout.clause_zero_count + bytes([count])
        for count in range(layout.clause_max_count + 1)
    )


def _build_tail_signature(layout: ContractLayout) -> tuple[bytes, int]:
    """(signature_bytes, offset_from_E): the sentinel byte and word, laid out contiguously,
    so `bytes.rfind` can search for both sentinels as one needle.

    Raises:
        ValueError: The sentinel word does not immediately follow the sentinel byte.
    """
    byte_offset = layout.tail_sentinel_byte_offset
    word_offset = layout.tail_sentinel_word_offset
    if word_offset != byte_offset + 1:
        raise ValueError(
            "tail_sentinel_word_offset must immediately follow tail_sentinel_byte_offset"
        )
    signature = bytes([layout.tail_sentinel_byte_value]) + struct.pack(
        "<I", layout.tail_sentinel_word_value
    )
    return signature, byte_offset


def _build_fallback_zero_needle(layout: ContractLayout) -> bytes:
    """`fallback_nonzero_length` zero bytes: a pair is rejected when the bytes at
    `j + fallback_nonzero_offset` start with this needle.

    Raises:
        ValueError: `fallback_nonzero_length` is below 1, which would reject every pair.
    """
    if layout.fallback_nonzero_length < 1:
        raise ValueError(
            f"fallback_nonzero_length ({layout.fallback_nonzero_length}) must be at least 1"
        )
    return bytes(layout.fallback_nonzero_length)


def _new_date_cache() -> dict[int, date | None]:
    return {}


def _new_clause_kind_cache() -> dict[int, CodedValue[ClauseKind]]:
    return {}


def _new_squad_status_cache() -> dict[int, CodedValue[SquadStatus]]:
    return {}


def _new_contract_type_cache() -> dict[int, CodedValue[ContractType]]:
    return {}


@dataclass(slots=True)
class ContractDecoder:
    """Decodes contract chains for one save; built once per `players()`/`contracts()` call.

    `build_contract_decoder` binds, as plain fields computed once: every `ContractLayout`
    offset, count and value the hot path (`decode`, `decode_chain_record` and the methods
    they call) reads; the Structs, the tail signature, the clause prefixes and the fallback
    zero needle derived from them; the team-to-club lookup; the save clock and file name.
    No method below loads a `ContractLayout` attribute, and the decoder keeps no reference
    to the layout itself. The module constants and literals that remain in the methods
    describe things `ContractLayout` does not, for example the u32 width of the selector
    and of each date, the `E+0`/`E+1` zero bytes the tail locator checks, the fallback
    reader's `FF FF FF FF` needle and its `j = i + 8`, the `FFFFFFFF` and `FFFF` values
    that mean a clause value or parameter is absent, and the award flag values 0 (no award
    list) and 1 (an award list follows). The per-save caches (dates by their raw stored u32, and `CodedValue`
    labels by raw code) are keyed by values shared across many players; `CodedValue` objects
    are never cached process-globally, since a cache tied to this decoder is dropped with
    the save. The `*_count` fields count what decoding sees, for the contract checks.
    """

    club_by_team_id: dict[int, tuple[int | None, str | None]]
    clock: date
    file_name: str

    # Chain search.
    tag: bytes
    chain_window_start_offset: int
    chain_window_end_offset: int
    selector_offset: int

    # Chain record fixed fields (team id, wage) and the start date.
    team_wage_struct: struct.Struct
    team_wage_struct_offset: int
    start_offset: int

    # Tail locator.
    tail_base_offset: int
    tail_step_bytes: int
    tail_max_event_count: int
    tail_signature: bytes
    tail_signature_offset: int
    tail_event_count_offset: int
    tail_end_offset: int
    tail_struct: struct.Struct

    # Clause locator and reader.
    clause_step_bytes: int
    clause_max_count: int
    clause_ff_offset: int
    clause_count_offset: int
    clause_entries_offset: int
    clause_prefixes: tuple[bytes, ...]
    clause_structs: tuple[struct.Struct, ...]
    clause_empty_lists: bytes

    # Clause locator fallback: the other marker form, the bonus lists and the trailer.
    clause_entry_bytes: int
    clause_zero_offset: int
    clause_count_needles: tuple[bytes, ...]
    clause_ff_run: bytes
    clause_team_marker_id_ff: bytes
    clause_team_marker_zero_run: bytes
    clause_competition_count_struct: struct.Struct
    clause_competition_item_bytes: int
    clause_competition_item_prefix: bytes
    clause_competition_max_count: int
    clause_award_flag_struct: struct.Struct
    clause_award_count_struct: struct.Struct
    clause_award_item_bytes: int
    clause_award_item_prefix: bytes
    clause_award_max_count: int
    clause_trailer: bytes

    # Head reader.
    head_struct: struct.Struct
    head_struct_offset: int
    head_gate_value: int

    # Fallback reader.
    fallback_start_from_record: int
    fallback_end_margin: int
    fallback_gate_length: int
    fallback_nonzero_offset: int
    fallback_nonzero_length: int
    fallback_zero_needle: bytes
    fallback_end_date_offset: int
    fallback_start_date_offset: int

    empty_unknown: FrozenMapping[str, int]

    date_cache: dict[int, date | None] = field(default_factory=_new_date_cache)
    clause_kind_cache: dict[int, CodedValue[ClauseKind]] = field(
        default_factory=_new_clause_kind_cache
    )
    squad_status_cache: dict[int, CodedValue[SquadStatus]] = field(
        default_factory=_new_squad_status_cache
    )
    contract_type_cache: dict[int, CodedValue[ContractType]] = field(
        default_factory=_new_contract_type_cache
    )

    # Counts for the contract checks, added to as chain records are decoded.
    players_with_chain_count: int = 0
    chain_record_count: int = 0
    chain_teams_resolved_count: int = 0
    tails_parsed_count: int = 0
    tail_ends_count: int = 0
    tail_ends_past_count: int = 0
    tails_without_clause_table_count: int = 0
    clause_table_count: int = 0
    clause_tables_ending_at_tail_count: int = 0
    head_ok_count: int = 0

    def stats(self, player_count: int, contract_count: int) -> ContractStats:
        """What decoding has counted so far, with the pass's player and contract counts."""
        return ContractStats(
            players=player_count,
            contracts=contract_count,
            players_with_chain=self.players_with_chain_count,
            chain_records=self.chain_record_count,
            tails_parsed=self.tails_parsed_count,
            tails_without_clause_table=self.tails_without_clause_table_count,
            clause_tables=self.clause_table_count,
            clause_tables_ending_at_tail=self.clause_tables_ending_at_tail_count,
            head_ok=self.head_ok_count,
            tail_ends=self.tail_ends_count,
            tail_ends_past=self.tail_ends_past_count,
            chain_teams_resolved=self.chain_teams_resolved_count,
        )

    def _cached_date(self, game_db: bytes, raw_value: int, date_offset: int) -> date | None:
        cache = self.date_cache
        cached = cache.get(raw_value, _DATE_CACHE_MISS)
        if cached is not _DATE_CACHE_MISS:
            return cast("date | None", cached)
        decoded = decode_date(game_db, date_offset)
        cache[raw_value] = decoded
        return decoded

    def _cached_clause_kind(self, raw_kind: int) -> CodedValue[ClauseKind]:
        cache = self.clause_kind_cache
        kind = cache.get(raw_kind)
        if kind is None:
            kind = cache[raw_kind] = CodedValue.from_raw(ClauseKind, raw_kind)
        return kind

    def _cached_squad_status(self, raw_status: int) -> CodedValue[SquadStatus]:
        cache = self.squad_status_cache
        status = cache.get(raw_status)
        if status is None:
            status = cache[raw_status] = CodedValue.from_raw(SquadStatus, raw_status)
        return status

    def _cached_contract_type(self, raw_type: int) -> CodedValue[ContractType]:
        cache = self.contract_type_cache
        contract_type = cache.get(raw_type)
        if contract_type is None:
            contract_type = cache[raw_type] = CodedValue.from_raw(ContractType, raw_type)
        return contract_type

    def _locate_tail(self, game_db: bytes, chain_tag_offset: int) -> int | None:
        """The tail start offset E, or None when no candidate's checks all pass.

        A candidate E is a tail only when the bytes at `E+0` and `E+1` are both zero, the
        tail signature (the sentinel byte and word) sits at `E + tail_signature_offset`, the
        whole tail struct fits inside game_db, and the stored event count equals the
        candidate's event count.

        Tries `event_count = 0` (`E = chain_tag_offset - tail_base_offset`) directly first.
        Failing that, it searches right to left for the tail signature with `rfind`, down to
        `event_count = tail_max_event_count`, so candidates come back in ascending
        `event_count` order; a hit is considered only when its distance from the
        `event_count = 0` position is a multiple of `tail_step_bytes`, and is accepted when
        the checks above pass for that multiple.
        """
        first_candidate = chain_tag_offset - self.tail_base_offset
        if first_candidate < 0:
            return None
        game_db_length = len(game_db)
        tail_struct_size = self.tail_struct.size
        tail_signature = self.tail_signature
        signature_offset = self.tail_signature_offset
        event_count_offset = self.tail_event_count_offset
        if (
            first_candidate + tail_struct_size <= game_db_length
            and game_db[first_candidate] == 0
            and game_db[first_candidate + 1] == 0
            and game_db.startswith(tail_signature, first_candidate + signature_offset)
            and _U32.unpack_from(game_db, first_candidate + event_count_offset)[0] == 0
        ):
            return first_candidate

        step_bytes = self.tail_step_bytes
        lowest_candidate = first_candidate - step_bytes * self.tail_max_event_count
        lowest_candidate = max(lowest_candidate, 0)
        # Bounds the search to distances of at least one step, since event_count = 0 was
        # already tried above: the signature for event_count = 1 sits at
        # first_candidate - step_bytes + signature_offset, and rfind's end is exclusive.
        search_end = first_candidate - step_bytes + signature_offset + len(tail_signature)
        signature_start = lowest_candidate + signature_offset
        if search_end <= signature_start:
            return None
        rfind = game_db.rfind
        signature_hit = rfind(tail_signature, signature_start, search_end)
        while signature_hit >= 0:
            candidate = signature_hit - signature_offset
            distance = first_candidate - candidate
            if (
                distance % step_bytes == 0
                and candidate + tail_struct_size <= game_db_length
                and game_db[candidate] == 0
                and game_db[candidate + 1] == 0
            ):
                event_count = distance // step_bytes
                stored_event_count: int = _U32.unpack_from(game_db, candidate + event_count_offset)[
                    0
                ]
                if stored_event_count == event_count:
                    return candidate
            signature_hit = rfind(tail_signature, signature_start, signature_hit + 4)
        return None

    def _locate_clause_base(self, game_db: bytes, tail_offset: int) -> tuple[int, int] | None:
        """(base, count), or None when no candidate count's checks all pass.

        Checks the cheap count byte first, then confirms with one `startswith` against a
        precomputed `FF*n + 00*m + count` needle, so a false count byte never allocates a
        slice to compare.
        """
        game_db_length = len(game_db)
        step_bytes = self.clause_step_bytes
        ff_offset = self.clause_ff_offset
        count_offset = self.clause_count_offset
        clause_prefixes = self.clause_prefixes
        startswith = game_db.startswith
        for count in range(self.clause_max_count + 1):
            base = tail_offset - step_bytes * count
            ff_start = base + ff_offset
            if ff_start < 0:
                return None
            count_at = base + count_offset
            if (
                count_at < game_db_length
                and game_db[count_at] == count
                and startswith(clause_prefixes[count], ff_start)
            ):
                return base, count
        return None

    def _locate_clause_base_fallback(
        self, game_db: bytes, tail_offset: int
    ) -> tuple[int, int] | None:
        """(base, count) of the clause table nearest the tail start that ends exactly there, or
        None.

        Used when `_locate_clause_base` finds nothing, which happens when bonus lists sit
        between the entries and the tail, or when the marker holds a team id. Read forward from
        its base, a table's entries, competition list, award flag and list, and zero trailer
        must end exactly at `tail_offset`. A base has only one forward reading, so the search
        works back from the tail instead: each way the award list can end at the trailer fixes
        where the competition list ends, each competition count then fixes where the entries
        end, and each clause count then fixes one base. A base is accepted when its zero run
        and count byte check and its marker is all `FF`, or a team id that is not all `FF`
        followed by zero bytes. Of the accepted bases, the nearest to the tail is returned.
        """
        startswith = game_db.startswith
        trailer_start = tail_offset - len(self.clause_trailer)
        flag_struct = self.clause_award_flag_struct
        flag_bytes = flag_struct.size
        absent_flag_offset = trailer_start - flag_bytes
        if absent_flag_offset < 0 or not startswith(self.clause_trailer, trailer_start):
            return None

        # Where the award list (its flag first) starts, for each way it can end at the trailer.
        award_list_starts: list[int] = []
        if flag_struct.unpack_from(game_db, absent_flag_offset)[0] == _AWARD_LIST_ABSENT:
            award_list_starts.append(absent_flag_offset)
        award_count_struct = self.clause_award_count_struct
        award_count_bytes = award_count_struct.size
        award_item_bytes = self.clause_award_item_bytes
        award_item_prefix = self.clause_award_item_prefix
        for award_count in range(self.clause_award_max_count + 1):
            award_items_start = trailer_start - award_item_bytes * award_count
            award_count_offset = award_items_start - award_count_bytes
            flag_offset = award_count_offset - flag_bytes
            if flag_offset < 0:
                break
            if (
                award_count_struct.unpack_from(game_db, award_count_offset)[0] == award_count
                and flag_struct.unpack_from(game_db, flag_offset)[0] == _AWARD_LIST_PRESENT
                and all(
                    startswith(award_item_prefix, award_items_start + award_item_bytes * index)
                    for index in range(award_count)
                )
            ):
                award_list_starts.append(flag_offset)

        competition_count_struct = self.clause_competition_count_struct
        competition_count_bytes = competition_count_struct.size
        competition_item_bytes = self.clause_competition_item_bytes
        competition_item_prefix = self.clause_competition_item_prefix
        competition_max_count = self.clause_competition_max_count
        entry_bytes = self.clause_entry_bytes
        entries_offset = self.clause_entries_offset
        ff_offset = self.clause_ff_offset
        zero_offset = self.clause_zero_offset
        count_needles = self.clause_count_needles
        ff_run = self.clause_ff_run
        team_id_ff = self.clause_team_marker_id_ff
        team_zero_run = self.clause_team_marker_zero_run
        team_zero_offset = len(team_id_ff)
        clause_max_count = self.clause_max_count
        nearest: tuple[int, int] | None = None
        for award_list_start in award_list_starts:
            for competition_count in range(competition_max_count + 1):
                competition_items_start = (
                    award_list_start - competition_item_bytes * competition_count
                )
                entries_end = competition_items_start - competition_count_bytes
                if entries_end < 0:
                    break
                if competition_count_struct.unpack_from(game_db, entries_end)[
                    0
                ] != competition_count or not all(
                    startswith(
                        competition_item_prefix,
                        competition_items_start + competition_item_bytes * index,
                    )
                    for index in range(competition_count)
                ):
                    continue
                for clause_count in range(clause_max_count + 1):
                    base = entries_end - entries_offset - entry_bytes * clause_count
                    marker_offset = base + ff_offset
                    if marker_offset < 0 or (nearest is not None and base <= nearest[0]):
                        break
                    if startswith(count_needles[clause_count], base + zero_offset) and (
                        startswith(ff_run, marker_offset)
                        or (
                            not startswith(team_id_ff, marker_offset)
                            and startswith(team_zero_run, marker_offset + team_zero_offset)
                        )
                    ):
                        nearest = (base, clause_count)
                        break
        return nearest

    def _read_clauses(
        self, game_db: bytes, base: int, count: int
    ) -> tuple[tuple[Clause, ...], bytes]:
        """(clauses, bytes_after_entries): the clause entries, and the bytes right after the
        last entry that empty bonus lists would fill.
        """
        entries_start = base + self.clause_entries_offset
        values = self.clause_structs[count].unpack_from(game_db, entries_start)
        bytes_after_entries: bytes = values[-1]
        if count == 0:
            return (), bytes_after_entries
        clauses: list[Clause] = []
        for entry_index in range(0, count * 3, 3):
            raw_value = values[entry_index]
            raw_parameter = values[entry_index + 1]
            raw_kind = values[entry_index + 2]
            clauses.append(
                Clause(
                    self._cached_clause_kind(raw_kind),
                    None if raw_parameter == _MISSING_U16 else raw_parameter,
                    None if raw_value == _MISSING_U32 else raw_value,
                )
            )
        return tuple(clauses), bytes_after_entries

    def _read_head(self, game_db: bytes, base: int) -> tuple[int, int, int, int] | None:
        head_offset = base + self.head_struct_offset
        head_struct = self.head_struct
        if head_offset < 0 or head_offset + head_struct.size > len(game_db):
            return None
        gate_value, contract_type_raw, money_a, money_b, money_c = head_struct.unpack_from(
            game_db, head_offset
        )
        if gate_value != self.head_gate_value:
            return None
        return contract_type_raw, money_a, money_b, money_c

    def decode_chain_record(self, game_db: bytes, chain_tag_offset: int) -> _ChainRecordTuple:
        """Decode one chain record's resolved club, team, wage, dates, tail and clauses from
        its tag offset alone: callable without a player window.

        Raises:
            CorruptSaveError: The record's team id or wage runs past the end of game_db.
        """
        team_wage_struct = self.team_wage_struct
        team_wage_offset = chain_tag_offset + self.team_wage_struct_offset
        fixed_fields_end = team_wage_offset + team_wage_struct.size
        if fixed_fields_end > len(game_db):
            raise CorruptSaveError(
                f"{section_label(self.file_name)}: a contract chain record at offset "
                f"{chain_tag_offset} needs bytes up to offset {fixed_fields_end}, past the "
                "end of the section"
            )
        team_id, wage = team_wage_struct.unpack_from(game_db, team_wage_offset)
        club_uid, club_name = self.club_by_team_id.get(team_id, (None, None))
        self.chain_record_count += 1
        if club_uid is not None:
            self.chain_teams_resolved_count += 1

        start_offset = chain_tag_offset + self.start_offset
        start: date | None = None
        if start_offset >= 0:
            raw_start: int = _U32.unpack_from(game_db, start_offset)[0]
            start = self._cached_date(game_db, raw_start, start_offset)

        tail_offset = self._locate_tail(game_db, chain_tag_offset)
        if tail_offset is None:
            return (
                club_uid,
                club_name,
                team_id,
                wage,
                start,
                None,
                False,
                None,
                None,
                (),
                None,
                None,
            )

        (
            e2,
            e8,
            e12,
            e16,
            e20,
            e24,
            raw_end,
            squad_status_raw,
            e37,
            e38,
            e39,
            event_count,
        ) = self.tail_struct.unpack_from(game_db, tail_offset)
        end = self._cached_date(game_db, raw_end, tail_offset + self.tail_end_offset)
        self.tails_parsed_count += 1
        if end is not None:
            self.tail_ends_count += 1
            if end < self.clock:
                self.tail_ends_past_count += 1
        unknown: dict[str, int] = {
            "e2": e2,
            "e8": e8,
            "e12": e12,
            "e16": e16,
            "e20": e20,
            "e24": e24,
            "e37": e37,
            "e38": e38,
            "e39": e39,
        }

        clause_base = self._locate_clause_base(game_db, tail_offset)
        if clause_base is not None:
            base, count = clause_base
            clauses, bytes_after_entries = self._read_clauses(game_db, base, count)
            if bytes_after_entries == self.clause_empty_lists:
                self.clause_tables_ending_at_tail_count += 1
        else:
            clause_base = self._locate_clause_base_fallback(game_db, tail_offset)
            if clause_base is None:
                self.tails_without_clause_table_count += 1
                return (
                    club_uid,
                    club_name,
                    team_id,
                    wage,
                    start,
                    end,
                    True,
                    squad_status_raw,
                    event_count,
                    (),
                    None,
                    unknown,
                )
            base, count = clause_base
            clauses, _bytes_after_entries = self._read_clauses(game_db, base, count)
            # The fallback accepts only a table that ends exactly at the tail start.
            self.clause_tables_ending_at_tail_count += 1
        self.clause_table_count += 1
        head = self._read_head(game_db, base)
        contract_type_raw: int | None = None
        if head is not None:
            self.head_ok_count += 1
            contract_type_raw, money_a, money_b, money_c = head
            unknown["money_a"] = money_a
            unknown["money_b"] = money_b
            unknown["money_c"] = money_c
        return (
            club_uid,
            club_name,
            team_id,
            wage,
            start,
            end,
            True,
            squad_status_raw,
            event_count,
            clauses,
            contract_type_raw,
            unknown,
        )

    def _find_chain_records(
        self,
        game_db: bytes,
        record_offset: int,
        record_window_end: int,
        is_last_record: bool,
        pindex: int,
    ) -> list[_ChainRecordTuple] | None:
        """Every chain record whose selector matches pindex, in file order, or None when
        there is none. Searches the tag inline (no intermediate hit list) and advances past
        each hit by 4 bytes, since the tag cannot overlap itself.
        """
        search_start = record_offset + self.chain_window_start_offset
        search_start = max(search_start, 0)
        search_end = (
            record_window_end
            if is_last_record
            else record_window_end + self.chain_window_end_offset
        )
        search_end = max(search_end, search_start)
        selector_bytes = _U32.pack(pindex + 1)
        selector_offset = self.selector_offset
        game_db_length = len(game_db)
        find = game_db.find
        startswith = game_db.startswith
        tag = self.tag
        records: list[_ChainRecordTuple] | None = None
        hit = find(tag, search_start, search_end)
        while hit >= 0:
            selector_at = hit + selector_offset
            if selector_at + 4 <= game_db_length and startswith(selector_bytes, selector_at):
                decoded_record = self.decode_chain_record(game_db, hit)
                if records is None:
                    records = [decoded_record]
                else:
                    records.append(decoded_record)
            hit = find(tag, hit + 4, search_end)
        return records

    def _find_fallback_dates(
        self, game_db: bytes, record_offset: int, record_window_end: int
    ) -> tuple[date | None, date | None]:
        """(start, end) with the latest end among valid pairs, or (None, None).

        `record_window_end` is already `len(game_db)` for the last player (see
        `player_scan.window_end`), so no separate last-record case is needed here.
        """
        search_start = record_offset + self.fallback_start_from_record
        limit = record_window_end - self.fallback_end_margin
        limit = max(limit, search_start)
        game_db_length = len(game_db)
        find_end = min(game_db_length, limit)
        gate_length = self.fallback_gate_length
        nonzero_offset = self.fallback_nonzero_offset
        nonzero_length = self.fallback_nonzero_length
        zero_needle = self.fallback_zero_needle
        end_date_offset = self.fallback_end_date_offset
        start_date_offset = self.fallback_start_date_offset
        find = game_db.find
        startswith = game_db.startswith
        best_start: date | None = None
        best_end: date | None = None
        hit = find(_FOUR_FF, search_start, find_end)
        while hit >= 0:
            dates_offset = hit + 8  # "j" in ContractLayout's docstring
            nonzero_start = dates_offset + nonzero_offset
            if (
                dates_offset + gate_length <= limit
                and nonzero_start + nonzero_length <= game_db_length
                and not startswith(zero_needle, nonzero_start)
            ):
                raw_end: int = _U32.unpack_from(game_db, dates_offset + end_date_offset)[0]
                end_date = self._cached_date(game_db, raw_end, dates_offset + end_date_offset)
                if end_date is not None and (best_end is None or end_date > best_end):
                    raw_start: int = _U32.unpack_from(game_db, dates_offset + start_date_offset)[0]
                    start_date = self._cached_date(
                        game_db, raw_start, dates_offset + start_date_offset
                    )
                    if start_date is not None and end_date > start_date:
                        best_end = end_date
                        best_start = start_date
            hit = find(_FOUR_FF, hit + 1, find_end)
        return best_start, best_end

    def decode(
        self,
        game_db: bytes,
        record_offset: int,
        record_window_end: int,
        is_last_record: bool,
        pindex: int,
        player_uid: int,
        player_name: str | None,
        player_club_uid: int | None,
    ) -> tuple[Contract | None, bool | None, int | None, str | None]:
        """Assemble one player's contract from their chain records and, when needed, the
        fallback reader.

        `player_club_uid` is the uid of the club fielding the player's own registered team,
        already resolved by `PlayerDecoder`, so this method never re-resolves it.

        Returns (contract, on_loan, loan_parent_club_uid, loan_parent_club_name); the last
        three are also carried inside contract when it is not None.

        Raises:
            CorruptSaveError: A chain record's team id or wage runs past the end of game_db.
        """
        chain_records = self._find_chain_records(
            game_db, record_offset, record_window_end, is_last_record, pindex
        )

        any_tail_parsed = False
        if chain_records is not None:
            for candidate_record in chain_records:
                if candidate_record[6]:
                    any_tail_parsed = True
                    break

        fallback_start: date | None = None
        fallback_end: date | None = None
        if chain_records is None or not any_tail_parsed:
            fallback_start, fallback_end = self._find_fallback_dates(
                game_db, record_offset, record_window_end
            )

        if chain_records is None and fallback_start is None and fallback_end is None:
            return None, None, None, None

        clock = self.clock

        if chain_records is None:
            wage: int | None = None
            start = fallback_start
            live_club_uid: int | None = None
            live_club_name: str | None = None
            live_team_id: int | None = None
            squad_status: CodedValue[SquadStatus] | None = None
            event_count: int | None = None
            contract_type: CodedValue[ContractType] | None = None
            clauses: tuple[Clause, ...] = ()
            unknown: FrozenMapping[str, int] = self.empty_unknown
            on_loan: bool | None = None
            loan_parent_club_uid: int | None = None
            loan_parent_club_name: str | None = None
            chain: tuple[ContractChainEntry, ...] = ()
            chain_club_uids: tuple[int | None, ...] = ()
            chain_club_names: tuple[str | None, ...] = ()
            tailed_chain_club_uids: tuple[int, ...] = ()
            if fallback_end is not None and fallback_end >= clock:
                end, end_source = fallback_end, ContractEndSource.FALLBACK
            else:
                end, end_source = None, ContractEndSource.NONE
        else:
            self.players_with_chain_count += 1
            first_record = chain_records[0]
            first_club_uid = first_record[0]
            first_club_name = first_record[1]
            wage = first_record[3]
            start = first_record[4]

            if len(chain_records) == 1:
                live_record = chain_records[0]
            else:
                live_record = None
                best_end: date | None = None
                for candidate_record in chain_records:
                    candidate_end = candidate_record[5]
                    if (
                        candidate_record[6]
                        and candidate_end is not None
                        and (best_end is None or candidate_end > best_end)
                    ):
                        live_record = candidate_record
                        best_end = candidate_end
                if live_record is None:
                    live_record = chain_records[-1]

            (
                live_club_uid,
                live_club_name,
                live_team_id,
                _live_wage,
                _live_start,
                live_end,
                live_has_tail,
                live_squad_status_raw,
                live_event_count,
                live_clauses,
                live_contract_type_raw,
                live_unknown,
            ) = live_record

            if live_end is not None:
                end, end_source = live_end, ContractEndSource.TAIL
            elif not any_tail_parsed and fallback_end is not None and fallback_end >= clock:
                end, end_source = fallback_end, ContractEndSource.FALLBACK
            else:
                end, end_source = None, ContractEndSource.NONE

            if live_has_tail:
                # A tail-bearing record's tail fields are never None; see decode_chain_record.
                squad_status = self._cached_squad_status(cast(int, live_squad_status_raw))
                event_count = live_event_count
                clauses = live_clauses
                contract_type = (
                    self._cached_contract_type(live_contract_type_raw)
                    if live_contract_type_raw is not None
                    else None
                )
                unknown = FrozenMapping(live_unknown) if live_unknown else self.empty_unknown
            else:
                squad_status = None
                event_count = None
                contract_type = None
                clauses = ()
                unknown = self.empty_unknown

            on_loan = None
            loan_parent_club_uid = None
            loan_parent_club_name = None
            if player_club_uid is not None and first_club_uid is not None:
                on_loan = player_club_uid != first_club_uid
                if on_loan:
                    loan_parent_club_uid = first_club_uid
                    loan_parent_club_name = first_club_name

            if len(chain_records) == 1:
                only_record = chain_records[0]
                chain = (ContractChainEntry(*only_record[:7]),)
                chain_club_uids = (only_record[0],)
                chain_club_names = (only_record[1],)
                tailed_chain_club_uids = (
                    (only_record[0],) if only_record[6] and only_record[0] is not None else ()
                )
            else:
                entries: list[ContractChainEntry] = []
                club_uids: list[int | None] = []
                club_names: list[str | None] = []
                tailed_uids: list[int] = []
                for record in chain_records:
                    club_uids.append(record[0])
                    club_names.append(record[1])
                    if record[6] and record[0] is not None:
                        tailed_uids.append(record[0])
                    entries.append(ContractChainEntry(*record[:7]))
                chain = tuple(entries)
                chain_club_uids = tuple(club_uids)
                chain_club_names = tuple(club_names)
                tailed_chain_club_uids = tuple(tailed_uids)

        contract = Contract(
            player_uid,
            player_name,
            live_club_uid,
            live_club_name,
            live_team_id,
            wage,
            start,
            end,
            end_source,
            squad_status,
            contract_type,
            clauses,
            on_loan,
            loan_parent_club_uid,
            loan_parent_club_name,
            event_count,
            chain,
            chain_club_uids,
            chain_club_names,
            tailed_chain_club_uids,
            unknown,
        )
        return contract, on_loan, loan_parent_club_uid, loan_parent_club_name


def build_contract_decoder(
    layout: ContractLayout, club_index: ClubIndex, clock: date, file_name: str
) -> ContractDecoder:
    """Build the per-save contract decoder from the save's layout, its ClubIndex and clock.

    Raises:
        ValueError: A layout-derived Struct or needle would be inconsistent: overlapping
            fields, fields not laid out in the order they are unpacked, a clause entry
            whose size does not match clause_entry_bytes or clause_step_bytes, clause entries
            that do not end where empty bonus lists start, a clause FF run, zero run and
            count byte that are not contiguous, a team id that leaves no room for zero bytes
            in the clause marker, a bonus list count or flag width other than 1, 2 or 4, a
            bonus item prefix longer than its item, a tail sentinel word that does not
            immediately follow the sentinel byte, or a fallback_nonzero_length below 1.
    """
    club_by_team_id: dict[int, tuple[int | None, str | None]] = {}
    for team_id, (club_uid, _slot) in club_index.team_to_club.items():
        club = club_index.club_by_uid.get(club_uid)
        club_by_team_id[team_id] = (club_uid, club.name if club is not None else None)

    team_wage_struct, team_wage_struct_offset = _build_team_wage_struct(layout)
    head_struct, head_struct_offset = _build_head_struct(layout)
    clause_entry_struct = _build_clause_entry_struct(layout)
    clause_structs = _build_clause_structs(layout, clause_entry_struct)
    clause_prefixes = _build_clause_prefixes(layout)
    team_marker_zero_run = _build_team_marker_zero_run(layout)
    tail_signature, tail_signature_offset = _build_tail_signature(layout)

    return ContractDecoder(
        club_by_team_id=club_by_team_id,
        clock=clock,
        file_name=file_name,
        tag=layout.tag,
        chain_window_start_offset=layout.chain_window_start_offset,
        chain_window_end_offset=layout.chain_window_end_offset,
        selector_offset=layout.selector_offset,
        team_wage_struct=team_wage_struct,
        team_wage_struct_offset=team_wage_struct_offset,
        start_offset=layout.start_offset,
        tail_base_offset=layout.tail_base_offset,
        tail_step_bytes=layout.tail_step_bytes,
        tail_max_event_count=layout.tail_max_event_count,
        tail_signature=tail_signature,
        tail_signature_offset=tail_signature_offset,
        tail_event_count_offset=layout.tail_event_count_offset,
        tail_end_offset=layout.tail_end_offset,
        tail_struct=_build_tail_struct(layout),
        clause_step_bytes=layout.clause_step_bytes,
        clause_max_count=layout.clause_max_count,
        clause_ff_offset=layout.clause_ff_offset,
        clause_count_offset=layout.clause_count_offset,
        clause_entries_offset=layout.clause_entries_offset,
        clause_prefixes=clause_prefixes,
        clause_structs=clause_structs,
        clause_empty_lists=bytes(_empty_bonus_lists_size(layout)),
        clause_entry_bytes=layout.clause_entry_bytes,
        clause_zero_offset=layout.clause_zero_offset,
        clause_count_needles=tuple(prefix[layout.clause_ff_count :] for prefix in clause_prefixes),
        clause_ff_run=b"\xff" * layout.clause_ff_count,
        clause_team_marker_id_ff=b"\xff" * layout.clause_team_marker_id_bytes,
        clause_team_marker_zero_run=team_marker_zero_run,
        clause_competition_count_struct=_build_unsigned_struct(
            layout.clause_competition_count_bytes, "clause_competition_count_bytes"
        ),
        clause_competition_item_bytes=layout.clause_competition_item_bytes,
        clause_competition_item_prefix=_check_item_prefix(
            layout.clause_competition_item_prefix,
            layout.clause_competition_item_bytes,
            "clause_competition_item_prefix",
            "clause_competition_item_bytes",
        ),
        clause_competition_max_count=layout.clause_competition_max_count,
        clause_award_flag_struct=_build_unsigned_struct(
            layout.clause_award_flag_bytes, "clause_award_flag_bytes"
        ),
        clause_award_count_struct=_build_unsigned_struct(
            layout.clause_award_count_bytes, "clause_award_count_bytes"
        ),
        clause_award_item_bytes=layout.clause_award_item_bytes,
        clause_award_item_prefix=_check_item_prefix(
            layout.clause_award_item_prefix,
            layout.clause_award_item_bytes,
            "clause_award_item_prefix",
            "clause_award_item_bytes",
        ),
        clause_award_max_count=layout.clause_award_max_count,
        clause_trailer=bytes(layout.clause_trailer_bytes),
        head_struct=head_struct,
        head_struct_offset=head_struct_offset,
        head_gate_value=layout.head_gate_value,
        fallback_start_from_record=layout.fallback_start_from_record,
        fallback_end_margin=layout.fallback_end_margin,
        fallback_gate_length=layout.fallback_gate_length,
        fallback_nonzero_offset=layout.fallback_nonzero_offset,
        fallback_nonzero_length=layout.fallback_nonzero_length,
        fallback_zero_needle=_build_fallback_zero_needle(layout),
        fallback_end_date_offset=layout.fallback_end_date_offset,
        fallback_start_date_offset=layout.fallback_start_date_offset,
        empty_unknown=FrozenMapping({}),
    )
