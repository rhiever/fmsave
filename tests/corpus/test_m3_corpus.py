"""Corpus checks for the ground, club-operations, staff, medical, training and tactics readers.

Values read from a save never appear in an assert or a message: each check reduces to a
boolean or to a count of records that broke an invariant, and failures are reported by file
name and check name only.

Every check here is structural. What each one asserts is a property the decode must have
whatever career a save holds, never a figure one career happens to produce, so a bound here
is a floor a working reader clears on any save rather than a fingerprint of these ones.

**What this module may not contain.** Three shapes of check look like evidence and are not,
and each one has been removed from here at least once:

- A check the reader cannot fail, because it only ever emits what the check asks for. A
  reference resolved through an index is absent when it does not resolve, so "every reference
  resolves" is a statement about the reader's own code and not about the save; a key the reader
  generates with `enumerate` is unique whatever the bytes said; a date counted back from the
  save's clock steps by a month because it was built to.
- A check that restates a bound the reader already enforces. Those raise `ReaderCheckError`
  before the assert can run, so the assert can only ever pass. The gate is the test.
- A check on a quantity that scores the same whether the decode is right or wrong. Several were
  measured during this milestone and rejected as gates for exactly that reason, and they are no
  better here than they were there.

Every check below therefore says, in a comment, what a wrong decode would do to it, and every
one of them measures something no shipped gate measures.

The whole-report check that every reader is "ok" with every gate applied and passed, and the
coverage regression against the recorded ranges, both live in `test_corpus_readers.py` and cover
every reader already.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
from pathlib import Path

import pytest

import fmsave
from tests.corpus.reporting import CorpusMismatches

pytestmark = [pytest.mark.corpus]

# Only the grounds a career has a reason to name carry one; the rest are the database's own
# unnamed entries. A decode that read a name out of the row body, or that lost the length in
# front of an inline name and ran on into the next row, names far more rows than this.
STADIUM_NAMED_SHARE_LIMIT = 0.01
# A ground's home clubs are voted for out of the calendar. The vote is keyed by club, so it
# cannot give one club two grounds however wrong it is; what it can do is give one ground every
# club in a country, which is what a fixture-to-ground ordinal that had collapsed onto a single
# row looks like. The corpus's busiest ground lists twelve.
STADIUM_HOME_CLUBS_LIMIT = 16
# The share of fixtures carrying a ground at all. `fixture_stadiums_resolved` judges the
# fixtures that store one, so it cannot see the span pass losing the ordinal itself: that shows
# up only here, as fixtures that name no ground.
FIXTURE_WITH_GROUND_MINIMUM = 0.95
# The finance chain locator accepts a stored row count anywhere from 3 to 1,000, so a walk that
# ran past one club's chain into the next club's produces a series far longer than any window
# the game keeps. The longest series on the corpus is 60 months and the limit is twice that, so
# a career whose window is wider than any seen here still passes while the runaway walk does not.
FINANCE_MONTHS_LIMIT = 120
# A league position is a place in a division. Read one byte over, this field reads the low byte
# of the stored competition id, which is far outside a division's range on most records; read
# one byte back it is a reserved zero on every record, which leaves no position at all. The
# range is generous: the largest division in any installed database is well inside it.
LEAGUE_POSITION_RANGE = (1, 40)
# The two person populations are built by two passes over different records, and they are
# disjoint on every save measured. An overlap is the sign the staff discovery pass has started
# walking player records.
STAFF_ALSO_PLAYER_SHARE_LIMIT = 0.001
# The save keeps a rolling window of injury history a little over two years wide. No gate bounds
# how far BACK the walk reaches -- `injury_log_dates` only asks that a date decode and fall on or
# before the clock -- so a walk that picked up dates from another array passes that and fails
# this. The oldest row on the corpus is 743 days old and the limit is half as long again.
INJURY_HISTORY_WINDOW_DAYS = 1_100


def save_label(relative_name: str) -> str:
    """The save's file name, which is all a failure message may name it by."""
    return Path(relative_name).name


def share(numerator: int, denominator: int) -> float | None:
    """The share, or None when there is no denominator to divide by."""
    return numerator / denominator if denominator else None


def meets(observed: float | None, minimum: float) -> bool:
    """Whether a share was measurable at all and reached its floor.

    A share with no denominator fails rather than passing quietly: a reader that returned
    nothing would otherwise clear every rate check it has.
    """
    return observed is not None and observed >= minimum


def stays_under(observed: float | None, limit: float) -> bool:
    """Whether a share was measurable at all and stayed at or below its ceiling."""
    return observed is not None and observed <= limit


def within(value: int, bounds: tuple[int, int]) -> bool:
    """Whether an integer is inside an inclusive range."""
    return bounds[0] <= value <= bounds[1]


def managed_club_uid_of(career_save: fmsave.Save) -> int | None:
    """The uid of the club the save's human manages, or None when nobody manages one."""
    managed_clubs = career_save.managed_clubs()
    return managed_clubs[0].club_uid if managed_clubs else None


def counted(values: Iterable[int]) -> collections.Counter[int]:
    """How often each value appears."""
    return collections.Counter(values)


@pytest.mark.corpus_fast
def test_grounds_are_mostly_unnamed_and_share_their_home_clubs_plausibly(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Few grounds carry a name, and no ground collects an implausible crowd of home clubs.

    Neither quantity is bounded by a shipped check. The name share is what a row walk that had
    lost the length in front of an inline name would blow through, and the home-club count is
    what the derived calendar link would blow through if every fixture resolved to one row.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        grounds = career_save.stadiums()
        named_share = share(sum(1 for ground in grounds if ground.name is not None), len(grounds))
        mismatches.check(
            label, "few grounds are named", stays_under(named_share, STADIUM_NAMED_SHARE_LIMIT)
        )
        mismatches.check(
            label,
            "no ground collects too many home clubs",
            all(len(ground.home_club_uids) <= STADIUM_HOME_CLUBS_LIMIT for ground in grounds),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_most_fixtures_name_the_ground_they_were_played_at(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Nearly every fixture carries a ground.

    The reader's own check judges the fixtures that store a ground and asks how many of those
    reach a row, so it stays at 1.0 if the span pass stopped reading the ordinal altogether.
    This is the share that falls when that happens.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        fixtures = career_save.fixtures()
        with_ground = sum(1 for fixture in fixtures if fixture.stadium_uid is not None)
        mismatches.check(
            label,
            "fixtures name a ground",
            meets(share(with_ground, len(fixtures)), FIXTURE_WITH_GROUND_MINIMUM),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_finance_series_stay_inside_one_club_and_cover_the_managed_club(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """No club's series is longer than a window the game could keep, and the club the save's
    human manages has one.

    The count floor the reader enforces asks only that some club keeps a series, which tens of
    thousands of clubs can satisfy while the one club a user opens the save to read is missing.
    The length limit catches the other direction: a chain walk that ran out of one club's record
    into the next club's.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        months_per_club = counted(month.club_uid for month in career_save.finances())
        mismatches.check(
            label,
            "finance series stay inside a window the game could keep",
            all(count <= FINANCE_MONTHS_LIMIT for count in months_per_club.values()),
        )
        managed_club_uid = managed_club_uid_of(career_save)
        if managed_club_uid is not None:
            mismatches.check(
                label, "the managed club keeps a series", managed_club_uid in months_per_club
            )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_affiliate_groups_partition_the_clubs_they_name(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """No group names a club twice and no club is in two groups.

    The section walk reads whatever member counts the bytes hold and never looks for a repeat,
    so a walk that lost its place re-reads members it has already emitted and breaks both of
    these. The reader's own check asks how many members resolve to a club, which a re-read
    member does just as well as a first reading, so it cannot see either fault.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        members_per_group = [
            [member_uid for member_uid in group.club_uids if member_uid is not None]
            for group in career_save.affiliates()
        ]
        mismatches.check(
            label,
            "no group names a club twice",
            all(len(set(members)) == len(members) for members in members_per_group),
        )
        group_counts = counted(
            member_uid for members in members_per_group for member_uid in set(members)
        )
        mismatches.check(
            label, "no club is in two groups", all(count == 1 for count in group_counts.values())
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_the_job_feed_states_league_places_that_are_places(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Vacancies state a league place, and every place stated is one a division has.

    Both halves are needed. Read one byte back the field is a reserved zero on every record, so
    every place becomes absent and only the first half notices; read one byte on it is the low
    byte of the stored competition id, so places appear that no division has and only the second
    half notices.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        positions = [
            vacancy.league_position
            for vacancy in career_save.job_vacancies()
            if vacancy.league_position is not None
        ]
        mismatches.check(label, "vacancies state a league place", len(positions) > 0)
        mismatches.check(
            label,
            "vacancy league places are places",
            all(within(position, LEAGUE_POSITION_RANGE) for position in positions),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_staff_and_players_are_separate_uid_populations(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Almost no staff uid is also a player uid.

    The staff pass builds a person map of its own beside the player one, from different records,
    and nothing inside either pass compares the two. An overlap is the sign the staff discovery
    has started walking player records, and no reader check can see it because each pass only
    ever judges its own population.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        staff_uids = {member.uid for member in career_save.staff()}
        player_uids = {player.uid for player in career_save.players()}
        mismatches.check(
            label,
            "staff and players are separate populations",
            stays_under(
                share(len(staff_uids & player_uids), len(staff_uids)),
                STAFF_ALSO_PLAYER_SHARE_LIMIT,
            ),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_the_injury_type_table_is_the_same_database_table_on_every_save(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every save written by the same build decodes the identical table.

    The names come out of the installed database rather than out of a career, so two saves of
    two different careers must produce the same ids and the same text. A decode that had picked
    up anything career-dependent -- a different anchor, a length taken from the wrong place, a
    window that moved with the save's size -- differs between the two, and nothing inside one
    save can notice that.
    """
    mismatches = CorpusMismatches()
    decoded_tables: set[tuple[tuple[int, str], ...]] = set()
    for career_save in corpus_saves.values():
        decoded_tables.add(
            tuple((injury_type.id, injury_type.name) for injury_type in career_save.injury_types())
        )
    if len(decoded_tables) > 1:
        mismatches.note("the injury type table differs between saves")
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_injury_history_reaches_back_no_further_than_the_window_the_save_keeps(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """The oldest history row is inside a window a career could plausibly hold.

    The reader's own date check asks that a date decode and fall on or before the clock, which a
    date from decades ago satisfies. How far back the walk reaches is bounded nowhere else, so
    this is what a walk that strayed into another array of the section would fail.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        clock = career_save.info.game_date
        if clock is None:
            mismatches.note(f"{label}: no in-game date")
            continue
        history_dates = [
            row.date
            for row in career_save.injury_history()
            if row.kind is fmsave.InjuryRecordKind.HISTORY and row.date is not None
        ]
        if not history_dates:
            mismatches.note(f"{label}: no dated history rows")
            continue
        mismatches.check(
            label,
            "history stays inside the window the save keeps",
            (clock - min(history_dates)).days <= INJURY_HISTORY_WINDOW_DAYS,
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_every_training_week_starts_on_the_same_weekday(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every week of every team's calendar starts on one weekday.

    The reader's own check asks that consecutive weeks be seven days apart, which is true of any
    weekday and stays true of a date field read a fixed distance from where it belongs. A week
    start read from an offset that moves between records scatters the weekdays instead, and that
    is what this catches. Which weekday it is is left to the save.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        weekdays = {
            week.week_start.weekday()
            for calendar in career_save.training()
            for week in calendar.weeks
            if week.week_start is not None
        }
        if not weekdays:
            mismatches.note(f"{label}: no dated training weeks")
            continue
        mismatches.check(label, "training weeks share one weekday", len(weekdays) == 1)
    mismatches.fail_if_any()
