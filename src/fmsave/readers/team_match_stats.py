"""Reading per-match team statistics from the match report store.

Each report is its own compressed frame, listed in the store's page index. A report holds a
header, then per team a team block and one record per player in the matchday squad. Squads
are framed by structure alone, never by whether the values look plausible.
"""

from __future__ import annotations

import datetime
import math
import re
import struct
import sys
from collections import Counter
from dataclasses import dataclass

from fmsave._errors import CorruptSaveError
from fmsave._layouts import MatchReportLayout
from fmsave._reader_stats import TeamMatchStatsStats
from fmsave.models.team_match_stats import TeamMatchStats
from fmsave.readers._common import MATCH_REPORTS_SECTION, layout_mismatch

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

_U32 = struct.Struct("<I")
_ENTRY = struct.Struct("<III")
_F32 = struct.Struct("<f")
_YEAR_ONE = datetime.datetime(1, 1, 1)  # noqa: DTZ001 - the save stores naive local times


def index_entries(
    section: bytes, layout: MatchReportLayout, file_name: str, *, check_borrowed: bool = False
) -> tuple[tuple[int, int], ...]:
    """The (start, size) of every report frame the page index lists, in index order.

    Raises:
        ReaderCheckError: A page is missing, or an entry points outside the section.
    """
    if len(section) < layout.first_page_offset:
        raise layout_mismatch(
            file_name,
            "the match report index is cut short",
            MATCH_REPORTS_SECTION,
            share_detail=True,
        )
    page_count = _U32.unpack_from(section, layout.page_count_offset)[0]
    entries: list[tuple[int, int]] = []
    search_from = layout.first_page_offset
    for page in range(page_count):
        name = layout.page_name_prefix + str(page).encode()
        signature = struct.pack("<II", page, len(name)) + name
        at = section.find(signature, search_from)
        if at < 0 or (page == 0 and at != layout.first_page_offset):
            raise layout_mismatch(
                file_name,
                f"match report page {page} is missing",
                MATCH_REPORTS_SECTION,
                share_detail=True,
            )
        after_name = at + len(signature)
        marker = section[after_name : after_name + layout.page_marker_bytes]
        count_at = after_name + layout.entry_count_offset_after_name
        if count_at + 4 > len(section):
            raise layout_mismatch(
                file_name,
                f"match report page {page} is cut short",
                MATCH_REPORTS_SECTION,
                share_detail=True,
            )
        count = _U32.unpack_from(section, count_at)[0]
        table_at = count_at + 4
        data_at = table_at + count * layout.entry_bytes + layout.data_header_bytes
        if data_at > len(section) or (
            section[
                data_at - layout.data_header_bytes : data_at
                - layout.data_header_bytes
                + layout.page_marker_bytes
            ]
            != marker
        ):
            raise layout_mismatch(
                file_name,
                f"match report page {page} has no data header",
                MATCH_REPORTS_SECTION,
                share_detail=True,
            )
        search_from = data_at
        for _report_id, offset, size in _ENTRY.iter_unpack(
            section[table_at : table_at + count * layout.entry_bytes]
        ):
            start = data_at + offset
            if size == 0 or start + size > len(section):
                raise layout_mismatch(
                    file_name,
                    "a match report runs past the section",
                    MATCH_REPORTS_SECTION,
                    share_detail=True,
                )
            entries.append((start, size))
            search_from = max(search_from, start + size)
    if check_borrowed and search_from < len(section):
        # The store may carry a tail after its last report. Only an empty index or
        # a structurally named next page contradicts the declared page count.
        next_page = layout.page_name_prefix + str(page_count).encode()
        signature = struct.pack("<II", page_count, len(next_page)) + next_page
        if not entries or section.find(signature, search_from) >= 0:
            raise layout_mismatch(
                file_name,
                "the match report index leaves trailing data",
                MATCH_REPORTS_SECTION,
                share_detail=True,
            )
    previous_end = 0
    for start, size in sorted(entries):
        if start < previous_end:
            raise layout_mismatch(
                file_name,
                "two match reports overlap",
                MATCH_REPORTS_SECTION,
                share_detail=True,
            )
        previous_end = start + size
    return tuple(entries)


def _decompress(frame: bytes | memoryview, layout: MatchReportLayout) -> bytes | None:
    """The report in one frame, or None when the frame does not decompress exactly."""
    decompressor = zstd.ZstdDecompressor()
    try:
        report = decompressor.decompress(frame, max_length=layout.maximum_report_bytes + 1)
    except zstd.ZstdError:
        return None
    if (
        len(report) > layout.maximum_report_bytes
        or not decompressor.eof
        or decompressor.unused_data
    ):
        return None
    return report


@dataclass(frozen=True, slots=True)
class _Header:
    competition_id: int
    home_team_id: int
    away_team_id: int
    kick_off: datetime.datetime


@dataclass(frozen=True, slots=True)
class _Squads:
    home: tuple[int, ...]
    away: tuple[int, ...]
    detailed: bool


def _header(report: bytes, layout: MatchReportLayout) -> _Header | None:
    at = layout.competition_id_offset
    if len(report) < layout.team_search_start * 2 or report[at - 1] != layout.competition_marker:
        return None
    home_at = report.find(layout.team_marker, layout.team_search_start)
    # The marker also occurs inside venue IDs and names. Team entries are consecutive.
    while home_at >= 0 and not report.startswith(
        layout.team_marker, home_at + layout.team_entry_bytes
    ):
        home_at = report.find(layout.team_marker, home_at + 1)
    if home_at < 0:
        return None
    away_at = home_at + layout.team_entry_bytes
    skip = len(layout.team_marker)
    if away_at + skip + _U32.size > len(report):
        return None
    minutes = _U32.unpack_from(report, layout.kick_off_offset)[0]
    try:
        kick_off = _YEAR_ONE + datetime.timedelta(minutes=minutes)
    except OverflowError:
        return None
    return _Header(
        competition_id=_U32.unpack_from(report, at)[0],
        home_team_id=_U32.unpack_from(report, home_at + skip)[0],
        away_team_id=_U32.unpack_from(report, away_at + skip)[0],
        kick_off=kick_off,
    )


def _is_marked(report: bytes, anchor: int, layout: MatchReportLayout) -> bool:
    first, second = layout.anchor_marker_offsets
    return (
        layout.minimum_anchor <= anchor
        and anchor + second < len(report)
        and report[anchor + first] == layout.anchor_marker
        and report[anchor + second] == layout.anchor_marker
    )


def _record_length(report: bytes, anchor: int, layout: MatchReportLayout) -> int | None:
    """The length of the player record at `anchor`, or None when its variable parts misframe."""
    at = anchor + layout.event_count_offset
    if at >= len(report):
        return None
    items = report[at]
    at += 1
    for _ in range(items):
        count_at = at + layout.event_entry_count_offset
        if count_at >= len(report):
            return None
        at += layout.event_item_header_bytes + report[count_at] * layout.event_entry_bytes
    flag_at = at + layout.optional_flag_gap
    if flag_at >= len(report):
        return None
    flag = report[flag_at]
    if flag not in (0, 1):
        return None
    base_flag_at = anchor + layout.event_count_offset + 1 + layout.optional_flag_gap
    return layout.record_bytes + (flag_at - base_flag_at) + flag * layout.optional_block_bytes


def _walk(head: int, successor: dict[int, int]) -> list[int]:
    walk = [head]
    while walk[-1] in successor:
        walk.append(successor[walk[-1]])
    return walk


def _squads(
    report: bytes, layout: MatchReportLayout, seed_pattern: re.Pattern[bytes]
) -> _Squads | None:
    """The anchors of the home and away squads, or None when either does not frame whole.

    Seeds must leave room for the team fields that precede the squad. Each seed is walked
    record by record while the next record carries its markers. The two longest walks are
    the squads, home first. Both must be at least a starting eleven. In the summary format,
    the block between them must be too short to hide a missing record. No walk of two or more
    records may follow the away squad, which would be a squad cut in two.
    """
    # An earlier header hit can join a real walk after its first player. It cannot
    # start a squad if there is no room for that squad's team fields.
    first_possible_anchor = max(back for _, _, back in layout.team_fields)
    seeds = sorted(
        {
            match.start() - 1
            for match in seed_pattern.finditer(report, first_possible_anchor + 1)
            if _is_marked(report, match.start() - 1, layout)
        }
    )
    successor: dict[int, int] = {}
    for seed in seeds:
        anchor = seed
        while anchor not in successor:
            length = _record_length(report, anchor, layout)
            if length is None or not _is_marked(report, anchor + length, layout):
                break
            successor[anchor] = anchor + length
            anchor += length
    reached = set(successor.values())
    # Each anchor's walk length is worked out once, so walks that merge cost nothing twice.
    remaining: dict[int, int] = {}
    for seed in seeds:
        path: list[int] = []
        anchor = seed
        while anchor not in remaining and anchor in successor:
            path.append(anchor)
            anchor = successor[anchor]
        known = remaining.setdefault(anchor, 1)
        for walked in reversed(path):
            known += 1
            remaining[walked] = known
    heads = [seed for seed in seeds if seed not in reached]
    longest = sorted(sorted(heads, key=lambda head: remaining[head], reverse=True)[:2])
    if len(longest) != 2:
        return None
    home = _walk(longest[0], successor)
    away = _walk(longest[1], successor)
    if min(len(home), len(away)) < layout.minimum_squad:
        return None
    detailed = all(
        home[0] - back >= 0 and report[home[0] - back] == layout.detail_marker
        for back in layout.detail_marker_offsets
    )
    home_length = _record_length(report, home[-1], layout)
    away_length = _record_length(report, away[-1], layout)
    if home_length is None or away_length is None:
        return None
    gap = away[0] - (home[-1] + home_length)
    shortest = layout.team_block_gap
    if detailed:
        if gap < shortest:
            return None
    elif not (
        shortest <= gap < shortest + layout.record_bytes
        and (gap - shortest) % layout.team_block_gap_step == 0
    ):
        return None
    away_end = away[-1] + away_length
    if any(head >= away_end and remaining[head] > 1 for head in heads):
        return None
    return _Squads(home=tuple(home), away=tuple(away), detailed=detailed)


def _read(report: bytes, code: str, at: int, layout: MatchReportLayout) -> float:
    value = struct.unpack_from("<" + code, report, at)[0]
    # Unused float slots hold NaN or junk on players who never took part.
    if code == "f" and not abs(value) < layout.float_limit:
        return 0.0
    return value


def _team_values(
    report: bytes, anchors: tuple[int, ...], detailed: bool, layout: MatchReportLayout
) -> dict[str, int | float | None]:
    values: dict[str, int | float | None] = {"players": len(anchors)}
    for name, code, offset in layout.player_fields:
        total = sum(_read(report, code, anchor + offset, layout) for anchor in anchors)
        values[name] = float(total) if code == "f" else int(total)
    # The game adds distances in 32-bit floats, player by player, and truncates the total on
    # screen, so a 64-bit sum can show a kilometre more.
    code, offset = layout.distance_field
    distance = 0.0
    for anchor in anchors:
        distance = _F32.unpack(_F32.pack(distance + _read(report, code, anchor + offset, layout)))[
            0
        ]
    values["distance_km"] = distance * (layout.detailed_distance_scale if detailed else 1.0)
    code, offset = layout.progressive_passes_field
    values["progressive_passes"] = (
        int(sum(_read(report, code, anchor + offset, layout) for anchor in anchors))
        if detailed
        else None
    )
    for name, code, back in layout.team_fields:
        values[name] = int(_read(report, code, anchors[0] - back, layout))
    return values


def _possession(home_completed: int, away_completed: int) -> tuple[int, int]:
    total = home_completed + away_completed
    if total == 0:
        return 50, 50
    home = round(100 * home_completed / total)
    return home, 100 - home


def _shares_half_up(home: int, away: int) -> tuple[int, int]:
    total = home + away
    if total == 0:
        return 0, 0
    return math.floor(100 * home / total + 0.5), math.floor(100 * away / total + 0.5)


def read_team_match_stats(
    section: bytes, layout: MatchReportLayout, file_name: str, *, check_borrowed: bool = False
) -> tuple[list[TeamMatchStats], TeamMatchStatsStats]:
    """Two rows for every report whose squads frame and whose key no other report shares.

    Each report's values are taken as soon as it decompresses, so only one report is held.

    Raises:
        ReaderCheckError: The page index does not walk, or two reports overlap.
        CorruptSaveError: The reports decompress to more than the layout allows.
    """
    entries = index_entries(section, layout, file_name, check_borrowed=check_borrowed)
    seed_pattern = re.compile(b"(?=" + re.escape(layout.anchor_run) + b")")
    view = memoryview(section)
    budget = layout.maximum_expansion * len(section) + layout.maximum_report_bytes
    framed: list[tuple[_Header, bool, dict[str, int | float | None], dict[str, int | float | None]]]
    framed = []
    decompressed = without_header = incomplete = detailed = 0
    for start, size in entries:
        report = _decompress(view[start : start + size], layout)
        if report is None:
            continue
        budget -= len(report)
        if budget < 0:
            raise CorruptSaveError(
                f"{file_name}: section {MATCH_REPORTS_SECTION!r} decompresses to more than "
                "its reports can hold"
            )
        decompressed += 1
        header = _header(report, layout)
        if header is None:
            without_header += 1
            continue
        squads = _squads(report, layout, seed_pattern)
        try:
            if squads is None:
                raise struct.error
            home = _team_values(report, squads.home, squads.detailed, layout)
            away = _team_values(report, squads.away, squads.detailed, layout)
        except struct.error:
            incomplete += 1
            continue
        detailed += squads.detailed
        framed.append((header, squads.detailed, home, away))

    if check_borrowed and entries and not framed:
        raise layout_mismatch(
            file_name,
            "no indexed match report could be decoded",
            MATCH_REPORTS_SECTION,
            share_detail=True,
        )

    # Two reports with one key cannot be told apart, so neither is used.
    key_counts = Counter(header for header, _, _, _ in framed)
    rows: list[TeamMatchStats] = []
    for header, is_detailed, home, away in framed:
        if key_counts[header] > 1:
            continue
        home_possession, away_possession = _possession(
            int(home["passes_completed"] or 0), int(away["passes_completed"] or 0)
        )
        home_ball, away_ball = _shares_half_up(
            int(home.pop("ball_distribution_units") or 0),
            int(away.pop("ball_distribution_units") or 0),
        )
        for team_id, is_home, values, possession, ball in (
            (header.home_team_id, True, home, home_possession, home_ball),
            (header.away_team_id, False, away, away_possession, away_ball),
        ):
            rows.append(
                TeamMatchStats(
                    competition_id=header.competition_id,
                    home_team_id=header.home_team_id,
                    away_team_id=header.away_team_id,
                    date=header.kick_off.date(),
                    kick_off_time=header.kick_off.time(),
                    team_id=team_id,
                    is_home=is_home,
                    detailed_report=is_detailed,
                    possession_percent=possession,
                    ball_distribution_percent=ball,
                    **values,  # type: ignore[arg-type]
                )
            )
    if check_borrowed and entries and not rows:
        raise layout_mismatch(
            file_name,
            "all decoded match reports have ambiguous keys",
            MATCH_REPORTS_SECTION,
            share_detail=True,
        )
    stats = TeamMatchStatsStats(
        entries=len(entries),
        decompressed=decompressed,
        without_header=without_header,
        incomplete=incomplete,
        framed=len(framed),
        detailed=detailed,
        duplicate_keys=sum(1 for count in key_counts.values() if count > 1),
        rows=len(rows),
    )
    return rows, stats
