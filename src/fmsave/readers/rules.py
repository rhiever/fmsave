"""Competition rules and transfer windows, read from the span and from `game_db`.

**Competition rules come from the preamble blocks one span pass already collected**, so this
reader walks nothing of its own: it decodes, keys and counts what `SpanRecords.rules_blocks`
holds. No block names a competition, so no index is borrowed and no join is made.

**The tagged rules groups are not read in this release.** The save's rules database does hold
groups of squad and financial rules, and a strict walk anchored on the wage-percentage tag
does pin four of them per save, identical in shape and count on both saves measured. They are
still not shipped, for reasons that are measured rather than cautious:

- none of the four carries a string of any kind, so there is no group name to return;
- none carries the value tag the squad-size rule was supposed to be read through, so that rule
  is not in them at all;
- the wider population the groups were meant to come from is not bounded: of 324 candidates
  for the home-grown tag, 116 do not sit at a record boundary at all and the rest fall into
  three unrelated shapes;
- and no displayed in-game label pins the meaning of any value the groups hold, so naming one
  would rest on another tool's guess rather than on evidence.

Walking from the description marker, which is the obvious route, decodes nothing: on both
saves all 1,707 strict walks from it stop before reaching any rules tag.

Transfer windows are read from the tagged stream below.

The rules database is written as a tagged stream: a run of
`<4-byte tag, byte-reversed><01><type><value>` records. A transfer window is one such run,
opening with its start-date sub-list and ending at its closing-time value.

**Why the closing time is what recognises a window.** The date tags a window uses are shared
by many kinds of record in this stream. On the saves measured 1,766 start-date sub-lists carry
a complete, in-range date pair and only 54 of them also carry a closing time, so accepting on
the dates alone would return every dated record the rules database holds. Acceptance is
structural throughout: the record carries no description of its own, and the description
strings elsewhere in the stream belong to other records, so nothing here reads text.

The walk is the strict one in `fmsave._scan`, which stops at the first byte that is not a
record rather than hunting for the next one. That is what keeps a layout that has moved
visibly empty instead of quietly short.

**The rules database stores its windows more than once.** Every window record the stream holds
is returned, which is more records than there are distinct windows: on the saves measured 54
records and 22 distinct windows. The repeats are neither a decode fault nor dropped here, since
dropping them would hide a change in what a save stores behind a number that never moved.
`fmsave.models.rules.TransferWindow` sets out what a repeated row means and what a caller can
do about it.
"""

from __future__ import annotations

from fmsave._frozen import FrozenMapping
from fmsave._layouts import TaggedStreamLayout, TransferWindowLayout, find_layout
from fmsave._reader_stats import RulesStats, TransferWindowStats
from fmsave._scan import iter_tagged_values
from fmsave.models.rules import CompetitionRules, RulesBlockKind, RulesRound, TransferWindow
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.span import RawRulesBlock, SpanRecords

CLOSE_TIME_KEY = "close_time"
WINDOW_TYPE_KEY = "window_type"
PROMOTION_BYTE2_KEY = CompetitionRules.UNKNOWN_KEYS[0]
TIE_BREAK_KEYS = CompetitionRules.UNKNOWN_KEYS[1:]
ROUND_KIND_KEY, ROUND_B5_KEY = RulesRound.UNKNOWN_KEYS


def _preamble_unknown(block: RawRulesBlock) -> FrozenMapping[str, int]:
    """The quad's unidentified byte and the tie-break codes, in the order the block lists them.

    The tie-break codes are paired with the declared keys rather than numbered from the list,
    so a block carrying more codes than there are keys can never produce a key the record does
    not declare. No displayed label names a tie-break code, so they ship as raw numbers.
    """
    unknown: dict[str, int] = {}
    if block.promotion_byte2 is not None:
        unknown[PROMOTION_BYTE2_KEY] = block.promotion_byte2
    for key, code in zip(TIE_BREAK_KEYS, block.tie_breaks, strict=False):
        unknown[key] = code
    return FrozenMapping(unknown)


def _rounds_of(block: RawRulesBlock) -> tuple[RulesRound, ...]:
    return tuple(
        RulesRound(
            number=raw_round.number,
            date=raw_round.date,
            match_count=raw_round.match_count,
            unknown=FrozenMapping({ROUND_KIND_KEY: raw_round.kind, ROUND_B5_KEY: raw_round.b5}),
        )
        for raw_round in block.rounds
    )


def build_competition_rules(
    span_records: SpanRecords,
) -> tuple[tuple[CompetitionRules, ...], RulesStats]:
    """Key the span's rules preamble blocks into rows, in the order the span stores them.

    Every row carries `competition_id` None. The save stores no link from a block to a
    competition and the hunt for one came back empty, so there is nothing to join through and
    no index is read: a caller matches a division by `fixtures_per_club` against the shape
    `league_tables()` reports instead. `club_count` cannot serve that, being None on every row,
    because no fixed position in the block carries it.

    A block whose promotion quad was not written twice keeps its lists and its calendar and
    leaves the four quad fields empty, rather than being dropped.
    """
    blocks = span_records.rules_blocks
    rows = tuple(
        CompetitionRules(
            kind=RulesBlockKind.PREAMBLE,
            competition_id=None,
            competition_name=None,
            club_count=block.club_count,
            fixtures_per_club=len(block.rounds) or None,
            promotion_places=block.promotion_places,
            playoff_places=block.playoff_places,
            relegation_places=block.relegation_places,
            administration_points_deduction=block.administration_points_deduction,
            prize_money=block.prize_money,
            rounds=_rounds_of(block),
            unknown=_preamble_unknown(block),
        )
        for block in blocks
    )
    stats = RulesStats(
        markers=span_records.rules_markers,
        blocks=len(blocks),
        fully_parsed=sum(1 for block in blocks if block.fully_parsed),
        quad_doubled=sum(1 for block in blocks if block.promotion_places is not None),
        rows=len(rows),
    )
    return rows, stats


def find_transfer_window_layouts(
    game_db_schema: int | None, build: str
) -> tuple[TaggedStreamLayout, TransferWindowLayout]:
    """The tagged-stream and transfer-window layouts for a `game_db` schema, build as fallback."""
    return (
        find_layout(TaggedStreamLayout, GAME_DB_SECTION, game_db_schema, build).layout,
        find_layout(TransferWindowLayout, GAME_DB_SECTION, game_db_schema, build).layout,
    )


def _season_dates(
    group: dict[str, int], layout: TransferWindowLayout
) -> tuple[int, int, int] | None:
    """(day, month, season year offset) for one date sub-list, or None when it does not hold."""
    day = group.get(layout.day_tag)
    month = group.get(layout.month_tag)
    year = group.get(layout.year_tag)
    if day is None or month is None or year is None:
        return None
    lowest_day, highest_day = layout.day_range
    lowest_month, highest_month = layout.month_range
    lowest_year, highest_year = layout.year_range
    if not lowest_day <= day <= highest_day:
        return None
    if not lowest_month <= month <= highest_month:
        return None
    if not lowest_year <= year <= highest_year:
        return None
    return day, month, year - layout.season_year_base


def _decode_window(
    game_db: bytes,
    marker_offset: int,
    tagged_layout: TaggedStreamLayout,
    layout: TransferWindowLayout,
) -> tuple[TransferWindow | None, bool]:
    """Decode one candidate: the window when it holds, and whether a closing time was found.

    A sub-list holds more members than its three dates, so nothing is counted down: the date
    tags seen while a sub-list is open belong to it, and the next sub-list or the closing time
    closes it.
    """
    scan_end = min(marker_offset + layout.window_scan_bytes, len(game_db))
    groups: dict[str, dict[str, int]] = {}
    open_group: dict[str, int] | None = None
    close_time: int | None = None
    window_type: int | None = None
    date_tags = (layout.day_tag, layout.month_tag, layout.year_tag)
    for tagged in iter_tagged_values(game_db, marker_offset, scan_end, tagged_layout):
        tag = tagged.tag
        if tagged.kind == tagged_layout.list_type and tag in (layout.start_tag, layout.end_tag):
            open_group = {}
            groups[tag] = open_group
            continue
        value = tagged.value
        if not isinstance(value, int):
            continue
        if tag == layout.window_type_tag:
            window_type = value
        elif tag == layout.close_time_tag:
            close_time = value
            break
        elif open_group is not None and tag in date_tags:
            open_group[tag] = value
    if close_time is None:
        return None, False
    start_group = groups.get(layout.start_tag)
    end_group = groups.get(layout.end_tag)
    if start_group is None or end_group is None:
        return None, True
    opens = _season_dates(start_group, layout)
    closes = _season_dates(end_group, layout)
    if opens is None or closes is None:
        return None, True
    unknown = {CLOSE_TIME_KEY: close_time}
    if window_type is not None:
        unknown[WINDOW_TYPE_KEY] = window_type
    return (
        TransferWindow(
            opens_day=opens[0],
            opens_month=opens[1],
            opens_season_year_offset=opens[2],
            closes_day=closes[0],
            closes_month=closes[1],
            closes_season_year_offset=closes[2],
            unknown=FrozenMapping(unknown),
        ),
        True,
    )


def read_transfer_windows(
    game_db: bytes, tagged_layout: TaggedStreamLayout, layout: TransferWindowLayout
) -> tuple[tuple[TransferWindow, ...], TransferWindowStats]:
    """Every transfer window the rules database holds, in the order `game_db` stores them.

    Each occurrence of the start-date sub-list is a candidate; the walk from it decides. A
    candidate with no closing time is not a window and is not counted as a failure, because
    most start-date sub-lists in this stream belong to other kinds of record.
    """
    marker = layout.marker
    windows: list[TransferWindow] = []
    marker_count = 0
    incomplete = 0
    marker_offset = game_db.find(marker)
    while marker_offset >= 0:
        marker_count += 1
        window, carried_close_time = _decode_window(game_db, marker_offset, tagged_layout, layout)
        if window is not None:
            windows.append(window)
        elif carried_close_time:
            incomplete += 1
        marker_offset = game_db.find(marker, marker_offset + 1)
    stats = TransferWindowStats(markers=marker_count, windows=len(windows), incomplete=incomplete)
    return tuple(windows), stats
