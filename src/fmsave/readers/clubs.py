"""Club records, their team lists, and the club-status table in `game_db`.

Club records are found by scanning for their anchor bytes and checking every candidate. They
sit back to back, so a record runs to the next accepted one. Each record holds a team list;
a separate status table holds each club's reputation and last league position. The result is
a private index that other readers use to join teams to clubs.
"""

from __future__ import annotations

import functools
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fmsave._layouts import ClubRecordLayout, ClubStatusLayout, TeamListLayout, find_layout
from fmsave.models.clubs import Club, Team
from fmsave.readers._common import GAME_DB_SECTION, MISSING_REFERENCE, layout_mismatch

_UINT32 = struct.Struct("<I")
_UINT16 = struct.Struct("<H")
_UINT32_PAIR = struct.Struct("<II")
_NO_STATUS: tuple[int | None, int | None] = (None, None)


@functools.cache
def _team_ids_struct(team_count: int) -> struct.Struct:
    return struct.Struct(f"<{team_count}I")


@dataclass(frozen=True, slots=True)
class ClubLayouts:
    """The layouts the club reader uses."""

    records: ClubRecordLayout
    team_lists: TeamListLayout
    statuses: ClubStatusLayout


def find_club_layouts(game_db_schema: int | None, build: str) -> ClubLayouts:
    """Look up the club layouts for a `game_db` schema, falling back to the build."""
    return ClubLayouts(
        records=find_layout(ClubRecordLayout, GAME_DB_SECTION, game_db_schema, build).layout,
        team_lists=find_layout(TeamListLayout, GAME_DB_SECTION, game_db_schema, build).layout,
        statuses=find_layout(ClubStatusLayout, GAME_DB_SECTION, game_db_schema, build).layout,
    )


@dataclass(frozen=True, slots=True, repr=False)
class ClubIndex:
    """Every club in club index order, with the lookups other readers join through.

    One index is cached and shared by every reader of a save: never mutate its mappings.

    Attributes:
        clubs: Every accepted club, in ascending club index.
        uid_by_club_index: The club uid for each club index (the stored index plus 1). Club
            indexes are unique.
        club_by_uid: The club for each uid (the stored uid plus 1). Uids are unique.
        team_to_club: (club uid, slot) for each team id. Team ids are exactly as stored, with
            no +1, unlike club indexes and uids. Each team id belongs to one club and one slot.
    """

    clubs: tuple[Club, ...]
    uid_by_club_index: Mapping[int, int]
    club_by_uid: Mapping[int, Club]
    team_to_club: Mapping[int, tuple[int, int]]

    def __repr__(self) -> str:
        return f"<fmsave ClubIndex {len(self.clubs)} clubs, {len(self.team_to_club)} teams>"


@dataclass(frozen=True, slots=True)
class _ClubRecord:
    """The fixed fields of one accepted club record, in the public +1 id space."""

    record_start: int
    club_index: int
    uid: int
    nation_id: int
    fa_nation_id: int
    city_id: int | None
    name: str
    short_name: str


def read_club_index(game_db: bytes, layouts: ClubLayouts, file_name: str) -> ClubIndex:
    """Read every club record, its team list and its status into a ClubIndex.

    Raises:
        ReaderCheckError: No club record is accepted, a club uid or club index appears in two
            records, or a team id is listed twice (by one club or by two).
    """
    records, scan_end = _scan_club_records(game_db, layouts.records)
    if not records:
        raise layout_mismatch(file_name, "no club records found")
    _reject_repeated_club_keys(records, file_name)
    record_ends = [next_record.record_start for next_record in records[1:]]
    record_ends.append(scan_end)
    teams_by_record = [
        _read_teams(game_db, record.record_start, record_end, layouts.team_lists)
        for record, record_end in zip(records, record_ends, strict=True)
    ]
    team_to_club = _map_teams_to_clubs(records, teams_by_record, file_name)
    index_order = sorted(range(len(records)), key=lambda position: records[position].club_index)
    statuses = _read_statuses(
        game_db, [records[position].uid for position in index_order], layouts.statuses
    )

    clubs: list[Club] = []
    uid_by_club_index: dict[int, int] = {}
    club_by_uid: dict[int, Club] = {}
    for position, (reputation, last_league_position) in zip(index_order, statuses, strict=True):
        record = records[position]
        club = Club(
            uid=record.uid,
            name=record.name,
            short_name=record.short_name,
            nation_id=record.nation_id,
            fa_nation_id=record.fa_nation_id,
            city_id=record.city_id,
            teams=teams_by_record[position],
            reputation=reputation,
            last_league_position=last_league_position,
        )
        clubs.append(club)
        uid_by_club_index[record.club_index] = record.uid
        club_by_uid[record.uid] = club
    return ClubIndex(
        clubs=tuple(clubs),
        uid_by_club_index=uid_by_club_index,
        club_by_uid=club_by_uid,
        team_to_club=team_to_club,
    )


def _reject_repeated_club_keys(records: Sequence[_ClubRecord], file_name: str) -> None:
    seen_uids: set[int] = set()
    seen_club_indexes: set[int] = set()
    for record in records:
        if record.uid in seen_uids:
            raise layout_mismatch(file_name, f"club uid {record.uid} appears in two club records")
        if record.club_index in seen_club_indexes:
            raise layout_mismatch(
                file_name, f"club index {record.club_index} appears in two club records"
            )
        seen_uids.add(record.uid)
        seen_club_indexes.add(record.club_index)


def _map_teams_to_clubs(
    records: Sequence[_ClubRecord],
    teams_by_record: Sequence[tuple[Team, ...]],
    file_name: str,
) -> dict[int, tuple[int, int]]:
    """Map each team id to (club uid, slot); club uids must already be unique."""
    team_to_club: dict[int, tuple[int, int]] = {}
    for record, teams in zip(records, teams_by_record, strict=True):
        for team in teams:
            claiming_club = team_to_club.get(team.team_id)
            if claiming_club is not None:
                repeat = "twice by one club" if claiming_club[0] == record.uid else "by two clubs"
                raise layout_mismatch(file_name, f"team id {team.team_id} is listed {repeat}")
            team_to_club[team.team_id] = (record.uid, team.slot)
    return team_to_club


def _scan_club_records(game_db: bytes, layout: ClubRecordLayout) -> tuple[list[_ClubRecord], int]:
    """Return the accepted records in file order and the offset that ends the last one."""
    buffer_length = len(game_db)
    find_anchor = game_db.find
    anchor = layout.anchor
    anchor_offset = layout.anchor_offset
    stop_gap_bytes = layout.stop_gap_bytes
    zero_byte_offset = layout.zero_byte_offset
    header_bytes = (
        max(
            layout.club_index_offset,
            layout.uid_offset,
            layout.uid_copy_offset,
            layout.nation_offset,
            layout.fa_nation_offset,
            layout.nation_copy_offset,
            layout.city_offset,
            layout.long_name_offset,
        )
        + _UINT32.size
    )
    records: list[_ClubRecord] = []
    last_accepted_start = 0
    anchor_hit = find_anchor(anchor, anchor_offset)
    while anchor_hit >= 0:
        record_start = anchor_hit - anchor_offset
        if records and record_start - last_accepted_start >= stop_gap_bytes:
            break
        if (
            record_start + header_bytes <= buffer_length
            and game_db[record_start + zero_byte_offset] == 0
        ):
            record = _accepted_record(game_db, record_start, layout, buffer_length)
            if record is not None:
                records.append(record)
                last_accepted_start = record_start
        anchor_hit = find_anchor(anchor, anchor_hit + 1)
    if not records:
        return records, buffer_length
    return records, min(last_accepted_start + stop_gap_bytes, buffer_length)


def _accepted_record(
    game_db: bytes, record_start: int, layout: ClubRecordLayout, buffer_length: int
) -> _ClubRecord | None:
    """Check one candidate whose fixed header lies inside the buffer; None when it fails."""
    read_uint32 = _UINT32.unpack_from
    lowest_nation_id, highest_nation_id = layout.nation_id_range
    nation_id: int = read_uint32(game_db, record_start + layout.nation_offset)[0]
    if not lowest_nation_id <= nation_id <= highest_nation_id:
        return None
    if read_uint32(game_db, record_start + layout.nation_copy_offset)[0] != nation_id:
        return None
    fa_nation_id: int = read_uint32(game_db, record_start + layout.fa_nation_offset)[0]
    if not lowest_nation_id <= fa_nation_id <= highest_nation_id:
        return None
    stored_uid: int = read_uint32(game_db, record_start + layout.uid_offset)[0]
    if read_uint32(game_db, record_start + layout.uid_copy_offset)[0] != stored_uid:
        return None
    max_name_bytes = layout.max_name_bytes
    long_name_length_at = record_start + layout.long_name_offset
    long_name_length: int = read_uint32(game_db, long_name_length_at)[0]
    if not 1 <= long_name_length <= max_name_bytes:
        return None
    long_name_start = long_name_length_at + _UINT32.size
    short_name_length_at = long_name_start + long_name_length
    if short_name_length_at + _UINT32.size > buffer_length:
        return None
    short_name_length: int = read_uint32(game_db, short_name_length_at)[0]
    if not 1 <= short_name_length <= max_name_bytes:
        return None
    short_name_start = short_name_length_at + _UINT32.size
    short_name_end = short_name_start + short_name_length
    if short_name_end > buffer_length:
        return None
    try:
        name = game_db[long_name_start:short_name_length_at].decode("utf-8")
        short_name = game_db[short_name_start:short_name_end].decode("utf-8")
    except UnicodeDecodeError:
        return None
    stored_club_index: int = read_uint32(game_db, record_start + layout.club_index_offset)[0]
    stored_city_id: int = read_uint32(game_db, record_start + layout.city_offset)[0]
    return _ClubRecord(
        record_start=record_start,
        club_index=stored_club_index + 1,
        uid=stored_uid + 1,
        nation_id=nation_id,
        fa_nation_id=fa_nation_id,
        city_id=None if stored_city_id == MISSING_REFERENCE else stored_city_id,
        name=name,
        short_name=short_name,
    )


def _read_teams(
    game_db: bytes, record_start: int, record_end: int, layout: TeamListLayout
) -> tuple[Team, ...]:
    """Parse the record's team list from its date anchor, then from each float anchor."""
    triple_at = game_db.find(layout.null_date_triple, record_start, record_end)
    if triple_at >= 0:
        team_ids = _parse_team_ids(game_db, triple_at, record_end, layout)
        if team_ids is not None:
            return _teams_in_slot_order(team_ids)
    float_anchor = layout.float_anchor
    float_hit = game_db.find(
        float_anchor, record_start + layout.minimum_float_anchor_record_offset, record_end
    )
    while float_hit >= 0:
        team_list_start = float_hit - layout.float_anchor_offset
        team_ids = _parse_team_ids(game_db, team_list_start, record_end, layout)
        if team_ids is not None:
            return _teams_in_slot_order(team_ids)
        float_hit = game_db.find(float_anchor, float_hit + 1, record_end)
    return ()


def _teams_in_slot_order(team_ids: tuple[int, ...]) -> tuple[Team, ...]:
    return tuple(Team(team_id=team_id, slot=slot) for slot, team_id in enumerate(team_ids))


def _parse_team_ids(
    game_db: bytes, team_list_start: int, record_end: int, layout: TeamListLayout
) -> tuple[int, ...] | None:
    """Read the team ids of a list starting at team_list_start; None when it does not fit."""
    cursor = team_list_start + layout.counts_offset
    for entry_bytes, lead_byte in (
        (layout.first_entry_bytes, layout.first_entry_lead_byte),
        (layout.second_entry_bytes, layout.second_entry_lead_byte),
    ):
        if cursor >= record_end:
            return None
        entries_start = cursor + 1
        entries_end = entries_start + game_db[cursor] * entry_bytes
        if entries_end > record_end:
            return None
        for entry_start in range(entries_start, entries_end, entry_bytes):
            if game_db[entry_start] != lead_byte:
                return None
        cursor = entries_end
    team_count_at = cursor + layout.filler_bytes
    if team_count_at >= record_end:
        return None
    team_count = game_db[team_count_at]
    lowest_team_count, highest_team_count = layout.team_count_range
    if not lowest_team_count <= team_count <= highest_team_count:
        return None
    team_ids_struct = _team_ids_struct(team_count)
    team_ids_start = team_count_at + 1
    if team_ids_start + team_ids_struct.size > record_end:
        return None
    team_ids: tuple[int, ...] = team_ids_struct.unpack_from(game_db, team_ids_start)
    lowest_team_id, highest_team_id = layout.team_id_range
    for team_id in team_ids:
        if not lowest_team_id <= team_id <= highest_team_id:
            return None
    return team_ids


def _read_statuses(
    game_db: bytes, uids_in_index_order: Sequence[int], layout: ClubStatusLayout
) -> list[tuple[int | None, int | None]]:
    """Walk the status table once, in club index order; return (reputation, position) pairs.

    Until a hit is accepted each search runs to the end of the buffer, and the walk gives up
    after `maximum_leading_misses` clubs in a row miss. After that, a hit must start at most
    `search_window_bytes` past the cursor.
    """
    buffer_length = len(game_db)
    find_uid_pair = game_db.find
    pack_uid_pair = _UINT32_PAIR.pack
    read_uint32 = _UINT32.unpack_from
    ordinal_offset = layout.ordinal_offset
    ordinal_limit = layout.ordinal_limit
    kind_offset = layout.kind_offset
    normal_kind = layout.normal_kind
    accepted_kinds = (normal_kind, layout.stub_kind)
    window_span = layout.search_window_bytes + _UINT32_PAIR.size
    statuses: list[tuple[int | None, int | None]] = []
    cursor = 0
    previous_ordinal = -1
    found_first_status = False
    leading_misses = 0
    for uid in uids_in_index_order:
        stored_uid = uid - 1
        uid_pair = pack_uid_pair(stored_uid, stored_uid)
        search_end = cursor + window_span if found_first_status else buffer_length
        status = _NO_STATUS
        accepted = False
        status_hit = find_uid_pair(uid_pair, cursor, search_end)
        while status_hit >= 0:
            ordinal_at = status_hit + ordinal_offset
            kind_at = status_hit + kind_offset
            if (
                0 <= ordinal_at
                and ordinal_at + _UINT32.size <= buffer_length
                and kind_at < buffer_length
            ):
                ordinal: int = read_uint32(game_db, ordinal_at)[0]
                kind = game_db[kind_at]
                if previous_ordinal < ordinal < ordinal_limit and kind in accepted_kinds:
                    accepted = True
                    previous_ordinal = ordinal
                    cursor = kind_at
                    if kind == normal_kind:
                        status = _normal_status(game_db, status_hit, layout)
                    break
            status_hit = find_uid_pair(uid_pair, status_hit + 1, search_end)
        statuses.append(status)
        if accepted:
            found_first_status = True
        elif not found_first_status:
            leading_misses += 1
            if leading_misses >= layout.maximum_leading_misses:
                break
    statuses.extend([_NO_STATUS] * (len(uids_in_index_order) - len(statuses)))
    return statuses


def _normal_status(
    game_db: bytes, status_hit: int, layout: ClubStatusLayout
) -> tuple[int | None, int | None]:
    """Read (reputation, last league position) from a normal status record."""
    buffer_length = len(game_db)
    position_at = status_hit + layout.position_offset
    last_league_position = game_db[position_at] if position_at < buffer_length else None
    reputation_at = status_hit + layout.reputation_offset
    reputation: int | None = None
    if reputation_at + _UINT16.size <= buffer_length:
        stored_reputation: int = _UINT16.unpack_from(game_db, reputation_at)[0]
        lowest_reputation, highest_reputation = layout.reputation_range
        if lowest_reputation <= stored_reputation <= highest_reputation:
            reputation = stored_reputation
    return reputation, last_league_position
