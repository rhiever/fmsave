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

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
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


class RulesBlockKind(StrEnum):
    """Which structure a competition-rules row was read from.

    Derived by fmsave from where the row came from, never read as a code.

    `GROUP` is declared and **not used in this release**: no row carries it. The save's rules
    database does hold tagged groups of squad and financial rules, but nothing readable ties a
    group to a competition, none of the groups found carries a name, and no displayed label
    pins the meaning of the values they hold, so fmsave ships none of them rather than shipping
    guesses. The member is declared now so that adding those rows later adds rows to this table
    instead of changing what `kind` can be.
    """

    PREAMBLE = "preamble"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class RulesRound:
    """One round of a competition's calendar, as the rules block stores it.

    Attributes:
        number: The round's number, counting from one. A round the save does not number
            stores a value that reads here as 256 rather than as a guess (unconfirmed).
        date: The date the round is played on, or None when the stored date does not decode
            (unconfirmed).
        match_count: How many matches the round holds (unconfirmed).
        unknown: Numeric fields with no known meaning. "kind" and "b5" are the two
            unidentified bytes the round record carries (unconfirmed).
    """

    number: int
    date: datetime.date | None
    match_count: int
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("kind", "b5")


@dataclass(frozen=True, slots=True)
class CompetitionRules:
    """One competition-rules block: promotion and relegation, prize money and the calendar.

    **The save does not store which competition a rules block belongs to, so
    `competition_id` is None on every row.** That is a measured result, not an omission: for
    200 blocks on each of two saves, every `u32` in the 256 bytes before the block's marker and
    the 256 bytes after its end was tested against the competition ids the stage table holds,
    and no offset named a known competition on even 90% of blocks while varying from block to
    block. The one offset that came close sits inside the promotion quad itself, where small
    counts collide with the low end of the id space, and it took five distinct values across
    200 blocks. Match a division instead by `fixtures_per_club` against the shape
    `league_tables()` reports, which carries a club count of its own. **`club_count` on this
    record cannot serve that**: no fixed position in the block carries it, so it is None on
    every row.

    **The field meanings are weakly sourced.** They come from checks against one division's
    Rules screen in another tool, never re-verified here, and because no row can be tied to a
    competition, the owner's own Rules screen cannot be matched to a block either. What the
    corpus does show is that blocks of the right shape exist: 17 blocks on one save and 16 on
    the other hold 38 rounds, and 5 and 6 of those also hold 3 relegation places, which is the
    shape of the division that screen describes. That is corroboration, not verification: with
    no competition to match a block by, no block can be tied to the screen at all, so **no
    field on this record has been checked against the game** and every one is unconfirmed.

    The squad and financial rules the save's rules database holds (a home-grown minimum, a
    maximum squad size, a salary cap and a wage-bill percentage) are **not** in this release.
    They live in tagged groups that carry no name, no competition and no displayed label to pin
    them, so fmsave ships no field for them rather than a field whose meaning rests on another
    tool's guess. Adding them later adds columns and renames nothing.

    Transfer windows are their own table: see `Save.transfer_windows()`.

    Attributes:
        kind: Which structure the row was read from. Every row in this release is PREAMBLE
            (unconfirmed).
        competition_id: Always None; the save stores no link from a block to a competition
            (unconfirmed).
        competition_name: Always None, since there is no competition to name (unconfirmed).
        club_count: How many clubs the competition holds. **Always None in this release**: no
            fixed offset from the block's marker carries it on the corpus, so it is not
            guessed (unconfirmed).
        fixtures_per_club: How many matches each club plays, which is the number of rounds the
            block holds; None when no round decoded (unconfirmed).
        promotion_places: How many clubs are promoted, or None when the block's two copies of
            the promotion quad differ (unconfirmed).
        playoff_places: How many clubs enter a promotion play-off, or None as promotion_places
            (unconfirmed).
        relegation_places: How many clubs are relegated, or None as promotion_places
            (unconfirmed).
        administration_points_deduction: Points deducted from a club in administration.
            **Always None in this release**, for the reason club_count is (unconfirmed).
        prize_money: Prize money by finishing position, in the save's base currency, in
            finishing order. Empty on most blocks: only about one block in eight carries a
            prize list at all (unconfirmed).
        rounds: The competition's calendar, in stored order (unconfirmed).
        unknown: Numeric fields with no known meaning. "promotion_byte2" is the third byte of
            the promotion quad. "tie_break_00" to "tie_break_15" are the tie-break codes the
            block lists, in order, and are absent past the end of that list; no displayed
            label names any of them, so they ship as raw numbers (unconfirmed).
    """

    kind: RulesBlockKind
    competition_id: int | None
    competition_name: str | None
    club_count: int | None
    fixtures_per_club: int | None
    promotion_places: int | None
    playoff_places: int | None
    relegation_places: int | None
    administration_points_deduction: int | None
    prize_money: tuple[int, ...]
    rounds: tuple[RulesRound, ...]
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("promotion_byte2",) + tuple(
        f"tie_break_{index:02d}" for index in range(16)
    )


# Nothing this reader returns has been checked against the game. The Rules screen the field
# meanings come from describes one division, and no block can be tied to a division, because no
# block names a competition and the hunt for a link came back empty. A shape that matches the
# screen is corroboration, not a check, so every field here is unconfirmed.
register_field_statuses(
    RulesRound,
    unconfirmed=("number", "date", "match_count", "unknown"),
)
register_field_statuses(
    CompetitionRules,
    unconfirmed=(
        "kind",
        "competition_id",
        "competition_name",
        "club_count",
        "fixtures_per_club",
        "promotion_places",
        "playoff_places",
        "relegation_places",
        "administration_points_deduction",
        "prize_money",
        "rounds",
        "unknown",
    ),
)
