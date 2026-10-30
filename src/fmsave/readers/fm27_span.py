"""Bounded, partial raw grammar observed on the FM27 preview build.

This is deliberately separate from FM26's span scanner. Raw identities and dates have
structural corroboration; unsupported fields are omitted, not borrowed from FM26.
These raw records are not semantic fixture/rules tables; no in-game verification is implied.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise
from typing import Literal

from fmsave._errors import CorruptSaveError
from fmsave._scan import decode_date

_U32 = struct.Struct("<I")
_U16 = struct.Struct("<H")
_RULE_MARKER = bytes.fromhex("ffff000001ffffff")
_MISSING = 0xFFFFFFFF
_UNSUPPORTED_FIXTURE_FIELDS = (
    "kick_off_time",
    "season_start_year",
    "round_index",
    "match_record_id",
    "match_rules_template",
    "phase",
    "leg",
    "date2",
    "r39_42",
    "r47_54",
)


@dataclass(frozen=True, slots=True)
class Fm27SpanLimits:
    """Allocation and work ceilings, independent of counts claimed by the input."""

    maximum_span_bytes: int = 64 * 1024**2
    maximum_frame_bytes: int = 8 * 1024**2
    maximum_candidates: int = 100_000
    maximum_fixtures: int = 100_000
    maximum_rules: int = 4096
    maximum_parent_bytes: int = 1024**2
    maximum_event_rows: int = 4096
    maximum_interstitials: int = 64
    maximum_rounds: int = 80
    maximum_prizes: int = 64
    maximum_tie_breaks: int = 16

    def __post_init__(self) -> None:
        if any(getattr(self, field) <= 0 for field in self.__dataclass_fields__):
            raise ValueError("FM27 span limits must all be positive")


_DEFAULT_LIMITS = Fm27SpanLimits()


@dataclass(frozen=True, slots=True)
class Fm27Fixture:
    """A raw core; status belongs to a preceding, completely closed sibling path.

    Unowned status is None, never False. The raw time bits are not a verified time of
    day. A non-strict core exists only after its path closed on a strict right anchor.
    """

    offset: int
    stage_id: int | None
    stadium_ordinal: int | None
    home_team_id: int
    away_team_id: int
    date: date
    packed_kick_off: int
    strict_anchor: bool
    played: bool | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    status_source: Literal["unowned", "sibling_prefix"] = "unowned"
    unsupported_fields: tuple[str, ...] = _UNSUPPORTED_FIXTURE_FIELDS


@dataclass(frozen=True, slots=True)
class Fm27RulesRound:
    """A completely counted row. Numeric fields retain raw, unidentified meanings."""

    date: date
    raw_b5: int
    raw_number: int
    raw_u32: int
    raw_byte13: int
    unsupported_fields: tuple[str, ...] = ("round_number_meaning", "extra_fields")


@dataclass(frozen=True, slots=True)
class Fm27Rules:
    """A closed counted parent, with inconsistent promotion copies left unknown."""

    offset: int
    promotion_quad: tuple[int, int, int, int] | None
    tie_breaks: tuple[int, ...]
    prize_money: tuple[int, ...]
    rounds: tuple[Fm27RulesRound, ...]
    interstitial_records: int
    unsupported_fields: tuple[str, ...] = (
        "competition_id",
        "promotion_quad_meanings",
        "money_unit",
        "interstitial_meanings",
    )


@dataclass(frozen=True, slots=True)
class Fm27Span:
    fixtures: tuple[Fm27Fixture, ...]
    rules: tuple[Fm27Rules, ...]
    span_bytes: int
    frame_count: int
    fixture_candidates: int
    rule_candidates: int
    rejected_rule_candidates: int
    recovered_fixtures: int


def _limit_error(what: str) -> CorruptSaveError:
    return CorruptSaveError(f"experimental FM27 span exceeds its {what} limit")


def _buffer_frames(
    frames: Iterable[bytes | bytearray | memoryview], limits: Fm27SpanLimits
) -> tuple[bytes, int]:
    chunks: list[bytes] = []
    size = count = 0
    for frame in frames:
        frame_bytes = frame.nbytes if isinstance(frame, memoryview) else len(frame)
        if frame_bytes > limits.maximum_frame_bytes:
            raise _limit_error("frame byte")
        size += frame_bytes
        if size > limits.maximum_span_bytes:
            raise _limit_error("total byte")
        count += 1
        if count > limits.maximum_candidates:
            raise _limit_error("frame count")
        # Own mutable input rather than retaining references that a producer may mutate.
        chunks.append(bytes(frame))
    return b"".join(chunks), count


def _fixture_core(data: bytes, at: int, *, strict: bool) -> Fm27Fixture | None:
    if at < 12 or at + 53 > len(data) or data[at - 12] != 31:
        return None
    if strict and (data[at + 4] != 255 or data[at + 11] != 255):
        return None
    game_date = decode_date(data, at + 13)
    if game_date is None:
        return None
    home = _U32.unpack_from(data, at)[0]
    away = _U32.unpack_from(data, at + 7)[0]
    if home >= 3_000_000 or away >= 3_000_000 or home == away:
        return None
    stage = _U32.unpack_from(data, at - 11)[0]
    stadium = _U32.unpack_from(data, at - 7)[0]
    if stage != _MISSING and stage >= 200_000:
        return None
    return Fm27Fixture(
        offset=at,
        stage_id=None if stage == _MISSING else stage,
        stadium_ordinal=None if stadium in (0, _MISSING) else stadium - 1,
        home_team_id=home,
        away_team_id=away,
        date=game_date,
        packed_kick_off=_U16.unpack_from(data, at + 13)[0],
        strict_anchor=strict,
    )


def _next_core(
    data: bytes, at: int, end: int, limits: Fm27SpanLimits
) -> tuple[int, bool, int | None, int | None] | None:
    prefix = at + 53
    if prefix >= end:
        return None
    if data[prefix] == 0:
        return prefix + 13, False, None, None
    if data[prefix] != 1:
        return None
    packet = prefix + 1
    if packet + 29 > end or data[packet] != 31:
        return None
    count = _U32.unpack_from(data, packet + 25)[0]
    if count > limits.maximum_event_rows:
        return None
    next_at = packet + 29 + 16 * count + 12
    if next_at > end:
        return None
    home, away = data[packet + 5], data[packet + 9]
    # Only the basic pair has independent result-key corroboration. Other packet
    # score-like bytes remain unsupported instead of being relabelled shootouts.
    if max(home, away) > 40:
        return next_at, True, None, None
    return next_at, True, home, away


def _close_fixture_paths(
    data: bytes, anchors: list[Fm27Fixture], limits: Fm27SpanLimits
) -> tuple[tuple[Fm27Fixture, ...], int]:
    fixtures = {row.offset: row for row in anchors}
    recovered = 0
    for left, right in pairwise(anchors):
        if right.offset - left.offset > limits.maximum_parent_bytes:
            continue
        pending: list[Fm27Fixture] = []
        cursor = left.offset
        while True:
            following = _next_core(data, cursor, right.offset, limits)
            if following is None:
                break
            at, played, home, away = following
            if at > right.offset or at <= cursor:
                break
            if at == right.offset:
                endpoint = replace(
                    right,
                    played=played,
                    home_goals=home,
                    away_goals=away,
                    status_source="sibling_prefix",
                )
                if len(fixtures) + len(pending) > limits.maximum_fixtures:
                    raise _limit_error("fixture count")
                fixtures.update((row.offset, row) for row in pending)
                fixtures[at] = endpoint
                recovered += len(pending)
                break
            middle = _fixture_core(data, at, strict=False)
            if middle is None:
                break
            if len(fixtures) + len(pending) + 1 > limits.maximum_fixtures:
                raise _limit_error("fixture count")
            pending.append(
                replace(
                    middle,
                    played=played,
                    home_goals=home,
                    away_goals=away,
                    status_source="sibling_prefix",
                )
            )
            cursor = at
    return tuple(fixtures[offset] for offset in sorted(fixtures)), recovered


def _rules_parent(data: bytes, at: int, limits: Fm27SpanLimits) -> Fm27Rules | None:
    if at < 28 or at + 9 > len(data) or data[at + 8] != 0:
        return None
    end = min(len(data), at + limits.maximum_parent_bytes)
    first = data[at - 28 : at - 24]
    second = data[at - 24 : at - 20]
    quad = (first[0], first[1], first[2], first[3]) if first == second else None
    cursor = at + 9
    if cursor + 4 > end:
        return None
    count: int = _U32.unpack_from(data, cursor)[0]
    cursor += 4
    if count > limits.maximum_tie_breaks or cursor + count + 4 > end:
        return None
    tie_breaks = tuple(data[cursor : cursor + count])
    cursor += count
    count = _U32.unpack_from(data, cursor)[0]
    cursor += 4
    if count > limits.maximum_prizes or cursor + 4 * count + 4 > end:
        return None
    prizes = tuple(_U32.unpack_from(data, cursor + 4 * index)[0] for index in range(count))
    cursor += 4 * count
    count = _U32.unpack_from(data, cursor)[0]
    cursor += 4
    if count > limits.maximum_rounds:
        return None
    # The first row's kind is the high byte of the parent count, not an extra byte.
    if count:
        cursor -= 1
    rows: list[Fm27RulesRound] = []
    interstitials = 0
    for row_number in range(count):
        if row_number:
            skipped = 0
            while cursor + 4 <= end and data[cursor : cursor + 4] == b"\xff" * 4:
                if skipped >= limits.maximum_interstitials or cursor + 10 > end:
                    return None
                cursor += 10
                skipped += 1
                interstitials += 1
        if cursor + 21 > end or data[cursor] != 0:
            return None
        round_date = decode_date(data, cursor + 1)
        if round_date is None:
            return None
        rows.append(
            Fm27RulesRound(
                date=round_date,
                raw_b5=data[cursor + 5],
                raw_number=data[cursor + 6],
                raw_u32=_U32.unpack_from(data, cursor + 9)[0],
                raw_byte13=data[cursor + 13],
            )
        )
        cursor += 21
    return Fm27Rules(at, quad, tie_breaks, prizes, tuple(rows), interstitials)


def read_fm27_span(
    frames: Iterable[bytes | bytearray | memoryview],
    *,
    clock_year: int,
    limits: Fm27SpanLimits = _DEFAULT_LIMITS,
) -> Fm27Span:
    """Read only explicitly observed raw grammar, with bounded memory and search work.

    Frames may split any field. This initial implementation owns at most the configured
    span buffer plus its chunks, rather than joining an unbounded generator. Failed sibling
    paths and malformed rule parents are discarded whole; no date resynchronization occurs.
    """
    if not 1900 <= clock_year <= 9991:
        raise ValueError("clock_year must leave the observed search window inside u16 years")
    data, frame_count = _buffer_frames(frames, limits)
    years = b"|".join(re.escape(_U16.pack(year)) for year in range(clock_year - 7, clock_year + 9))
    pattern = re.compile(rb"\xff.{6}\xff.{3}(?:" + years + rb")", re.DOTALL)
    anchors: list[Fm27Fixture] = []
    fixture_candidates = 0
    cursor = 0
    while (match := pattern.search(data, cursor)) is not None:
        cursor = match.start() + 1
        fixture_candidates += 1
        if fixture_candidates > limits.maximum_candidates:
            raise _limit_error("candidate count")
        row = _fixture_core(data, match.start() - 4, strict=True)
        if row is not None:
            if len(anchors) >= limits.maximum_fixtures:
                raise _limit_error("fixture count")
            anchors.append(row)
    fixtures, recovered = _close_fixture_paths(data, anchors, limits)
    rules: list[Fm27Rules] = []
    rule_candidates = rejected = 0
    cursor = 0
    while (at := data.find(_RULE_MARKER, cursor)) != -1:
        cursor = at + 1
        rule_candidates += 1
        if fixture_candidates + rule_candidates > limits.maximum_candidates:
            raise _limit_error("candidate count")
        parent = _rules_parent(data, at, limits)
        if parent is None:
            rejected += 1
        else:
            if len(rules) >= limits.maximum_rules:
                raise _limit_error("rule count")
            rules.append(parent)
    return Fm27Span(
        fixtures,
        tuple(rules),
        len(data),
        frame_count,
        fixture_candidates,
        rule_candidates,
        rejected,
        recovered,
    )
