"""Corpus checks for the stage, competition, fixture, league-table, transfer-window,
competition-rules and per-match readers.

Values read from a save never appear in an assert or a message: each check reduces to a
boolean or to a count of records that broke an invariant, and failures are reported by file
name and check name only.

Every check here is structural. What each one asserts is a property the decode must have
whatever career a save holds, never a figure one career happens to produce, so a bound here
is a floor a working reader clears on any save rather than a fingerprint of these ones.

Two things this module deliberately leaves to their existing owners. The whole-report check
that every reader is "ok" with every gate applied and passed, and the coverage regression
against the recorded ranges, are both in `test_corpus_readers.py` and cover all twelve
readers already; repeating them here would run the same readers twice over to assert the same
facts.
"""

from __future__ import annotations

import datetime
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

import fmsave
from tests.corpus.reporting import CorpusMismatches

pytestmark = [pytest.mark.corpus]

# Stage table.
STAGE_ASCENDING_MINIMUM = 0.99
STAGE_WITH_COMPETITION_MINIMUM = 0.90
# Competitions.
COMPETITION_DATABASE_ID_MINIMUM = 0.70
# Fixtures.
FIXTURES_MINIMUM = 5_000
FIXTURE_COMPETITION_MINIMUM = 0.95
# A career runs forward a season at a time, so a calendar reaching far past the save's own
# clock means records from somewhere other than this career have been kept: the block of
# template matches every save carries, dated years away from any of them, is what this
# catches if the rule that drops it ever stops working.
FIXTURE_YEARS_AHEAD_LIMIT = 8
# League tables.
TABLE_ROWS_MINIMUM = 200
TABLE_GROUPS_MINIMUM = 20
TABLE_GROUPS_RESOLVED_MINIMUM = 0.70
DOUBLE_ROUND_ROBIN_GROUPS_MINIMUM = 5
DIVISION_CLUB_COUNT_RANGE = (18, 26)
# Transfer windows.
TRANSFER_WINDOWS_MINIMUM = 1
MONTH_RANGE = (1, 12)
DAY_OF_MONTH_RANGE = (1, 31)
# Competition rules.
RULES_ROWS_MINIMUM = 20
# A round the save leaves unnumbered stores a value that reads as 256 rather than as a guess,
# so the numbering is a strong majority rather than every round: 0.948 and 0.952 of rounds on
# the corpus are numbered by their own position.
RULES_ROUND_NUMBERED_BY_POSITION_MINIMUM = 0.90
# A block's competition comes from the league table the save stores after it, and 0.622 and
# 0.553 of blocks on the corpus resolve to one. The floor is under the lower of those and the
# ceiling well over both: a share that reached 1.0 would mean the link had stopped demanding
# exactly one table, which is the whole of what makes it trustworthy.
RULES_LINKED_COMPETITION_RANGE = (0.45, 0.90)
# The linked blocks spread over 148 and 123 distinct competitions on the corpus, 2.8 and 2.3
# blocks apiece, and the competition most blocks claim takes 0.074 and 0.101 of them. A link
# that had collapsed onto one enormous table would keep its count and lose that spread, which
# neither the share above nor the reader's own gates would notice.
RULES_LINKED_COMPETITIONS_MINIMUM = 40
RULES_BUSIEST_COMPETITION_SHARE_LIMIT = 0.30
# Per-match player stats.
MATCH_COMPETITION_IN_TABLE_MINIMUM = 0.95
MATCH_MINUTES_LIMIT = 130
MATCH_RATING_LIMIT = 10.0


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


def ascending_share(ids: Sequence[int]) -> float | None:
    """The share of consecutive pairs that ascend, or None with fewer than two ids."""
    steps = len(ids) - 1
    if steps < 1:
        return None
    return sum(1 for index in range(steps) if ids[index + 1] > ids[index]) / steps


def is_sorted(keys: Sequence[tuple[datetime.date, datetime.time]]) -> bool:
    """Whether sort keys are already in order."""
    return all(keys[index] <= keys[index + 1] for index in range(len(keys) - 1))


def splits_add_up(
    played: int,
    won: int,
    drawn: int,
    lost: int,
    home_played: int,
    away_played: int,
    first_half_played: int,
    second_half_played: int,
) -> bool:
    """Whether a table row's own arithmetic holds across its total and its four splits."""
    return (
        played == won + drawn + lost
        and home_played + away_played == played
        and first_half_played + second_half_played == played
    )


def is_double_round_robin(club_count: int, rounds_per_venue: int) -> bool:
    """Whether a group has the shape of a division playing everyone home and away.

    A shape rule, not a name: it holds in any country and needs no competition name.
    """
    lowest, highest = DIVISION_CLUB_COUNT_RANGE
    return lowest <= club_count <= highest and rounds_per_venue == club_count - 1


def window_dates(window: fmsave.TransferWindow) -> tuple[int, ...]:
    """When a window opens and closes, which is the whole of what a window says."""
    opens = (window.opens_day, window.opens_month, window.opens_season_year_offset)
    closes = (window.closes_day, window.closes_month, window.closes_season_year_offset)
    return opens + closes


def years_ahead_of(when: datetime.date, clock: datetime.date) -> float:
    """How many years after the save's clock a date falls, negative when it is in the past."""
    return (when - clock).days / 365.25


@pytest.mark.corpus_fast
def test_stage_ids_walk_upwards_and_name_their_competitions(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """The stage table is a walk of distinct, almost always ascending ids, most of which
    carry a competition.

    Every competition join in the library goes through this table, so a walk that lost its
    place, repeated a row or started naming the wrong field is what these three catch.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        stages = career_save.stages()
        stage_ids = [stage.id for stage in stages]
        mismatches.check(label, "stage rows read", len(stages) > 0)
        mismatches.check(label, "stage ids unique", len(set(stage_ids)) == len(stage_ids))
        mismatches.check(
            label,
            "stage ids ascend",
            meets(ascending_share(stage_ids), STAGE_ASCENDING_MINIMUM),
        )
        with_competition = share(
            sum(1 for stage in stages if stage.competition_id is not None), len(stages)
        )
        mismatches.check(
            label,
            "stage rows carry a competition",
            meets(with_competition, STAGE_WITH_COMPETITION_MINIMUM),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_competitions_are_distinct_and_mostly_carry_a_database_id(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Competition ids are unique, most carry an editor database id, no two claim the same
    one, and nothing is named.

    The database id is the only stable key across saves and the only key a user's name map is
    read on, so an id claimed by two competitions would put one competition's name on
    another. That no name is set at all is the other half of it: the corpus session supplies
    no map, and a name appearing without one would mean fmsave had shipped names of its own.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        competitions = career_save.competitions()
        competition_ids = {competition.id for competition in competitions}
        mismatches.check(label, "competitions read", len(competitions) > 0)
        mismatches.check(label, "competition ids unique", len(competition_ids) == len(competitions))
        database_ids = [
            competition.database_id
            for competition in competitions
            if competition.database_id is not None
        ]
        mismatches.check(
            label,
            "competitions carry a database id",
            meets(share(len(database_ids), len(competitions)), COMPETITION_DATABASE_ID_MINIMUM),
        )
        mismatches.check(
            label, "database ids claimed once", len(set(database_ids)) == len(database_ids)
        )
        mismatches.check(
            label,
            "no competition is named without a map",
            all(competition.name is None for competition in competitions),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_the_fixture_calendar_is_sorted_dated_and_joined(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """The calendar is in date order, nearly every stage reaches a competition, and no match
    is dated far beyond the career the save holds.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        fixtures = career_save.fixtures()
        mismatches.check(label, "fixture rows read", len(fixtures) >= FIXTURES_MINIMUM)
        sort_keys = [
            (fixture.date, fixture.kick_off_time or datetime.time.min)
            for fixture in fixtures
            if fixture.date is not None
        ]
        mismatches.check(label, "fixtures sorted by kick-off", is_sorted(sort_keys))
        with_stage = [fixture for fixture in fixtures if fixture.stage_id is not None]
        reaching_competition = share(
            sum(1 for fixture in with_stage if fixture.competition_id is not None), len(with_stage)
        )
        mismatches.check(
            label,
            "fixture stages reach a competition",
            meets(reaching_competition, FIXTURE_COMPETITION_MINIMUM),
        )
        clock = career_save.info.game_date
        if clock is None:
            mismatches.note(f"{label}: no in-game date")
            continue
        far_future = sum(
            1
            for fixture in fixtures
            if fixture.date is not None
            and years_ahead_of(fixture.date, clock) > FIXTURE_YEARS_AHEAD_LIMIT
        )
        mismatches.check(label, "no fixture is dated beyond this career", far_future == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_fixture_joins_resolve_in_the_tables_they_name(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every club uid and competition id a fixture hands out is in the table it came from."""
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        fixtures = career_save.fixtures()
        club_uids = {club.uid for club in career_save.clubs()}
        competition_ids = {competition.id for competition in career_save.competitions()}
        unresolved_clubs = sum(
            1
            for fixture in fixtures
            for club_uid in (fixture.home_club_uid, fixture.away_club_uid)
            if club_uid is not None and club_uid not in club_uids
        )
        mismatches.check(label, "fixture club uids resolve", unresolved_clubs == 0)
        unresolved_competitions = sum(
            1
            for fixture in fixtures
            if fixture.competition_id is not None and fixture.competition_id not in competition_ids
        )
        mismatches.check(label, "fixture competition ids resolve", unresolved_competitions == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_league_table_rows_keep_their_own_arithmetic(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every row's total agrees with its results and with both of its splits, and the tables
    hold divisions.

    The arithmetic is what says the four splits were read from the positions they belong to:
    a block read one field over still looks like numbers, and stops adding up.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        tables = career_save.league_tables()
        rows_read = sum(len(table.rows) for table in tables)
        mismatches.check(label, "table groups read", len(tables) >= TABLE_GROUPS_MINIMUM)
        mismatches.check(label, "table rows read", rows_read >= TABLE_ROWS_MINIMUM)
        broken_arithmetic = 0
        divisions = 0
        for table in tables:
            for row in table.rows:
                if not splits_add_up(
                    row.played,
                    row.won,
                    row.drawn,
                    row.lost,
                    row.home.played,
                    row.away.played,
                    row.first_half.played,
                    row.second_half.played,
                ):
                    broken_arithmetic += 1
            if table.rows and is_double_round_robin(
                table.club_count, table.rows[0].rounds_per_venue
            ):
                divisions += 1
        mismatches.check(label, "table rows add up", broken_arithmetic == 0)
        mismatches.check(
            label, "tables hold divisions", divisions >= DOUBLE_ROUND_ROBIN_GROUPS_MINIMUM
        )
        resolved = share(
            sum(1 for table in tables if table.competition_id is not None), len(tables)
        )
        mismatches.check(
            label,
            "table groups reach a competition",
            meets(resolved, TABLE_GROUPS_RESOLVED_MINIMUM),
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_league_table_joins_resolve_in_the_tables_they_name(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every club uid and competition id a table hands out is in the table it came from.

    A competition id is deliberately not required to name only one group: a cup's group stage
    is one competition holding a table per group, and on the corpus about four resolved groups
    in five share their competition with another, so a uniqueness check here would fail a
    reader that is working exactly as its own documentation says.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        tables = career_save.league_tables()
        club_uids = {club.uid for club in career_save.clubs()}
        competition_ids = {competition.id for competition in career_save.competitions()}
        unresolved_clubs = sum(
            1
            for table in tables
            for row in table.rows
            if row.club_uid is not None and row.club_uid not in club_uids
        )
        mismatches.check(label, "table club uids resolve", unresolved_clubs == 0)
        unresolved_competitions = sum(
            1
            for table in tables
            if table.competition_id is not None and table.competition_id not in competition_ids
        )
        mismatches.check(label, "table competition ids resolve", unresolved_competitions == 0)
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_transfer_windows_are_dated_and_are_database_content(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every window opens and closes on a real day of a real month, and every save decodes
    the same windows.

    The windows come from the installed database rather than from a career, so two saves of
    one database must decode to the same list; a decode that had drifted onto career state
    would differ between them.
    """
    mismatches = CorpusMismatches()
    decoded_per_save: list[tuple[str, tuple[tuple[int, ...], ...]]] = []
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        windows = career_save.transfer_windows()
        mismatches.check(label, "transfer windows read", len(windows) >= TRANSFER_WINDOWS_MINIMUM)
        lowest_month, highest_month = MONTH_RANGE
        lowest_day, highest_day = DAY_OF_MONTH_RANGE
        months_in_range = all(
            lowest_month <= month <= highest_month
            for window in windows
            for month in (window.opens_month, window.closes_month)
        )
        days_in_range = all(
            lowest_day <= day <= highest_day
            for window in windows
            for day in (window.opens_day, window.closes_day)
        )
        mismatches.check(label, "window months in range", months_in_range)
        mismatches.check(label, "window days in range", days_in_range)
        decoded_per_save.append((label, tuple(window_dates(window) for window in windows)))
    if len(decoded_per_save) > 1:
        first_label, first_windows = decoded_per_save[0]
        for label, windows in decoded_per_save[1:]:
            mismatches.check(
                f"{first_label} and {label}",
                "decode the same transfer windows",
                windows == first_windows,
            )
    mismatches.fail_if_any()


@pytest.mark.corpus_fast
def test_competition_rules_blocks_are_shaped_like_rules(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Blocks are read, no prize is negative, rounds are numbered from one, and the positional
    competition link resolves on a measured share of blocks and no more.

    The last of those is the measured result this reader ships on. The competition comes from
    the league table the save stores after the block, which resolves on about three blocks in
    five; a share at either extreme would mean the link had stopped working or had stopped
    demanding exactly one table, and the second is what makes it trustworthy. Every row whose
    competition resolves must name one the competition table holds, since it is copied from a
    table this save's own reader returned.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        rules = career_save.competition_rules()
        mismatches.check(label, "rules blocks read", len(rules) >= RULES_ROWS_MINIMUM)
        negative_prizes = sum(1 for row in rules for amount in row.prize_money if amount < 0)
        mismatches.check(label, "prize money is not negative", negative_prizes == 0)
        rounds_read = 0
        numbered_by_position = 0
        below_one = 0
        for row in rules:
            for position, rules_round in enumerate(row.rounds, start=1):
                rounds_read += 1
                if rules_round.number == position:
                    numbered_by_position += 1
                if rules_round.number < 1:
                    below_one += 1
        mismatches.check(label, "rules rounds read", rounds_read > 0)
        mismatches.check(label, "round numbers count from one", below_one == 0)
        mismatches.check(
            label,
            "rounds are numbered by their position",
            meets(
                share(numbered_by_position, rounds_read),
                RULES_ROUND_NUMBERED_BY_POSITION_MINIMUM,
            ),
        )
        linked = [row for row in rules if row.competition_id is not None]
        lowest_linked, highest_linked = RULES_LINKED_COMPETITION_RANGE
        linked_share = share(len(linked), len(rules))
        mismatches.check(
            label,
            "the positional competition link resolves on its measured share of blocks",
            linked_share is not None and lowest_linked <= linked_share <= highest_linked,
        )
        claims = Counter(row.competition_id for row in linked)
        busiest_share = share(max(claims.values(), default=0), len(linked))
        mismatches.check(
            label,
            "the linked blocks spread over many competitions",
            len(claims) >= RULES_LINKED_COMPETITIONS_MINIMUM,
        )
        mismatches.check(
            label,
            "no one competition takes most of the linked blocks",
            busiest_share is not None and busiest_share <= RULES_BUSIEST_COMPETITION_SHARE_LIMIT,
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_per_match_records_belong_to_their_player_and_stay_in_range(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Every record belongs to a player the save holds, nearly every competition is one the
    stage table names, and a record the save holds no body for carries no body values.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        match_stats = career_save.player_match_stats()
        player_uids = {player.uid for player in career_save.players()}
        competition_ids = {competition.id for competition in career_save.competitions()}
        mismatches.check(label, "per-match rows read", len(match_stats) > 0)
        unresolved_players = sum(
            1 for record in match_stats if record.player_uid not in player_uids
        )
        mismatches.check(label, "per-match player uids resolve", unresolved_players == 0)
        in_competition_table = share(
            sum(1 for record in match_stats if record.competition_id in competition_ids),
            len(match_stats),
        )
        mismatches.check(
            label,
            "per-match competitions are in the competition table",
            meets(in_competition_table, MATCH_COMPETITION_IN_TABLE_MINIMUM),
        )
        bodies_out_of_range = sum(
            1
            for record in match_stats
            if record.body_valid
            and (
                record.minutes is None
                or record.minutes > MATCH_MINUTES_LIMIT
                or record.rating is None
                or record.rating > MATCH_RATING_LIMIT
            )
        )
        mismatches.check(label, "valid bodies stay in range", bodies_out_of_range == 0)
        unplayed_with_minutes = sum(
            1 for record in match_stats if record.played is False and record.minutes is not None
        )
        mismatches.check(
            label, "records without a body carry no minutes", unplayed_with_minutes == 0
        )
    mismatches.fail_if_any()


@pytest.mark.corpus_full
def test_every_reader_names_competitions_from_the_one_table(
    corpus_saves: dict[str, fmsave.Save],
) -> None:
    """Each competition id any reader hands out is either empty or in `competitions()`.

    The stage id space is the one space the library reports competitions in, and this is what
    says every reader stayed inside it. A suspension's competition id is deliberately absent:
    it belongs to a separate id space with no known link to this one, so requiring it to
    resolve here would assert something known to be false.
    """
    mismatches = CorpusMismatches()
    for relative_name, career_save in corpus_saves.items():
        label = save_label(relative_name)
        competition_ids = {competition.id for competition in career_save.competitions()}
        readers_and_ids = (
            ("stages", [stage.competition_id for stage in career_save.stages()]),
            ("fixtures", [fixture.competition_id for fixture in career_save.fixtures()]),
            ("league_tables", [table.competition_id for table in career_save.league_tables()]),
            (
                "player_match_stats",
                [record.competition_id for record in career_save.player_match_stats()],
            ),
        )
        for reader_name, reported_ids in readers_and_ids:
            outside = sum(
                1
                for competition_id in reported_ids
                if competition_id is not None and competition_id not in competition_ids
            )
            mismatches.check(label, f"{reader_name} competition ids are in the table", outside == 0)
    mismatches.fail_if_any()
