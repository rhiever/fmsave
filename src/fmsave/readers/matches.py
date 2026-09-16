"""Locating a player's per-match records in `game_db` and joining them to players and clubs.

The records sit inside the owning player's own object, so the search runs over the player
region exactly as the suspension search does: from just before the first player record to the
end of `game_db`, with a compiled pattern that resumes one byte after every match start so
records that overlap a false lead byte are all considered. Each record is given to its owning
player by bisecting the sorted record offsets, and a record lying before the first player's
window belongs to none.

**The trap this reader exists to avoid.** A record whose body flag is zero is fifteen bytes
long, not forty-three, and every field past the position mask then belongs to the *next* match.
Reading a body off a record that has none does not give a wrong number, it gives another
match's number, which looks perfectly ordinary. Every body field is therefore gated on that one
byte, and the derived layout checks that no body field starts inside the header, so a layout
that moved one into it fails at derivation rather than quietly reporting another match.

The pattern, the two field structs, the offsets and the bounds are derived from the layout and
the save's clock once per pair, and checked for consistency at that point, so the search loop
reads no layout field.
"""

from __future__ import annotations

import datetime
import functools
import re
import struct
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass

from fmsave._frozen import FrozenMapping
from fmsave._layouts import MatchRecordLayout, find_layout
from fmsave._reader_stats import MatchStats
from fmsave._scan import decode_date
from fmsave.models.clubs import Club
from fmsave.models.common import CodedValue
from fmsave.models.matches import MatchPosition, PlayerMatchStats
from fmsave.models.players import Player
from fmsave.readers._common import GAME_DB_SECTION, build_gap_padded_struct
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.player_scan import PlayerRecords
from fmsave.readers.stages import StageIndex
from fmsave.table import Table

# The key a record is filed under when it lies before the first player's window and so belongs
# to no player. Such a record is counted and then dropped: nothing is built from it.
#
# This count is structurally zero, and the guard behind it is still worth keeping. The search
# starts where the first player's window starts, so no record it can reach bisects below the
# first player, and every save measured files none here. What the guard prevents is worse than
# an undercount: a position of -1 indexes the *last* player's uid, so were the region ever to
# start earlier, a record before the first window would be credited to the wrong player in
# silence. It is not dead code; do not remove it because the count never moves.
UNOWNED_POSITION = -1

# How far into a stored date its year sits, and how far to shift that year for its high byte.
_YEAR_OFFSET_IN_DATE = 2
_DATE_BYTES = 4
_YEAR_HIGH_BYTE_SHIFT = 8
# How wide the position mask is, which bounds the bits a layout may name.
_POSITION_MASK_BITS = 16
_NO_BODY_FLAG = 0
_BODY_FLAG = 1

_NO_OPPONENT_CLUB: tuple[int | None, str | None, str | None, int | None] = (None, None, None, None)


@dataclass(frozen=True, slots=True)
class RawMatchRecord:
    """One accepted per-match record, before any join.

    Every field from `position_mask` on is None when `played` is false, because the record then
    stops before them and those bytes belong to the next match.

    Attributes:
        date: The date the match was played.
        opponent_team_id: The opposing side's first-team id, exactly as stored.
        competition_id: The competition id, in the stage id space.
        tag: The unidentified byte exported as `unknown["tag"]`.
        played: Whether a performance body follows the header.
        position_mask: The stored position mask.
        role_code: The unidentified byte exported as `unknown["role_code"]`.
        goals: Goals scored.
        assists: Assists, which is a hypothesis with no labelled source.
        left_at_minute: The minute the player left the pitch.
        minutes: Minutes played.
        rating_raw: The match rating before it is divided by the layout's scale.
        passes_attempted: Passes attempted.
        passes_completed: Passes completed.
    """

    date: datetime.date
    opponent_team_id: int
    competition_id: int
    tag: int
    played: bool
    position_mask: int | None
    role_code: int | None
    goals: int | None
    assists: int | None
    left_at_minute: int | None
    minutes: int | None
    rating_raw: int | None
    passes_attempted: int | None
    passes_completed: int | None


@dataclass(frozen=True, slots=True)
class _MatchSearch:
    """Everything `locate_match_records` needs from a layout and a clock year, derived once.

    `pattern` matches from a record's lead byte, which is the record start. `header_struct`
    unpacks the fields every record carries and `body_struct` those only a record with a body
    carries; both unpack from the record start, and the `*_index` fields give each value's
    position in its result.
    """

    pattern: re.Pattern[bytes]
    header_struct: struct.Struct
    opponent_team_id_index: int
    competition_id_index: int
    tag_index: int
    body_flag_index: int
    body_struct: struct.Struct
    position_mask_index: int
    role_code_index: int
    goals_index: int
    assists_index: int
    left_at_index: int
    minutes_index: int
    rating_index: int
    passes_attempted_index: int
    passes_completed_index: int
    date_offset: int
    header_bytes: int
    record_bytes: int
    owner_back_offset: int
    lowest_team_id: int
    highest_team_id: int
    lowest_competition_id: int
    highest_competition_id: int


def find_match_record_layout(game_db_schema: int | None, build: str) -> MatchRecordLayout:
    """Look up the per-match record layout for a `game_db` schema, falling back to the build."""
    return find_layout(MatchRecordLayout, GAME_DB_SECTION, game_db_schema, build).layout


def _year_byte_class(years: range) -> tuple[bytes, int]:
    """(the low byte class, the shared high byte) for the years a record's date may carry.

    Raises:
        ValueError: The years do not share one high byte, or their low bytes are not a single
            run, so no one byte class covers them.
    """
    high_bytes = {year >> _YEAR_HIGH_BYTE_SHIFT for year in years}
    if len(high_bytes) != 1:
        raise ValueError(
            f"the match years {years.start} to {years.stop - 1} do not share one high byte, "
            "so no single byte class covers them"
        )
    low_bytes = sorted(year & 0xFF for year in years)
    if low_bytes[-1] - low_bytes[0] != len(low_bytes) - 1:
        raise ValueError("the match years' low bytes are not a single run")
    byte_class = (
        b"[" + re.escape(bytes((low_bytes[0],))) + b"-" + re.escape(bytes((low_bytes[-1],))) + b"]"
    )
    return byte_class, high_bytes.pop()


@functools.cache
def _match_search(layout: MatchRecordLayout, clock_year: int) -> _MatchSearch:
    """The layout's compiled search and structs for one in-game year, built on first use.

    Raises:
        ValueError: The lead byte does not start a record, the date does not lie inside the
            header, the header is not shorter than a whole record, a header field ends past the
            header, a body field starts inside the header or ends past the record, two fields
            overlap, the years around the clock share no high byte, or a bound leaves no id.
    """
    if layout.lead_byte_offset != 0:
        raise ValueError(
            f"the lead byte at offset {layout.lead_byte_offset} must start a record, since the "
            "search anchors on it"
        )
    if layout.header_bytes >= layout.record_bytes:
        raise ValueError(
            f"the {layout.header_bytes}-byte header must be shorter than the "
            f"{layout.record_bytes}-byte record, which is the header plus a body"
        )
    if layout.date_offset <= layout.lead_byte_offset:
        raise ValueError(f"the date at offset {layout.date_offset} must follow the lead byte")
    if layout.date_offset + _DATE_BYTES > layout.header_bytes:
        raise ValueError(
            f"the date at offset {layout.date_offset} ends past the {layout.header_bytes}-byte "
            "header, which every record carries whole"
        )
    year_low_offset = layout.date_offset + _YEAR_OFFSET_IN_DATE
    years = range(clock_year - layout.years_before_clock, clock_year + layout.years_after_clock + 1)
    year_class, year_high_byte = _year_byte_class(years)
    pattern = re.compile(
        re.escape(bytes((layout.lead_byte_value,)))
        + b".{%d}" % (year_low_offset - layout.lead_byte_offset - 1)
        + year_class
        + re.escape(bytes((year_high_byte,))),
        re.DOTALL,
    )

    header_specs = [
        (layout.opponent_team_id_offset, "I", "opponent_team_id"),
        (layout.competition_id_offset, "I", "competition_id"),
        (layout.tag_offset, "B", "tag"),
        (layout.body_flag_offset, "B", "body_flag"),
    ]
    body_specs = [
        (layout.position_mask_offset, "H", "position_mask"),
        (layout.role_code_offset, "B", "role_code"),
        (layout.goals_offset, "B", "goals"),
        (layout.assists_offset, "B", "assists"),
        (layout.left_at_offset, "B", "left_at_minute"),
        (layout.minutes_offset, "B", "minutes"),
        (layout.rating_offset, "B", "rating"),
        (layout.passes_attempted_offset, "B", "passes_attempted"),
        (layout.passes_completed_offset, "B", "passes_completed"),
    ]
    for offset, format_code, field_name in header_specs:
        if offset + struct.calcsize(format_code) > layout.header_bytes:
            raise ValueError(
                f"header field {field_name!r} at offset {offset} ends past the "
                f"{layout.header_bytes}-byte header, which every record carries whole"
            )
    for offset, format_code, field_name in body_specs:
        if offset < layout.header_bytes:
            raise ValueError(
                f"body field {field_name!r} at offset {offset} starts inside the "
                f"{layout.header_bytes}-byte header, so a record with no body would appear to "
                "carry one"
            )
        if offset + struct.calcsize(format_code) > layout.record_bytes:
            raise ValueError(
                f"body field {field_name!r} at offset {offset} ends past the "
                f"{layout.record_bytes}-byte record"
            )
    header_struct, _header_start, header_indexes = build_gap_padded_struct(
        header_specs, start_offset=0
    )
    body_struct, _body_start, body_indexes = build_gap_padded_struct(body_specs, start_offset=0)

    lowest_team_id, highest_team_id = layout.team_id_range
    if highest_team_id < lowest_team_id:
        raise ValueError(f"team_id_range {layout.team_id_range} leaves no team id")
    lowest_competition_id, highest_competition_id = layout.competition_id_range
    if highest_competition_id < lowest_competition_id:
        raise ValueError(
            f"competition_id_range {layout.competition_id_range} leaves no competition id"
        )
    return _MatchSearch(
        pattern=pattern,
        header_struct=header_struct,
        opponent_team_id_index=header_indexes["opponent_team_id"],
        competition_id_index=header_indexes["competition_id"],
        tag_index=header_indexes["tag"],
        body_flag_index=header_indexes["body_flag"],
        body_struct=body_struct,
        position_mask_index=body_indexes["position_mask"],
        role_code_index=body_indexes["role_code"],
        goals_index=body_indexes["goals"],
        assists_index=body_indexes["assists"],
        left_at_index=body_indexes["left_at_minute"],
        minutes_index=body_indexes["minutes"],
        rating_index=body_indexes["rating"],
        passes_attempted_index=body_indexes["passes_attempted"],
        passes_completed_index=body_indexes["passes_completed"],
        date_offset=layout.date_offset,
        header_bytes=layout.header_bytes,
        record_bytes=layout.record_bytes,
        owner_back_offset=layout.owner_back_offset,
        lowest_team_id=lowest_team_id,
        highest_team_id=highest_team_id,
        lowest_competition_id=lowest_competition_id,
        highest_competition_id=highest_competition_id,
    )


def locate_match_records(
    game_db: bytes,
    player_records: PlayerRecords,
    layout: MatchRecordLayout,
    clock: datetime.date,
) -> Mapping[int, tuple[RawMatchRecord, ...]]:
    """Every accepted per-match record, keyed by the position of its owning player record.

    Positions index `player_records.record_offsets` and come in ascending order; each player's
    records keep the order of their offsets, which is the order the save stores them. A player
    with no record has no key. Records lying before the first player's window are filed under
    `UNOWNED_POSITION`, where the counts can see them and nothing is built from them.

    The scan starts `owner_back_offset` bytes before the first record (or at 0) and resumes one
    byte after every match start, kept or not, so a false lead byte cannot hide a real record
    that overlaps it. A record is kept when its date decodes (so day 366 of a year that has 365
    is rejected), its opponent team id and competition id are inside the layout's ranges, its
    body flag is 0 or 1, and the whole of it lies inside the section: a record whose body would
    run past the end of `game_db` cannot be read and is not kept.

    Raises:
        ValueError: The layout is inconsistent (see `_match_search`).
    """
    search = _match_search(layout, clock.year)
    record_offsets = player_records.record_offsets
    if not record_offsets:
        return {}
    find_lead_byte = search.pattern.search
    unpack_header = search.header_struct.unpack_from
    unpack_body = search.body_struct.unpack_from
    opponent_team_id_index = search.opponent_team_id_index
    competition_id_index = search.competition_id_index
    tag_index = search.tag_index
    body_flag_index = search.body_flag_index
    position_mask_index = search.position_mask_index
    role_code_index = search.role_code_index
    goals_index = search.goals_index
    assists_index = search.assists_index
    left_at_index = search.left_at_index
    minutes_index = search.minutes_index
    rating_index = search.rating_index
    passes_attempted_index = search.passes_attempted_index
    passes_completed_index = search.passes_completed_index
    date_offset = search.date_offset
    header_bytes = search.header_bytes
    record_bytes = search.record_bytes
    owner_back_offset = search.owner_back_offset
    lowest_team_id = search.lowest_team_id
    highest_team_id = search.highest_team_id
    lowest_competition_id = search.lowest_competition_id
    highest_competition_id = search.highest_competition_id
    game_db_length = len(game_db)

    region_start = max(0, record_offsets[0] - owner_back_offset)
    records_by_position: dict[int, list[RawMatchRecord]] = {}
    match = find_lead_byte(game_db, region_start, game_db_length)
    while match is not None:
        record_start = match.start()
        match = find_lead_byte(game_db, record_start + 1, game_db_length)
        if record_start + header_bytes > game_db_length:
            continue
        played_on = decode_date(game_db, record_start + date_offset)
        if played_on is None:
            continue
        header_values = unpack_header(game_db, record_start)
        opponent_team_id: int = header_values[opponent_team_id_index]
        if not lowest_team_id <= opponent_team_id <= highest_team_id:
            continue
        competition_id: int = header_values[competition_id_index]
        if not lowest_competition_id <= competition_id <= highest_competition_id:
            continue
        body_flag: int = header_values[body_flag_index]
        if body_flag not in (_NO_BODY_FLAG, _BODY_FLAG):
            continue
        played = body_flag == _BODY_FLAG
        if played and record_start + record_bytes > game_db_length:
            continue
        if played:
            body_values = unpack_body(game_db, record_start)
            record = RawMatchRecord(
                date=played_on,
                opponent_team_id=opponent_team_id,
                competition_id=competition_id,
                tag=header_values[tag_index],
                played=True,
                position_mask=body_values[position_mask_index],
                role_code=body_values[role_code_index],
                goals=body_values[goals_index],
                assists=body_values[assists_index],
                left_at_minute=body_values[left_at_index],
                minutes=body_values[minutes_index],
                rating_raw=body_values[rating_index],
                passes_attempted=body_values[passes_attempted_index],
                passes_completed=body_values[passes_completed_index],
            )
        else:
            # Nothing at or past the position mask is read: those bytes are the next match's.
            record = RawMatchRecord(
                date=played_on,
                opponent_team_id=opponent_team_id,
                competition_id=competition_id,
                tag=header_values[tag_index],
                played=False,
                position_mask=None,
                role_code=None,
                goals=None,
                assists=None,
                left_at_minute=None,
                minutes=None,
                rating_raw=None,
                passes_attempted=None,
                passes_completed=None,
            )
        position = bisect_right(record_offsets, record_start + owner_back_offset) - 1
        if position < 0:
            # Out of reach while the search starts at the first window, and kept all the same:
            # see UNOWNED_POSITION for what a negative position would otherwise do.
            position = UNOWNED_POSITION
        position_records = records_by_position.get(position)
        if position_records is None:
            records_by_position[position] = [record]
        else:
            position_records.append(record)
    return {position: tuple(records) for position, records in records_by_position.items()}


@functools.cache
def _position_labels(
    position_bits: tuple[tuple[int, str], ...],
) -> FrozenMapping[int, MatchPosition]:
    """The whole mask each named bit stands for, mapped to its position.

    Keying on the whole mask rather than on the bit is what makes the lookup total: a mask with
    no bit, with a bit no pair names, or with more than one bit is simply absent, and every one
    of those reads as UNKNOWN with its raw mask kept.

    Raises:
        ValueError: A bit is outside the mask, a bit is named twice, or a name is not a
            `MatchPosition` member.
    """
    labels: dict[int, MatchPosition] = {}
    for bit, member_name in position_bits:
        if not 0 <= bit < _POSITION_MASK_BITS:
            raise ValueError(
                f"position bit {bit} is outside the {_POSITION_MASK_BITS}-bit position mask"
            )
        mask = 1 << bit
        if mask in labels:
            raise ValueError(f"position bit {bit} is named twice")
        try:
            labels[mask] = MatchPosition[member_name]
        except KeyError:
            raise ValueError(
                f"position bit {bit} names {member_name!r}, which is not a MatchPosition member"
            ) from None
    return FrozenMapping(labels)


def _opponent_fields(
    opponent_club: tuple[int, int] | None, club_by_uid: Mapping[int, Club]
) -> tuple[int | None, str | None, str | None, int | None]:
    """(uid, name, short name, slot) of the club fielding the opposing team, all None when no
    club lists that team.
    """
    if opponent_club is None:
        return _NO_OPPONENT_CLUB
    club_uid, team_slot = opponent_club
    club_record = club_by_uid.get(club_uid)
    if club_record is None:
        return club_uid, None, None, team_slot
    return club_uid, club_record.name, club_record.short_name, team_slot


def build_player_match_stats(
    records_by_position: Mapping[int, tuple[RawMatchRecord, ...]],
    player_records: PlayerRecords,
    players: Table[Player],
    club_index: ClubIndex,
    stage_index: StageIndex,
    layout: MatchRecordLayout,
) -> tuple[tuple[PlayerMatchStats, ...], MatchStats]:
    """Join the located records to their players and opponents, and count what the checks judge.

    Rows come back in player order and, inside each player, in the order the save stores his
    matches. A record that belongs to no player builds no row and is counted in
    `MatchStats.unowned`, so `MatchStats.records` counts exactly the rows returned.

    The stage table is read here only to count how many competition ids it names, which is what
    the stage-space check judges. No value of its own reaches a row: a record carries its
    competition id itself, and nothing here looks one up.

    A body outside the layout's bounds is flagged and kept, never blanked: `body_valid` says
    what fmsave makes of the numbers and the numbers stay exactly as the save holds them.
    """
    labels_by_mask = _position_labels(layout.position_bits)
    uids = player_records.uids
    team_to_club = club_index.team_to_club
    club_by_uid = club_index.club_by_uid
    competition_ids = stage_index.stage_ids_by_competition_id
    maximum_minutes = layout.maximum_minutes
    maximum_rating = layout.maximum_rating
    maximum_goals = layout.maximum_goals
    rating_scale = layout.rating_scale

    rows: list[PlayerMatchStats] = []
    record_count = 0
    with_body = 0
    players_with_records = 0
    competition_in_stage_space = 0
    minutes_in_range = 0
    rating_in_range = 0
    body_valid_count = 0
    opponent_resolved = 0
    unowned = 0

    for position in sorted(records_by_position):
        position_records = records_by_position[position]
        if position == UNOWNED_POSITION:
            unowned += len(position_records)
            continue
        players_with_records += 1
        player_uid: int = uids[position]
        decoded_player = players.get_by_uid(player_uid)
        player_name = None if decoded_player is None else decoded_player.name
        for record in position_records:
            record_count += 1
            if record.competition_id in competition_ids:
                competition_in_stage_space += 1
            opponent_club = team_to_club.get(record.opponent_team_id)
            if opponent_club is not None:
                opponent_resolved += 1
            club_uid, club_name, club_short_name, team_slot = _opponent_fields(
                opponent_club, club_by_uid
            )
            position_mask = record.position_mask
            rating_raw = record.rating_raw
            minutes = record.minutes
            goals = record.goals
            body_valid = False
            if record.played:
                with_body += 1
                minutes_ok = minutes is not None and minutes <= maximum_minutes
                rating_ok = rating_raw is not None and rating_raw <= maximum_rating
                goals_ok = goals is not None and goals <= maximum_goals
                minutes_in_range += minutes_ok
                rating_in_range += rating_ok
                body_valid = minutes_ok and rating_ok and goals_ok
                body_valid_count += body_valid
            unknown_values = {"tag": record.tag}
            if record.role_code is not None:
                unknown_values["role_code"] = record.role_code
            rows.append(
                PlayerMatchStats(
                    player_uid=player_uid,
                    player_name=player_name,
                    date=record.date,
                    competition_id=record.competition_id,
                    opponent_team_id=record.opponent_team_id,
                    opponent_club_uid=club_uid,
                    opponent_club_name=club_name,
                    opponent_club_short_name=club_short_name,
                    opponent_team_slot=team_slot,
                    played=record.played,
                    position=(
                        None
                        if position_mask is None
                        else CodedValue(
                            label=labels_by_mask.get(position_mask, MatchPosition.UNKNOWN),
                            raw=position_mask,
                        )
                    ),
                    minutes=minutes,
                    left_at_minute=record.left_at_minute,
                    goals=goals,
                    assists=record.assists,
                    rating=None if rating_raw is None else rating_raw / rating_scale,
                    passes_attempted=record.passes_attempted,
                    passes_completed=record.passes_completed,
                    body_valid=body_valid,
                    unknown=FrozenMapping(unknown_values),
                )
            )

    stats = MatchStats(
        records=record_count,
        with_body=with_body,
        players_with_records=players_with_records,
        competition_in_stage_space=competition_in_stage_space,
        minutes_in_range=minutes_in_range,
        rating_in_range=rating_in_range,
        body_valid=body_valid_count,
        opponent_resolved=opponent_resolved,
        unowned=unowned,
    )
    return tuple(rows), stats
