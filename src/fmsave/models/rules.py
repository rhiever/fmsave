"""Competition rules, and the transfer windows the game's rules database carries.

A transfer window is database content rather than career state: the same windows, byte for
byte, are read from every save of one installed database, so they say when a window opens and
closes in a season, not what any one career has done.

The dates are **season-relative**. The save stores a year of 2000 for the season's own start
year and 2001 for the calendar year after it, so a window carries an offset from the season
start rather than a calendar date. Without knowing which season is meant there is no calendar
date to build, so fmsave ships the offset and never a `datetime.date`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class TransferWindow:
    """One transfer window: when it opens and closes, relative to the season start.

    The window carries no name. The save's rules database does hold description strings, but
    none of them belongs to a window record: on the saves measured only six windows in
    fifty-four have a description ending anywhere near the record, and the rest sit hundreds of
    thousands of bytes away. Attaching the nearest one would put an unrelated label on a
    window, so no label ships and the dates are the whole of what a window says.

    **A save holds more rows than it has distinct windows.** On the saves measured the reader
    returns 54 rows of which 22 are distinct: 17 of those appear twice and 5 appear four times.
    Rows that repeat are equal in every field this record carries, so a caller who wants one
    row per distinct window can drop the repeats and lose nothing it is able to see. A record
    carries a mapping and so is not hashable, which rules out a `set`; equality works as usual,
    so keep the first of each instead::

        distinct_windows: list[TransferWindow] = []
        for window in career_save.transfer_windows():
            if window not in distinct_windows:
                distinct_windows.append(window)

    Why the rules database repeats a window is **not established**. What was measured is that a
    repeat carries no key of its own that fmsave drops: of the 32 repeated records, 26 repeat
    the whole underlying record exactly, tag for tag and value for value, including the id each
    of its two date sub-lists carries, and the other 6 differ only in a description and two
    unidentified tags. Nothing inside a window record tells one copy from another, so whatever
    separates them, if anything does, sits outside the record and this reader does not read it.
    In particular nothing measured here makes them per-competition or per-nation copies; that
    remains a guess. The count is the anchored walk's own, not a decode that counts a record
    twice, and both saves measured give the same 54 rows and the same 22 distinct windows.

    Attributes:
        opens_day: Day of the month the window opens, 1 to 31.
        opens_month: Month the window opens, 1 to 12.
        opens_season_year_offset: Which season year the window opens in: 0 is the season's own
            start year and 1 the calendar year after it. There is no calendar date without a
            season, so this is an offset and never a date.
        closes_day: Day of the month the window closes, 1 to 31.
        closes_month: Month the window closes, 1 to 12.
        closes_season_year_offset: Which season year the window closes in, as
            opens_season_year_offset.
        unknown: Numeric fields with no known meaning. "close_time" is the value stored
            against the window's closing-time tag, which looks like an hour and minute on a
            24-hour clock but is not named, because the game's own Rules screen shows no time
            of day to pin it to. "window_type" is a small code the record carries on about two
            windows in five and no displayed label explains (unconfirmed).
    """

    opens_day: int
    opens_month: int
    opens_season_year_offset: int
    closes_day: int
    closes_month: int
    closes_season_year_offset: int
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("close_time", "window_type")


register_field_statuses(
    TransferWindow,
    verified=(
        "opens_day",
        "opens_month",
        "opens_season_year_offset",
        "closes_day",
        "closes_month",
        "closes_season_year_offset",
    ),
    unconfirmed=("unknown",),
)
