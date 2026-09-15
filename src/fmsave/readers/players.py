"""Player records in `game_db`: identity, ability, reputation, positions and attributes.

Player records are found by two scans: a fast marker anchor, and a slower completeness pass
over the region after the name pools that catches records the anchor scan misses. Results
from both passes are merged in ascending record-offset order into a private index. Decoding
is done by a `PlayerDecoder` built once per `players()` call from the save's layout and its
`ClubIndex`, so a single record never repeats a layout lookup or a club join.
"""

from __future__ import annotations

import calendar
import functools
import re
import struct
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from fmsave._errors import CorruptSaveError
from fmsave._layouts import PlayerRecordLayout
from fmsave._scan import DAY_OF_YEAR_MASK, EARLIEST_GAME_YEAR, LATEST_GAME_YEAR
from fmsave.models.common import TransferValueState
from fmsave.models.players import Ability, Attributes, Player, Positions, Reputation
from fmsave.readers._common import MISSING_REFERENCE, layout_mismatch, section_label
from fmsave.readers.clubs import ClubIndex

RECORD_OFFSET_TYPECODE = "Q"
PINDEX_TYPECODE = "I"
UID_TYPECODE = "I"
PLAYER_RECORDS_CACHE_KEY = "player_records"

_TeamFields = tuple[
    int, "str | None", "str | None", "int | None", "int | None", "int | None", "int | None", int
]
type _Candidate = tuple[int, int, int]  # (record_offset, pindex, uid)

_DATE_CACHE_MISS = object()


def _new_date_cache() -> dict[int, date | None]:
    return {}


def _record_overrun(file_name: str) -> CorruptSaveError:
    return CorruptSaveError(
        f"{section_label(file_name)}: a player record runs past the end of the section"
    )


@dataclass(frozen=True, slots=True, repr=False)
class PlayerRecords:
    """Every accepted player record's offset, pindex and uid, in ascending record offset.

    Never mutate the mappings: this index is cached and shared by every reader of a save.

    Attributes:
        record_offsets: Each record's start offset in `game_db`, ascending.
        pindexes: Each record's pindex, aligned with record_offsets.
        uids: Each record's uid, aligned with record_offsets.
        markerless_count: How many records were found only by the completeness pass.
        position_by_pindex: Position in the arrays above for each pindex.
        position_by_uid: Position in the arrays above for each uid.
        layout: The layout the scan used, for building a PlayerDecoder.
    """

    record_offsets: array[int]
    pindexes: array[int]
    uids: array[int]
    markerless_count: int
    position_by_pindex: Mapping[int, int]
    position_by_uid: Mapping[int, int]
    layout: PlayerRecordLayout

    def __repr__(self) -> str:
        return f"<fmsave PlayerRecords {len(self.record_offsets)} records>"


def locate_player_records(
    game_db: bytes, name_pools_end: int, layout: PlayerRecordLayout, file_name: str
) -> PlayerRecords:
    """Scan `game_db` for player records with both the marker and completeness passes.

    Raises:
        ReaderCheckError: No player records were found, or a pindex or uid appears in two
            records.
        CorruptSaveError: An accepted record runs past the end of `game_db`.
    """
    uid_layout = _uid_layout(layout)
    header_layout = _header_layout(layout)
    pattern = _completeness_pattern(
        layout.rating_range, layout.ratings_count, layout.attribute_range, layout.attribute_count
    )
    marker_candidates = _scan_marker_candidates(
        game_db, layout, uid_layout, header_layout, pattern, file_name
    )
    marker_offsets = {candidate[0] for candidate in marker_candidates}
    completeness_candidates = _scan_completeness_candidates(
        game_db,
        name_pools_end,
        layout,
        uid_layout,
        header_layout,
        pattern,
        marker_offsets,
        file_name,
    )
    merged = marker_candidates + completeness_candidates
    merged.sort(key=lambda candidate: candidate[0])
    if not merged:
        raise layout_mismatch(file_name, "no player records found")
    _reject_repeated_keys(merged, file_name)
    record_offsets = array(RECORD_OFFSET_TYPECODE, (candidate[0] for candidate in merged))
    pindexes = array(PINDEX_TYPECODE, (candidate[1] for candidate in merged))
    uids = array(UID_TYPECODE, (candidate[2] for candidate in merged))
    position_by_pindex = {pindex: position for position, pindex in enumerate(pindexes)}
    position_by_uid = {uid: position for position, uid in enumerate(uids)}
    return PlayerRecords(
        record_offsets=record_offsets,
        pindexes=pindexes,
        uids=uids,
        markerless_count=len(completeness_candidates),
        position_by_pindex=position_by_pindex,
        position_by_uid=position_by_uid,
        layout=layout,
    )


def window_end(records: PlayerRecords, position: int, game_db_length: int) -> int:
    """The offset ending the window of the record at position: the next record's start, or
    the length of `game_db` for the last record.
    """
    next_position = position + 1
    if next_position < len(records.record_offsets):
        return records.record_offsets[next_position]
    return game_db_length


def _reject_repeated_keys(candidates: Sequence[_Candidate], file_name: str) -> None:
    seen_pindexes: set[int] = set()
    seen_uids: set[int] = set()
    for _, pindex, uid in candidates:
        if pindex in seen_pindexes:
            raise layout_mismatch(file_name, f"pindex {pindex} appears in two player records")
        if uid in seen_uids:
            raise layout_mismatch(file_name, f"player uid {uid} appears in two player records")
        seen_pindexes.add(pindex)
        seen_uids.add(uid)


def _scan_marker_candidates(
    game_db: bytes,
    layout: PlayerRecordLayout,
    uid_layout: _UidLayout,
    header_layout: _HeaderLayout,
    pattern: re.Pattern[bytes],
    file_name: str,
) -> list[_Candidate]:
    """Every record found by the marker anchor, in the order the anchor is found."""
    buffer_length = len(game_db)
    find_marker = game_db.find
    marker = layout.marker
    marker_offset = layout.marker_offset
    decode_extent = layout.decode_extent
    candidates: list[_Candidate] = []
    marker_hit = find_marker(marker, 0)
    while marker_hit >= 0:
        record_offset = marker_hit - marker_offset
        accepted = _accept_candidate(
            game_db,
            record_offset,
            layout,
            buffer_length,
            uid_layout,
            header_layout,
            pattern,
            check_pattern=True,
        )
        if accepted is not None:
            if record_offset + decode_extent > buffer_length:
                raise _record_overrun(file_name)
            candidates.append((record_offset, *accepted))
        marker_hit = find_marker(marker, marker_hit + 1)
    return candidates


def _scan_completeness_candidates(
    game_db: bytes,
    name_pools_end: int,
    layout: PlayerRecordLayout,
    uid_layout: _UidLayout,
    header_layout: _HeaderLayout,
    pattern: re.Pattern[bytes],
    marker_offsets: set[int],
    file_name: str,
) -> list[_Candidate]:
    """Every record found by the 69-byte ratings-then-attributes pattern, offset ascending.

    Measured on the real corpus, a maximal-run pre-filter (a coarser regex finding runs of
    ratings_count + attribute_count or more bytes in the wider of the two ranges, then the
    exact pattern only inside each run) does not pay for itself: real runs are almost always
    exactly minimum length, so the coarser regex costs about as much as the exact one and
    the second pass adds nothing. A single bounded finditer, skipping offsets the marker scan
    already found before paying for a header-struct read, is faster in practice.
    """
    buffer_length = len(game_db)
    decode_extent = layout.decode_extent
    ratings_offset = layout.ratings_offset
    candidates: list[_Candidate] = []
    for match in pattern.finditer(game_db, name_pools_end):
        record_offset = match.start() - ratings_offset
        if record_offset in marker_offsets:
            continue
        accepted = _accept_candidate(
            game_db,
            record_offset,
            layout,
            buffer_length,
            uid_layout,
            header_layout,
            pattern,
            check_pattern=False,
        )
        if accepted is not None:
            if record_offset + decode_extent > buffer_length:
                raise _record_overrun(file_name)
            candidates.append((record_offset, *accepted))
    return candidates


def _accept_candidate(
    game_db: bytes,
    record_offset: int,
    layout: PlayerRecordLayout,
    buffer_length: int,
    uid_layout: _UidLayout,
    header_layout: _HeaderLayout,
    pattern: re.Pattern[bytes],
    *,
    check_pattern: bool,
) -> tuple[int, int] | None:
    """Check one candidate; return (pindex, uid) when every acceptance check holds, else None.

    check_pattern is False for a completeness-pass candidate, whose ratings and attribute
    bytes the regex has already validated at this exact position. The doubled-uid check runs
    first, from its own small struct, because almost every false marker hit fails it; the
    wider header struct is only read once that check passes.
    """
    header_absolute_start = record_offset + header_layout.start_offset
    accept_checks_end = record_offset + layout.attributes_offset + layout.attribute_count
    if header_absolute_start < 0 or accept_checks_end > buffer_length:
        return None
    uid_values = uid_layout.struct_object.unpack_from(
        game_db, record_offset + uid_layout.start_offset
    )
    uid: int = uid_values[uid_layout.uid_index]
    uid_copy: int = uid_values[uid_layout.uid_copy_index]
    if uid != uid_copy or uid == 0 or uid == MISSING_REFERENCE:
        return None
    header_values = header_layout.struct_object.unpack_from(game_db, header_absolute_start)
    current_ability: int = header_values[header_layout.current_ability_index]
    lowest_ability, highest_ability = layout.current_ability_range
    if not lowest_ability <= current_ability <= highest_ability:
        return None
    potential_ability: int = header_values[header_layout.potential_ability_index]
    lowest_potential, highest_potential = layout.potential_ability_range
    if not lowest_potential <= potential_ability <= highest_potential:
        return None
    reputation_bucket: int = header_values[header_layout.reputation_bucket_index]
    lowest_bucket, highest_bucket = layout.reputation_bucket_range
    if not lowest_bucket <= reputation_bucket <= highest_bucket:
        return None
    if check_pattern and pattern.match(game_db, record_offset + layout.ratings_offset) is None:
        return None
    pindex: int = header_values[header_layout.pindex_index]
    return pindex, uid


def _byte_class(value_range: tuple[int, int]) -> bytes:
    lowest, highest = value_range
    return b"[" + re.escape(bytes((lowest,))) + b"-" + re.escape(bytes((highest,))) + b"]"


@functools.cache
def _completeness_pattern(
    rating_range: tuple[int, int],
    ratings_count: int,
    attribute_range: tuple[int, int],
    attribute_count: int,
) -> re.Pattern[bytes]:
    """The compiled pattern for the completeness pass; cached so it is built only once."""
    rating_class = _byte_class(rating_range)
    attribute_class = _byte_class(attribute_range)
    pattern = (
        rating_class
        + b"{"
        + str(ratings_count).encode("ascii")
        + b"}"
        + attribute_class
        + b"{"
        + str(attribute_count).encode("ascii")
        + b"}"
    )
    return re.compile(pattern)


_SCALE_TABLE = bytes(max(1, (raw_value + 2) // 5) for raw_value in range(256))


def _derived_positions(
    ratings: bytes, position_codes: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(natural_positions, accomplished_positions): best rating first, ties in array order."""
    qualifying = [(rating, index) for index, rating in enumerate(ratings) if rating >= 15]
    qualifying.sort(key=lambda item: -item[0])
    natural_positions = tuple(position_codes[index] for rating, index in qualifying if rating >= 18)
    accomplished_positions = tuple(
        position_codes[index] for rating, index in qualifying if rating < 18
    )
    return natural_positions, accomplished_positions


def _transfer_value(raw_value: int, placeholder: int) -> tuple[int | None, TransferValueState]:
    if raw_value == MISSING_REFERENCE:
        return None, TransferValueState.UNSET
    if raw_value == placeholder:
        return None, TransferValueState.PLACEHOLDER
    if raw_value == 0:
        return None, TransferValueState.ZERO
    return raw_value, TransferValueState.OK


def _decode_packed_date(raw_date: int) -> date | None:
    """Decode a 4-byte game date read as one little-endian u32 (day/time low, year high)."""
    packed = raw_date & 0xFFFF
    year = raw_date >> 16
    day_of_year = packed & DAY_OF_YEAR_MASK
    if not EARLIEST_GAME_YEAR <= year <= LATEST_GAME_YEAR:
        return None
    days_in_year = 366 if calendar.isleap(year) else 365
    if not 1 <= day_of_year <= days_in_year:
        return None
    return date(year, 1, 1) + timedelta(days=day_of_year - 1)


@dataclass(frozen=True, slots=True)
class _UidLayout:
    """A small struct covering only uid_offset and uid_copy_offset.

    Most marker-anchor hits are false positives, and almost all of them fail the doubled-uid
    check; reading just these two fields first, before the wider header struct, skips
    unpacking the other eight header fields for a candidate that is about to be rejected.
    """

    struct_object: struct.Struct
    start_offset: int
    uid_index: int
    uid_copy_index: int


@dataclass(frozen=True, slots=True)
class _HeaderLayout:
    """A struct spanning pindex_offset..team_id_offset+4, and each field's tuple index."""

    struct_object: struct.Struct
    start_offset: int
    pindex_index: int
    uid_index: int
    uid_copy_index: int
    home_reputation_index: int
    current_reputation_index: int
    world_reputation_index: int
    current_ability_index: int
    potential_ability_index: int
    reputation_bucket_index: int
    team_id_index: int


@dataclass(frozen=True, slots=True)
class _TailLayout:
    """A struct spanning transfer_value_offset..height_offset+1, and each field's index."""

    struct_object: struct.Struct
    start_offset: int
    transfer_value_index: int
    club_join_date_index: int
    match_sharpness_index: int
    condition_index: int
    height_index: int


_UID_FIELD_SPECS: tuple[tuple[str, str], ...] = (
    ("uid_offset", "I"),
    ("uid_copy_offset", "I"),
)

_HEADER_FIELD_SPECS: tuple[tuple[str, str], ...] = (
    ("pindex_offset", "I"),
    ("uid_offset", "I"),
    ("uid_copy_offset", "I"),
    ("home_reputation_offset", "H"),
    ("current_reputation_offset", "H"),
    ("world_reputation_offset", "H"),
    ("current_ability_offset", "H"),
    ("potential_ability_offset", "h"),
    ("reputation_bucket_offset", "B"),
    ("team_id_offset", "I"),
)

_TAIL_FIELD_SPECS: tuple[tuple[str, str], ...] = (
    ("transfer_value_offset", "I"),
    ("club_join_date_offset", "I"),
    ("match_sharpness_offset", "H"),
    ("condition_offset", "H"),
    ("height_offset", "B"),
)


def _indexed_struct(
    layout: PlayerRecordLayout, field_specs: tuple[tuple[str, str], ...]
) -> tuple[struct.Struct, int, dict[str, int]]:
    """One struct spanning every named offset in field_specs, gaps padded, offsets ascending."""
    fields = sorted(
        ((getattr(layout, attr_name), code, attr_name) for attr_name, code in field_specs),
        key=lambda described_field: described_field[0],
    )
    start_offset = fields[0][0]
    format_codes: list[str] = []
    cursor = start_offset
    index_by_field: dict[str, int] = {}
    for position, (offset, code, attr_name) in enumerate(fields):
        gap = offset - cursor
        if gap:
            format_codes.append(f"{gap}x")
        format_codes.append(code)
        cursor = offset + struct.calcsize(code)
        index_by_field[attr_name] = position
    return struct.Struct("<" + "".join(format_codes)), start_offset, index_by_field


@functools.cache
def _uid_layout(layout: PlayerRecordLayout) -> _UidLayout:
    uid_struct, start_offset, index_by_field = _indexed_struct(layout, _UID_FIELD_SPECS)
    return _UidLayout(
        struct_object=uid_struct,
        start_offset=start_offset,
        uid_index=index_by_field["uid_offset"],
        uid_copy_index=index_by_field["uid_copy_offset"],
    )


@functools.cache
def _header_layout(layout: PlayerRecordLayout) -> _HeaderLayout:
    header_struct, start_offset, index_by_field = _indexed_struct(layout, _HEADER_FIELD_SPECS)
    return _HeaderLayout(
        struct_object=header_struct,
        start_offset=start_offset,
        pindex_index=index_by_field["pindex_offset"],
        uid_index=index_by_field["uid_offset"],
        uid_copy_index=index_by_field["uid_copy_offset"],
        home_reputation_index=index_by_field["home_reputation_offset"],
        current_reputation_index=index_by_field["current_reputation_offset"],
        world_reputation_index=index_by_field["world_reputation_offset"],
        current_ability_index=index_by_field["current_ability_offset"],
        potential_ability_index=index_by_field["potential_ability_offset"],
        reputation_bucket_index=index_by_field["reputation_bucket_offset"],
        team_id_index=index_by_field["team_id_offset"],
    )


@functools.cache
def _tail_layout(layout: PlayerRecordLayout) -> _TailLayout:
    tail_struct, start_offset, index_by_field = _indexed_struct(layout, _TAIL_FIELD_SPECS)
    return _TailLayout(
        struct_object=tail_struct,
        start_offset=start_offset,
        transfer_value_index=index_by_field["transfer_value_offset"],
        club_join_date_index=index_by_field["club_join_date_offset"],
        match_sharpness_index=index_by_field["match_sharpness_offset"],
        condition_index=index_by_field["condition_offset"],
        height_index=index_by_field["height_offset"],
    )


@functools.cache
def _attribute_struct_without_feet(layout: PlayerRecordLayout) -> struct.Struct:
    """Unpacks the 54-byte attribute slice, skipping the two foot-strength bytes."""
    first_index, second_index = sorted((layout.left_foot_index, layout.right_foot_index))
    before_count = first_index
    between_count = second_index - first_index - 1
    after_count = layout.attribute_count - second_index - 1
    return struct.Struct(f"<{before_count}Bx{between_count}Bx{after_count}B")


@dataclass(slots=True)
class PlayerDecoder:
    """Decodes player records for one save; built once per `players()` call.

    Holds every layout- and club-derived value a record decode needs, so a single record
    never repeats a layout lookup, a team-to-club join, or a date decode already seen.
    """

    layout: PlayerRecordLayout
    header_layout: _HeaderLayout
    tail_layout: _TailLayout
    attribute_struct: struct.Struct
    scale_table: bytes
    team_fields: Mapping[int, _TeamFields]
    date_cache: dict[int, date | None] = field(default_factory=_new_date_cache)

    def decode(self, game_db: bytes, record_offset: int) -> Player:
        """Decode one player record's public fields; person fields stay empty until a later
        task.
        """
        layout = self.layout
        header_layout = self.header_layout
        header_values = header_layout.struct_object.unpack_from(
            game_db, record_offset + header_layout.start_offset
        )
        uid: int = header_values[header_layout.uid_index]
        home_reputation: int = header_values[header_layout.home_reputation_index]
        current_reputation: int = header_values[header_layout.current_reputation_index]
        world_reputation: int = header_values[header_layout.world_reputation_index]
        current_ability: int = header_values[header_layout.current_ability_index]
        potential_ability_raw: int = header_values[header_layout.potential_ability_index]
        reputation_bucket: int = header_values[header_layout.reputation_bucket_index]
        stored_team_id: int = header_values[header_layout.team_id_index]

        reputation = Reputation(
            reputation_bucket, home_reputation, current_reputation, world_reputation
        )
        if potential_ability_raw < 0:
            ability = Ability(current_ability, None, potential_ability_raw)
        else:
            ability = Ability(current_ability, potential_ability_raw, None)

        team_id = None if stored_team_id == MISSING_REFERENCE else stored_team_id
        team_fields = self.team_fields.get(team_id) if team_id is not None else None
        if team_fields is None:
            club_uid = club_name = club_short_name = None
            club_nation_id = club_fa_nation_id = None
            club_reputation = club_last_league_position = None
            team_slot = None
        else:
            (
                club_uid,
                club_name,
                club_short_name,
                club_nation_id,
                club_fa_nation_id,
                club_reputation,
                club_last_league_position,
                team_slot,
            ) = team_fields

        ratings_start = record_offset + layout.ratings_offset
        ratings = game_db[ratings_start : ratings_start + layout.ratings_count]
        positions = Positions(*ratings)
        natural_positions, accomplished_positions = _derived_positions(
            ratings, layout.position_codes
        )

        attributes_start = record_offset + layout.attributes_offset
        raw_attribute_bytes = game_db[attributes_start : attributes_start + layout.attribute_count]
        scaled_attribute_bytes = raw_attribute_bytes.translate(self.scale_table)
        raw_attributes = Attributes(*self.attribute_struct.unpack(raw_attribute_bytes))
        attributes = Attributes(*self.attribute_struct.unpack(scaled_attribute_bytes))
        raw_left_foot = raw_attribute_bytes[layout.left_foot_index]
        raw_right_foot = raw_attribute_bytes[layout.right_foot_index]
        left_foot = scaled_attribute_bytes[layout.left_foot_index]
        right_foot = scaled_attribute_bytes[layout.right_foot_index]

        tail_layout = self.tail_layout
        tail_values = tail_layout.struct_object.unpack_from(
            game_db, record_offset + tail_layout.start_offset
        )
        transfer_value_raw: int = tail_values[tail_layout.transfer_value_index]
        club_join_date_raw: int = tail_values[tail_layout.club_join_date_index]
        match_sharpness: int = tail_values[tail_layout.match_sharpness_index]
        condition: int = tail_values[tail_layout.condition_index]
        height_cm: int = tail_values[tail_layout.height_index]

        transfer_value, transfer_value_state = _transfer_value(
            transfer_value_raw, layout.transfer_value_placeholder
        )
        club_join_date = self._cached_date(club_join_date_raw)

        # Positional, matching Player's field order in models/players.py. Person fields
        # (name..nation_id, their tuples, personality and traits) stay empty until Task 7.
        return Player(
            uid,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            (),
            (),
            (),
            height_cm,
            ability,
            reputation,
            club_uid,
            club_name,
            club_short_name,
            club_nation_id,
            club_fa_nation_id,
            club_reputation,
            club_last_league_position,
            team_id,
            team_slot,
            club_join_date,
            natural_positions,
            accomplished_positions,
            None,
            attributes,
            raw_attributes,
            left_foot,
            right_foot,
            raw_left_foot,
            raw_right_foot,
            positions,
            transfer_value,
            transfer_value_state,
            condition,
            match_sharpness,
            (),
            None,
        )

    def _cached_date(self, raw_date: int) -> date | None:
        cache = self.date_cache
        cached = cache.get(raw_date, _DATE_CACHE_MISS)
        if cached is not _DATE_CACHE_MISS:
            return cached  # type: ignore[return-value]
        decoded = _decode_packed_date(raw_date)
        cache[raw_date] = decoded
        return decoded


def build_player_decoder(layout: PlayerRecordLayout, club_index: ClubIndex) -> PlayerDecoder:
    """Build the per-save decoder from the save's layout and its ClubIndex."""
    team_fields: dict[int, _TeamFields] = {}
    for team_id, (club_uid, team_slot) in club_index.team_to_club.items():
        club = club_index.club_by_uid[club_uid]
        team_fields[team_id] = (
            club_uid,
            club.name,
            club.short_name,
            club.nation_id,
            club.fa_nation_id,
            club.reputation,
            club.last_league_position,
            team_slot,
        )
    return PlayerDecoder(
        layout=layout,
        header_layout=_header_layout(layout),
        tail_layout=_tail_layout(layout),
        attribute_struct=_attribute_struct_without_feet(layout),
        scale_table=_SCALE_TABLE,
        team_fields=team_fields,
    )
