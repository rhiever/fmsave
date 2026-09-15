"""Player records in `game_db`: identity, ability, reputation, positions and attributes.

Player records are found by two scans: a fast marker anchor, and a slower completeness pass
over the region after the name pools that catches records the anchor scan misses. Results
from both passes are merged in ascending record-offset order into a private index;
`decode_player_record` then reads one record's public fields, joining its team id to a club
through the `ClubIndex`.
"""

from __future__ import annotations

import functools
import re
import struct
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fmsave._errors import ISSUES_URL, ReaderCheckError
from fmsave._layouts import FALLBACK_BUILD, PlayerRecordLayout, find_layout
from fmsave._scan import decode_date
from fmsave.models.common import TransferValueState
from fmsave.models.players import Ability, Attributes, Player, Positions, Reputation
from fmsave.readers._common import MISSING_REFERENCE
from fmsave.readers.clubs import ClubIndex

GAME_DB_SECTION = "game_db"
RECORD_OFFSET_TYPECODE = "Q"
PINDEX_TYPECODE = "I"
UID_TYPECODE = "I"
PLAYER_RECORDS_CACHE_KEY = "player_records"

_U16 = struct.Struct("<H")
_I16 = struct.Struct("<h")
_U32 = struct.Struct("<I")
_U16_TRIPLE = struct.Struct("<HHH")
_RATINGS = struct.Struct("<15B")
_RAW_ATTRIBUTES = struct.Struct("<54B")

# The record decode functions use the default (fallback) build's field layout: in M1, only
# one build is registered, so this is always the layout the locate functions use too.
_DEFAULT_RECORD_LAYOUT: PlayerRecordLayout = find_layout(
    PlayerRecordLayout, GAME_DB_SECTION, None, FALLBACK_BUILD
).layout

type _Candidate = tuple[int, int, int]  # (record_offset, pindex, uid)


def _section_label(file_name: str) -> str:
    return f"{file_name}: section {GAME_DB_SECTION!r}"


def _layout_mismatch(file_name: str, detail: str) -> ReaderCheckError:
    return ReaderCheckError(
        f"{_section_label(file_name)}: {detail}, so the save layout differs from what fmsave "
        f"expects. Please report it at {ISSUES_URL}"
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
    """

    record_offsets: array[int]
    pindexes: array[int]
    uids: array[int]
    markerless_count: int
    position_by_pindex: Mapping[int, int]
    position_by_uid: Mapping[int, int]

    def __repr__(self) -> str:
        return f"<fmsave PlayerRecords {len(self.record_offsets)} records>"


def locate_player_records(
    game_db: bytes, name_pools_end: int, layout: PlayerRecordLayout, file_name: str
) -> PlayerRecords:
    """Scan `game_db` for player records with both the marker and completeness passes.

    Raises:
        ReaderCheckError: No player records were found, or a uid appears in two records.
    """
    marker_candidates = _scan_marker_candidates(game_db, layout)
    marker_offsets = {candidate[0] for candidate in marker_candidates}
    completeness_pattern = _completeness_pattern(
        layout.rating_range, layout.ratings_count, layout.attribute_range, layout.attribute_count
    )
    completeness_candidates = [
        candidate
        for candidate in _scan_completeness_candidates(
            game_db, name_pools_end, layout, completeness_pattern
        )
        if candidate[0] not in marker_offsets
    ]
    merged = marker_candidates + completeness_candidates
    merged.sort(key=lambda candidate: candidate[0])
    if not merged:
        raise _layout_mismatch(file_name, "no player records found")
    _reject_repeated_uids(merged, file_name)
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
    )


def window_end(records: PlayerRecords, position: int, game_db_length: int) -> int:
    """The offset ending the window of the record at position: the next record's start, or
    the length of `game_db` for the last record.
    """
    next_position = position + 1
    if next_position < len(records.record_offsets):
        return records.record_offsets[next_position]
    return game_db_length


def _reject_repeated_uids(candidates: Sequence[_Candidate], file_name: str) -> None:
    seen_uids: set[int] = set()
    for _, _, uid in candidates:
        if uid in seen_uids:
            raise _layout_mismatch(file_name, f"player uid {uid} appears in two player records")
        seen_uids.add(uid)


def _scan_marker_candidates(game_db: bytes, layout: PlayerRecordLayout) -> list[_Candidate]:
    """Every record found by the marker anchor, in the order the anchor is found."""
    buffer_length = len(game_db)
    find_marker = game_db.find
    marker = layout.marker
    marker_offset = layout.marker_offset
    candidates: list[_Candidate] = []
    marker_hit = find_marker(marker, 0)
    while marker_hit >= 0:
        record_offset = marker_hit - marker_offset
        accepted = _accept_candidate(game_db, record_offset, layout, buffer_length)
        if accepted is not None:
            candidates.append((record_offset, *accepted))
        marker_hit = find_marker(marker, marker_hit + 1)
    return candidates


def _scan_completeness_candidates(
    game_db: bytes, name_pools_end: int, layout: PlayerRecordLayout, pattern: re.Pattern[bytes]
) -> list[_Candidate]:
    """Every record found by the 69-byte ratings-then-attributes pattern, in match order."""
    buffer_length = len(game_db)
    ratings_offset = layout.ratings_offset
    candidates: list[_Candidate] = []
    for match in pattern.finditer(game_db, name_pools_end):
        record_offset = match.start() - ratings_offset
        accepted = _accept_candidate(game_db, record_offset, layout, buffer_length)
        if accepted is not None:
            candidates.append((record_offset, *accepted))
    return candidates


def _accept_candidate(
    game_db: bytes, record_offset: int, layout: PlayerRecordLayout, buffer_length: int
) -> tuple[int, int] | None:
    """Check one candidate; return (pindex, uid) when every acceptance check holds, else None."""
    lowest_offset = record_offset + layout.pindex_offset
    attributes_end = record_offset + layout.attributes_offset + layout.attribute_count
    if lowest_offset < 0 or attributes_end > buffer_length:
        return None
    lowest_ability, highest_ability = layout.current_ability_range
    current_ability: int = _U16.unpack_from(game_db, record_offset + layout.current_ability_offset)[
        0
    ]
    if not lowest_ability <= current_ability <= highest_ability:
        return None
    lowest_potential, highest_potential = layout.potential_ability_range
    potential_ability: int = _I16.unpack_from(
        game_db, record_offset + layout.potential_ability_offset
    )[0]
    if not lowest_potential <= potential_ability <= highest_potential:
        return None
    lowest_bucket, highest_bucket = layout.reputation_bucket_range
    reputation_bucket = game_db[record_offset + layout.reputation_bucket_offset]
    if not lowest_bucket <= reputation_bucket <= highest_bucket:
        return None
    ratings_start = record_offset + layout.ratings_offset
    ratings = game_db[ratings_start : ratings_start + layout.ratings_count]
    lowest_rating, highest_rating = layout.rating_range
    if min(ratings) < lowest_rating or max(ratings) > highest_rating:
        return None
    attributes_start = record_offset + layout.attributes_offset
    raw_attributes = game_db[attributes_start:attributes_end]
    lowest_attribute, highest_attribute = layout.attribute_range
    if min(raw_attributes) < lowest_attribute or max(raw_attributes) > highest_attribute:
        return None
    uid: int = _U32.unpack_from(game_db, record_offset + layout.uid_offset)[0]
    uid_copy: int = _U32.unpack_from(game_db, record_offset + layout.uid_copy_offset)[0]
    if uid != uid_copy or uid == 0 or uid == MISSING_REFERENCE:
        return None
    pindex: int = _U32.unpack_from(game_db, record_offset + layout.pindex_offset)[0]
    return pindex, uid


def _byte_class(value_range: tuple[int, int]) -> bytes:
    lowest, highest = value_range
    return b"[" + bytes((lowest,)) + b"-" + bytes((highest,)) + b"]"


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


def _scaled_attribute(raw_value: int) -> int:
    return max(1, (raw_value + 2) // 5)


def _derived_positions(
    ratings: tuple[int, ...], position_codes: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(natural_positions, accomplished_positions): best rating first, ties in array order."""
    ranked_indexes = sorted(range(len(ratings)), key=lambda index: -ratings[index])
    natural_positions = tuple(
        position_codes[index] for index in ranked_indexes if ratings[index] >= 18
    )
    accomplished_positions = tuple(
        position_codes[index] for index in ranked_indexes if 15 <= ratings[index] <= 17
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


def decode_player_record(game_db: bytes, record_offset: int, club_index: ClubIndex) -> Player:
    """Decode one player record's public fields; person fields stay empty until a later task."""
    layout = _DEFAULT_RECORD_LAYOUT
    uid: int = _U32.unpack_from(game_db, record_offset + layout.uid_offset)[0]

    home_reputation, current_reputation, world_reputation = _U16_TRIPLE.unpack_from(
        game_db, record_offset + layout.home_reputation_offset
    )
    reputation = Reputation(
        bucket=game_db[record_offset + layout.reputation_bucket_offset],
        home=home_reputation,
        current=current_reputation,
        world=world_reputation,
    )

    current_ability: int = _U16.unpack_from(game_db, record_offset + layout.current_ability_offset)[
        0
    ]
    potential_ability_raw: int = _I16.unpack_from(
        game_db, record_offset + layout.potential_ability_offset
    )[0]
    if potential_ability_raw < 0:
        ability = Ability(
            current=current_ability, potential=None, potential_range_code=potential_ability_raw
        )
    else:
        ability = Ability(
            current=current_ability, potential=potential_ability_raw, potential_range_code=None
        )

    stored_team_id: int = _U32.unpack_from(game_db, record_offset + layout.team_id_offset)[0]
    team_id = None if stored_team_id == MISSING_REFERENCE else stored_team_id
    club_uid = club_name = club_short_name = None
    club_nation_id = club_fa_nation_id = None
    club_reputation = club_last_league_position = None
    team_slot = None
    if team_id is not None:
        club_team = club_index.team_to_club.get(team_id)
        if club_team is not None:
            club_uid, team_slot = club_team
            club = club_index.club_by_uid[club_uid]
            club_name = club.name
            club_short_name = club.short_name
            club_nation_id = club.nation_id
            club_fa_nation_id = club.fa_nation_id
            club_reputation = club.reputation
            club_last_league_position = club.last_league_position

    ratings = _RATINGS.unpack_from(game_db, record_offset + layout.ratings_offset)
    positions = Positions(*ratings)
    natural_positions, accomplished_positions = _derived_positions(ratings, layout.position_codes)

    raw_values = _RAW_ATTRIBUTES.unpack_from(game_db, record_offset + layout.attributes_offset)
    raw_attribute_values = raw_values[:24] + raw_values[26:]
    raw_attributes = Attributes(*raw_attribute_values)
    attributes = Attributes(*[_scaled_attribute(value) for value in raw_attribute_values])
    raw_left_foot, raw_right_foot = raw_values[24], raw_values[25]
    left_foot = _scaled_attribute(raw_left_foot)
    right_foot = _scaled_attribute(raw_right_foot)

    transfer_value_raw: int = _U32.unpack_from(
        game_db, record_offset + layout.transfer_value_offset
    )[0]
    transfer_value, transfer_value_state = _transfer_value(
        transfer_value_raw, layout.transfer_value_placeholder
    )

    club_join_date = decode_date(game_db, record_offset + layout.club_join_date_offset)
    match_sharpness: int = _U16.unpack_from(game_db, record_offset + layout.match_sharpness_offset)[
        0
    ]
    condition: int = _U16.unpack_from(game_db, record_offset + layout.condition_offset)[0]
    height_cm = game_db[record_offset + layout.height_offset]

    return Player(
        uid=uid,
        name=None,
        first_name=None,
        last_name=None,
        common_name=None,
        full_name=None,
        legal_name=None,
        birth_date=None,
        age=None,
        nation_id=None,
        second_nation_ids=(),
        home_grown_nation_ids=(),
        home_grown_club_uids=(),
        home_grown_club_names=(),
        height_cm=height_cm,
        ability=ability,
        reputation=reputation,
        club_uid=club_uid,
        club_name=club_name,
        club_short_name=club_short_name,
        club_nation_id=club_nation_id,
        club_fa_nation_id=club_fa_nation_id,
        club_reputation=club_reputation,
        club_last_league_position=club_last_league_position,
        team_id=team_id,
        team_slot=team_slot,
        club_join_date=club_join_date,
        natural_positions=natural_positions,
        accomplished_positions=accomplished_positions,
        personality=None,
        attributes=attributes,
        raw_attributes=raw_attributes,
        left_foot=left_foot,
        right_foot=right_foot,
        raw_left_foot=raw_left_foot,
        raw_right_foot=raw_right_foot,
        positions=positions,
        transfer_value=transfer_value,
        transfer_value_state=transfer_value_state,
        condition=condition,
        match_sharpness=match_sharpness,
        traits=(),
        trait_bits=None,
    )
