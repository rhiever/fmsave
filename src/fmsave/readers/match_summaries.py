"""Counted, owned match summaries used only to enrich missing fixture scores."""

from __future__ import annotations

import datetime
import functools
import re
import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fmsave._errors import CorruptSaveError
from fmsave._frozen import FrozenMapping
from fmsave._layouts import MatchSummaryLayout, find_layout
from fmsave._scan import decode_date
from fmsave.models.officials import Official
from fmsave.readers._common import GAME_DB_SECTION, MISSING_REFERENCE
from fmsave.readers.persons import PersonBlockDecoder

type MatchSummaryKey = tuple[datetime.date, int, int, int]
type ScorePair = tuple[int, int]
type _SummaryRows = list[tuple[MatchSummaryKey, ScorePair]]

_WORD = struct.Struct("<I")


@dataclass(frozen=True, slots=True)
class MatchSummaryScores:
    """Scores from complete objects; a poisoned key can never supply enrichment."""

    scores: FrozenMapping[MatchSummaryKey, ScorePair | None]
    lists_found: int
    lists_decoded: int
    record_count: int
    invalid_score_records: int


def find_match_summary_layout(game_db_schema: int | None, build: str) -> MatchSummaryLayout:
    return find_layout(MatchSummaryLayout, GAME_DB_SECTION, game_db_schema, build).layout


@functools.cache
def _header_pattern(layout: MatchSummaryLayout) -> tuple[re.Pattern[bytes], int]:
    constraints = {layout.kind_offset: re.escape(bytes([layout.kind_value]))}
    for offset in layout.ability_offsets:
        low, high = layout.ability_range
        if not 0 <= low <= high <= 255:
            raise ValueError("summary ability locator must fit a byte")
        constraints[offset] = rb"[" + re.escape(bytes(range(low, high + 1))) + rb"]"
        constraints[offset + 1] = b"\x00"
    low, high = layout.attributes_range
    attribute = rb"[" + re.escape(bytes(range(low, high + 1))) + rb"]"
    for offset in range(
        layout.attributes_offset, layout.attributes_offset + layout.attributes_count
    ):
        constraints[offset] = attribute
    for offset in layout.flag_offsets:
        constraints[offset] = rb"[\x00\x01]"
    first, last = min(constraints), max(constraints)
    if first < 0 or last >= layout.header_bytes:
        raise ValueError("summary locator lies outside its header")
    return re.compile(
        b"".join(constraints.get(i, b".") for i in range(first, last + 1)), re.DOTALL
    ), first


def _sound_header(db: bytes, at: int, layout: MatchSummaryLayout) -> bool:
    uid = _WORD.unpack_from(db, at + layout.uid_offset)[0]
    if uid in (0, 0xFFFFFFFF) or uid != _WORD.unpack_from(db, at + layout.uid_copy_offset)[0]:
        return False
    return _WORD.unpack_from(db, at + layout.header_word_offset)[0] in layout.header_word_values


def _walk_object(
    db: bytes, at: int, count: int, layout: MatchSummaryLayout
) -> tuple[_SummaryRows, int] | None:
    end = len(db)
    offset = at + layout.header_bytes
    if count > (end - offset) // layout.record_bytes:
        return None
    rows: list[tuple[MatchSummaryKey, ScorePair]] = []
    for _ in range(count):
        if db[offset + layout.lead_byte_offset] != layout.lead_byte_value:
            return None
        date = decode_date(db, offset + layout.date_offset)
        competition = _WORD.unpack_from(db, offset + layout.competition_id_offset)[0]
        home = _WORD.unpack_from(db, offset + layout.home_team_id_offset)[0]
        away = _WORD.unpack_from(db, offset + layout.away_team_id_offset)[0]
        if date is None:
            return None
        score = (db[offset + layout.home_goals_offset], db[offset + layout.away_goals_offset])
        rows.append(((date, competition, home, away), score))
        offset += layout.record_bytes
    for _ in range(layout.trailing_array_count):
        if offset + _WORD.size > end:
            return None
        words = _WORD.unpack_from(db, offset)[0]
        offset += _WORD.size
        if words > (end - offset) // _WORD.size:
            return None
        offset += words * _WORD.size
    if offset + 4 > end:
        return None
    if db[offset : offset + 4] != layout.null_date_bytes and decode_date(db, offset) is None:
        return None
    return rows, offset + 4


def _summary_objects(
    db: bytes, layout: MatchSummaryLayout
) -> Iterator[tuple[int, tuple[_SummaryRows, int] | None]]:
    pattern, back = _header_pattern(layout)
    start = 0
    while (hit := pattern.search(db, start)) is not None:
        start = hit.start() + 1
        at = hit.start() - back
        if at < 0 or at + layout.header_bytes > len(db) or not _sound_header(db, at, layout):
            continue
        walked = _walk_object(db, at, db[at + layout.count_offset], layout)
        yield at, walked
        if walked is not None:
            _, start = walked


def locate_match_summary_scores(db: bytes, layout: MatchSummaryLayout) -> MatchSummaryScores:
    """Require the complete header, declared rows, and closing collection grammar.

    A bad statistical value still belongs to a structurally sound row. It poisons that
    exact fixture key, as does any conflicting duplicate, without changing the count walk.
    """
    scores: dict[MatchSummaryKey, ScorePair | None] = {}
    found = decoded = records = invalid = 0
    for _, walked in _summary_objects(db, layout):
        found += 1
        if walked is None:
            continue
        rows, _ = walked
        decoded += 1
        records += len(rows)
        for key, pair in rows:
            if max(pair) > layout.goals_maximum:
                invalid += 1
                scores[key] = None
            elif key not in scores:
                scores[key] = pair
            elif scores[key] != pair:
                scores[key] = None
    return MatchSummaryScores(FrozenMapping(scores), found, decoded, records, invalid)


def locate_officials(
    db: bytes, layout: MatchSummaryLayout, build_person_decoder: Callable[[], PersonBlockDecoder]
) -> tuple[Official, ...]:
    """Read complete official objects with an attached person block."""
    by_referee_id: dict[int, Official | None] = {}
    person_decoder = None
    for at, walked in _summary_objects(db, layout):
        if walked is None:
            continue
        official_index = _WORD.unpack_from(db, at + layout.official_index_offset)[0]
        # Like other person selectors, the calendar reference is the object index plus one.
        referee_id = official_index + 1
        if referee_id >= MISSING_REFERENCE:
            continue
        _, end = walked
        if person_decoder is None:
            person_decoder = build_person_decoder()
        try:
            person = person_decoder.decode_at_start(db, end + layout.person_block_offset_from_end)
        except CorruptSaveError:
            continue
        if person is None:
            continue
        person_uid = _WORD.unpack_from(db, at + layout.uid_offset)[0]
        official = Official(referee_id, person_uid, person[0])
        if referee_id not in by_referee_id:
            by_referee_id[referee_id] = official
        elif by_referee_id[referee_id] != official:
            by_referee_id[referee_id] = None
    return tuple(official for _, official in sorted(by_referee_id.items()) if official is not None)
