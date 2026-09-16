"""The Save object returned by fmsave.open."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from types import TracebackType
from typing import NamedTuple, Self

from fmsave import checks
from fmsave._container import ContainerIndex, read_index, read_section
from fmsave._context import SaveContext, closed_save_error
from fmsave._errors import ReaderCheckError
from fmsave._frozen import FrozenMapping
from fmsave._layouts import (
    ContractLayout,
    FixtureCalendarLayout,
    GateBounds,
    LeagueTableLayout,
    PersonBlockLayout,
    StageResultLayout,
    SuspensionLayout,
    find_layout,
)
from fmsave._reader_stats import ResultStats
from fmsave._version import read_save_info
from fmsave.checks import ReaderCheck
from fmsave.models.clubs import Club
from fmsave.models.competitions import Competition, Stage
from fmsave.models.contracts import Contract
from fmsave.models.fixtures import Fixture
from fmsave.models.league_tables import LeagueTable
from fmsave.models.managed import ManagedClub
from fmsave.models.matches import PlayerMatchStats
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.models.rules import CompetitionRules, TransferWindow
from fmsave.models.suspensions import Suspension
from fmsave.name_maps import EMPTY_COMPETITION_NAMES, normalize_competition_names
from fmsave.readers._common import (
    GAME_DB_SECTION,
    HUMANS_SECTION,
    SAVE_SUMMARY_SECTION,
    SPAN_REGION,
)
from fmsave.readers.fixtures import build_fixtures
from fmsave.readers.league_tables import build_league_tables
from fmsave.readers.managed import find_managed_club_layouts, resolve_managed_clubs
from fmsave.readers.matches import (
    build_player_match_stats,
    find_match_record_layout,
    locate_match_records,
)
from fmsave.readers.player_scan import window_end
from fmsave.readers.players import build_player_decoder, collect_player_stats
from fmsave.readers.results import (
    apply_results,
    calendar_dates,
    find_result_layout,
    locate_stage_results,
    result_in_scope,
)
from fmsave.readers.rules import (
    build_competition_rules,
    find_transfer_window_layouts,
    read_transfer_windows,
)
from fmsave.readers.span import SPAN_RECORDS_CACHE_KEY, SpanRecords
from fmsave.readers.stages import StageIndex, named_stages
from fmsave.readers.suspensions import (
    SuspensionEntry,
    locate_suspensions,
    suspension_rows,
    suspension_stats,
)
from fmsave.table import Table

CLUBS_TABLE_CACHE_KEY = "table:clubs"
PLAYERS_TABLE_CACHE_KEY = "table:players"
CONTRACTS_TABLE_CACHE_KEY = "table:contracts"
SUSPENSIONS_TABLE_CACHE_KEY = "table:suspensions"
MANAGED_CLUBS_TABLE_CACHE_KEY = "table:managed_clubs"
STAGES_TABLE_CACHE_KEY = "table:stages"
COMPETITIONS_TABLE_CACHE_KEY = "table:competitions"
FIXTURES_TABLE_CACHE_KEY = "table:fixtures"
TRANSFER_WINDOWS_TABLE_CACHE_KEY = "table:transfer_windows"
LEAGUE_TABLES_TABLE_CACHE_KEY = "table:league_tables"
COMPETITION_RULES_TABLE_CACHE_KEY = "table:competition_rules"
PLAYER_MATCH_STATS_TABLE_CACHE_KEY = "table:player_match_stats"

# What each shared decode is kept under. While nothing is stored there the decode has not
# finished, which is what tells a failed pass from a failed reader of a pass that ran.
_SHARED_PASS_CACHE_KEYS: Mapping[str, str] = {
    checks.PLAYER_PASS: PLAYERS_TABLE_CACHE_KEY,
    checks.SPAN_PASS: SPAN_RECORDS_CACHE_KEY,
}


class _PlayerTables(NamedTuple):
    """The three tables one decode pass over the player records builds, and their checks."""

    players: Table[Player]
    contracts: Table[Contract]
    suspensions: Table[Suspension]
    reader_checks: tuple[ReaderCheck, ...]


def _check_cache_key(reader_name: str) -> str:
    return f"check:{reader_name}"


def _returning[ValueT](value: ValueT) -> Callable[[], ValueT]:
    return lambda: value


class Save:
    """A Football Manager 26 save opened for reading.

    Opening reads only the header, the directory and the save metadata; the file is
    not kept open. Each reader reopens the file, checks that it has not changed since
    it was opened, and reads only the parts it needs.

    A Save is not thread-safe: use one Save per thread. Records and tables it returns
    are immutable, safe to share, and keep working after the Save is closed.
    """

    __slots__ = ("_container_index", "_context", "_info")

    def __init__(
        self,
        container_index: ContainerIndex,
        info: SaveInfo,
        *,
        competition_names: FrozenMapping[int, str] = EMPTY_COMPETITION_NAMES,
    ) -> None:
        self._container_index = container_index
        self._info = info
        self._context = SaveContext(container_index, info, competition_names=competition_names)

    @property
    def info(self) -> SaveInfo:
        """Game, build, database version, in-game date and section schemas."""
        return self._info

    @property
    def closed(self) -> bool:
        """Whether the save has been closed. Readers raise SaveClosedError once it is."""
        return self._context.closed

    def clubs(self) -> Table[Club]:
        """Every club in the save's game database, in club index order.

        The table is read on the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), or, on a
                full-size save, the club records fall outside the checks' bounds.
        """
        context = self._context
        return context.cached(CLUBS_TABLE_CACHE_KEY, self._read_clubs)

    def players(self) -> Table[Player]:
        """Every player in the save's game database, in record offset order.

        Person fields (name, birth date, nationality, personality, traits and the rest) are filled
        in from each player's person block, or stay None or empty when no block validates.
        The table is read on the first call to `players()`, `contracts()` or `suspensions()`,
        from one decode pass; later calls to any of them return the same tables. When a check
        of that pass fails, none of the three tables is kept, so each of them raises.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, the save's in-game
                date is unreadable, or, on a full-size save, the players, contracts or
                suspensions decoded fall outside the checks' bounds.
        """
        context = self._context
        return context.cached(PLAYERS_TABLE_CACHE_KEY, self._players_table_entry_point)

    def contracts(self) -> Table[Contract]:
        """Every player's contract in the save's game database, in player order.

        Only players whose contract is not None appear. The table is read on the first
        call to `players()`, `contracts()` or `suspensions()`, from one decode pass; later
        calls to any of them return the same tables. When a check of that pass fails, none
        of the three tables is kept, so each of them raises.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, the save's in-game
                date is unreadable, or, on a full-size save, the players, contracts or
                suspensions decoded fall outside the checks' bounds.
        """
        context = self._context
        return context.cached(CONTRACTS_TABLE_CACHE_KEY, self._contracts_table_entry_point)

    def suspensions(self) -> Table[Suspension]:
        """Every unserved suspension in the save's game database, in player order.

        Every unserved ban the save holds is listed, including bans the game no longer
        displays. Each player's
        suspensions keep the order the save stores them in, and each row carries the club the
        player belongs to, which for a player registered with a team another club controls is
        that controlling club. The table is read on the first call to
        `players()`, `contracts()` or `suspensions()`, from one decode pass; later calls to
        any of them return the same tables. When a check of that pass fails, none of the
        three tables is kept, so each of them raises.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, the save's in-game
                date is unreadable, or, on a full-size save, the players, contracts or
                suspensions decoded fall outside the checks' bounds.
        """
        context = self._context
        return context.cached(SUSPENSIONS_TABLE_CACHE_KEY, self._suspensions_table_entry_point)

    def managed_clubs(self) -> Table[ManagedClub]:
        """The club run by the save's first human manager.

        An empty table means no managed club was found: the save has no human manager, or
        the manager has no current club, for example while between jobs. The link from a
        human manager to a club is proven only on saves with a single human manager; on a
        save with several, only the first is listed. The club comes from the manager's
        current contract and is checked against the save summary, which also stores the
        manager's name. The table is read on the first call; later calls return the same
        table. It does not decode players.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No club record is accepted, a club uid or club index appears in
                two records, a team id is listed twice, the save's in-game date is unreadable,
                the contract and the save summary link the manager to different clubs, or,
                with no current contract, the save summary links the manager to more than
                one club.
        """
        context = self._context
        return context.cached(MANAGED_CLUBS_TABLE_CACHE_KEY, self._read_managed_clubs)

    def stages(self) -> Table[Stage]:
        """Every stage of every competition, in the order the save's stage table stores them.

        A stage is one part of a competition: a league season is one stage, a cup round is one,
        and each leg of a two-legged tie is its own stage carrying the same round. Stage ids are
        what fixtures, league-table groups and per-match records join through. No save stores a
        competition name, so `competition_name` is None unless the save was opened with a name
        map, and then it is filled in for the competitions that map names. The table is read on
        the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No stage table was found in the tail of the game database, a
                stage id appears in two rows, or, on a full-size save, the stage table falls
                outside the checks' bounds. With a name map the competition checks must pass
                as well, since a stage's competition name is read out of that table.
        """
        context = self._context
        return context.cached(STAGES_TABLE_CACHE_KEY, self._read_stages)

    def competitions(self) -> Table[Competition]:
        """Every competition the save's stage table names, in ascending competition id.

        Each row carries the ids of its stages and, for about nine competitions in ten, the
        competition's id in the game's own editor database, which is the same value on every
        save and is what an external name source is keyed on. The save stores no competition
        names, so `name` is None on every row until a name map is supplied.
        The table is read on the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No stage table was found in the tail of the game database, a
                stage id appears in two rows, or, on a full-size save, fewer competitions were
                found than the checks allow.
        """
        context = self._context
        return context.cached(COMPETITIONS_TABLE_CACHE_KEY, self._read_competitions)

    def fixtures(self) -> Table[Fixture]:
        """Every match the save has scheduled or played, in date and kick-off order.

        The save holds several copies of the calendar; only the largest is returned, so the
        block of template matches every save carries is left out. Each row joins to its
        competition through its stage, and to a club through each team id; an id the save does
        not resolve leaves its fields empty rather than being guessed.

        `home_goals` and `away_goals` carry the score of a played match the save still holds
        one for, which is about a quarter of them: the calendar itself stores no score, and the
        separate records that do are kept for only part of a career. A played match with empty
        goals means the save no longer holds that result, not that it finished goalless.

        The table is read on the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No club record is accepted, a club uid or club index appears in
                two records, a team id is listed twice, no stage table was found in the tail of
                the game database, a stage id appears in two rows, the save's in-game date is
                unreadable, or, on a full-size span, the calendar or the scores joined onto it
                fall outside the checks' bounds. With a competition name map, the competition
                checks run first and raise here too, so no row is named from a table whose
                checks did not pass.
        """
        context = self._context
        return context.cached(FIXTURES_TABLE_CACHE_KEY, self._read_fixtures)

    def _read_fixtures(self) -> Table[Fixture]:
        context = self._context
        save_info = context.info
        gate_bounds = self._gate_bounds()
        layout = find_layout(FixtureCalendarLayout, SPAN_REGION, None, save_info.build).layout
        # One game_db borrow covers all three indexes the joins go through, so a cold call
        # decompresses that section once rather than once per index. The span is streamed after
        # the borrow ends, so the two large regions are never held in memory together.
        with context.section(GAME_DB_SECTION):
            club_index = context.club_index()
            # With a name map the competitions are read first, checks and all. Every
            # competition name a fixture row carries comes out of the competition index, so
            # that index must have passed its own checks before a name of its leaves this
            # reader: a build that mis-paired entity ids with database ids would otherwise put
            # another competition's name on every one of a hundred thousand fixture rows and
            # raise nothing at all. Reading the competition table runs those checks inside this
            # same borrow, so game_db is still decompressed once. Without a map every
            # competition_name is None anyway, so nothing is read on its account.
            if context.competition_names:
                self.competitions()
            stage_index = context.stage_index()
            competition_index = context.competition_index()
        span_records = context.span_records()
        fixtures, fixture_stats = build_fixtures(
            span_records, stage_index, competition_index, club_index, layout
        )
        fixtures, result_stats = self._scored_fixtures(
            fixtures, span_records, stage_index, find_result_layout(save_info.build)
        )
        fixture_check = checks.check_fixtures(
            fixture_stats, result_stats, gate_bounds, span_records.span_bytes
        )
        checks.enforce_checks((fixture_check,))
        self._store_reader_checks((fixture_check,))
        return Table(fixtures, Fixture)

    def _scored_fixtures(
        self,
        fixtures: tuple[Fixture, ...],
        span_records: SpanRecords,
        stage_index: StageIndex,
        layout: StageResultLayout,
    ) -> tuple[tuple[Fixture, ...], ResultStats]:
        """Join the stage-keyed results onto the calendar and fill the scores they carry.

        The records come from the span pass, which collected them on what each one settles by
        itself, and from the sections the layout names, read one at a time. Both routes are
        then judged by the one `result_in_scope` predicate, so neither can accept what the
        other would not.

        The window a record is accepted in is the calendar's own first and last date, taken
        from the calendar this very call built. A calendar holding no dated match at all
        therefore accepts nothing, rather than falling back on some wider rule: with no fixture
        to join, no score could be attributed anyway.

        A section the save does not list is skipped rather than raising, since a save need not
        carry every one of them.
        """
        context = self._context
        # The stage table is a rejection filter here and nothing else: this join asks only
        # whether a record's stage id is one the table holds, and copies no value out of it, so
        # no score it produces carries anything of that index. That is why this reads the
        # cached index instead of going through `stages()`, which would enforce that reader's
        # checks. Taking only a membership test is what fails safe: a stage table that had
        # moved would cost scores here and could never invent one, which is the opposite of the
        # defect the rule about handing another reader's data out unchecked exists to stop.
        # A fixture row does carry stage-derived fields, its competition and round among them,
        # but `build_fixtures` puts them there; they do not arrive through this join.
        stage_by_id = stage_index.stage_by_id
        covered_dates = calendar_dates(fixtures)
        if covered_dates is None:
            return apply_results(fixtures, (), candidates=span_records.result_candidates)
        earliest_date, latest_date = covered_dates
        candidates = span_records.result_candidates
        collected = [
            raw_result
            for raw_result in span_records.results
            if result_in_scope(raw_result, stage_by_id, earliest_date, latest_date)
        ]
        listed_sections = self._require_open().sections
        for section_name in layout.regions:
            if section_name not in listed_sections:
                continue
            with context.section(section_name) as section_bytes:
                located = locate_stage_results(
                    section_bytes, layout, stage_by_id, earliest_date, latest_date
                )
            candidates += located.candidates
            collected.extend(located.results)
        return apply_results(fixtures, collected, candidates=candidates)

    def transfer_windows(self) -> Table[TransferWindow]:
        """Every transfer window the save's rules database holds, in stored order.

        A window says when a transfer window opens and closes in a season. It is database
        content rather than career state: every save made from one installed database holds
        the same windows, whatever has happened in the career. The dates are season-relative,
        so each carries an offset from the season's start year rather than a calendar date,
        and a window has no name of its own. The table is read on the first call; later calls
        return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: On a full-size save, fewer windows were decoded than the checks
                allow, or the windows that were found did not decode their dates.
        """
        context = self._context
        return context.cached(TRANSFER_WINDOWS_TABLE_CACHE_KEY, self._read_transfer_windows)

    def league_tables(self) -> Table[LeagueTable]:
        """Every live league table the save holds, in the order the save stores them.

        One table is one run of blocks the save stores together, told from the next by the
        index each block keeps of its own place in its table. The save stores each block
        several times over, the copies agreeing in every field fmsave decodes and differing
        only in undecoded head bytes, so repeated content is dropped before the tables are
        built; keeping it would break the tables apart. Nothing in a table names its
        competition, so it is voted for from the fixture calendar and is empty on the few
        tables the vote cannot settle, which are still returned; one competition names
        several tables, since a cup's group stage holds a table per group. Rows are in the
        order the save stores, which is the table's own standings order, so `position` is the
        league position. The table is read on the first call; later calls return the same
        table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: The fixture calendar the vote runs on, or the club, stage or
                competition table this reader joins through, failed its own checks; no club
                record is accepted; a club uid or club index appears in two records; a team id
                is listed twice; no stage table was found in the tail of the game database; a
                stage id appears in two rows; the save's in-game date is unreadable; or, on a
                full-size span, the blocks fall outside the checks' bounds. Every index whose
                data this reader hands out is read through the accessor that enforces that
                index's own checks, so none of those checks can be skipped.
        """
        context = self._context
        return context.cached(LEAGUE_TABLES_TABLE_CACHE_KEY, self._read_league_tables)

    def _read_league_tables(self) -> Table[LeagueTable]:
        context = self._context
        save_info = context.info
        gate_bounds = self._gate_bounds()
        layout = find_layout(LeagueTableLayout, SPAN_REGION, None, save_info.build).layout
        # The vote runs on the calendar this reader asks the fixtures reader for, not on the
        # span's raw fixture records, so every row it counts comes from a table whose own
        # checks have passed: a calendar that had shattered into fragments, or swallowed the
        # block of template matches no save plays, would otherwise vote a competition onto
        # hundreds of tables and raise nothing at all.
        fixtures_table = self.fixtures()
        # Every index this reader borrows is taken through the accessor that enforces that
        # index's own checks, never through the raw context index, because this reader hands
        # the borrowed data straight out: club names and team slots on every row, competition
        # ids on every table, and the stage joins the calendar vote runs on. Forcing the club,
        # competition or stage bounds to something unmeetable must stop this call, not leave it
        # returning thousands of club names from an index whose checks never ran. The calendar
        # above already built and cached all three indexes inside one game_db borrow, so these
        # are cache reads plus their checks, and this reader decompresses nothing of its own.
        self.clubs()
        self.stages()
        self.competitions()
        club_index = context.club_index()
        competition_index = context.competition_index()
        span_records = context.span_records()
        league_tables, table_stats = build_league_tables(
            span_records, fixtures_table, competition_index, club_index, layout
        )
        table_check = checks.check_league_tables(table_stats, gate_bounds, span_records.span_bytes)
        checks.enforce_checks((table_check,))
        self._store_reader_checks((table_check,))
        return Table(league_tables, LeagueTable)

    def competition_rules(self) -> Table[CompetitionRules]:
        """Every competition-rules block the save holds, in the order the save stores them.

        A block carries a competition's promotion, play-off and relegation places, its
        tie-break codes, its prize money by finishing position and its round calendar.

        **No row says which competition it belongs to.** The save stores no such link, and a
        measured hunt for one found none, so `competition_id` and `competition_name` are None
        on every row: match a division by `club_count` and `fixtures_per_club` against
        `league_tables()` instead. `club_count` is itself empty in this release, because no
        fixed position in the block carries it.

        The squad and financial rules the save's rules database holds are not in this release:
        the groups that carry them have no name, no competition and no displayed label to pin
        their values, so `kind` is PREAMBLE on every row. Transfer windows are their own table,
        `transfer_windows()`.

        The table is read on the first call; later calls return the same table. It reads only
        the shared span pass, so it decompresses nothing of its own once that pass has run.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: The save's in-game date is unreadable, so the span pass cannot
                run, or, on a full-size span, the blocks fall outside the checks' bounds.
        """
        context = self._context
        return context.cached(COMPETITION_RULES_TABLE_CACHE_KEY, self._read_competition_rules)

    def _read_competition_rules(self) -> Table[CompetitionRules]:
        context = self._context
        gate_bounds = self._gate_bounds()
        # No index is borrowed and no join is made: no block names a competition, so there is
        # nothing to look up and nothing of another reader's to hand out.
        span_records = context.span_records()
        rules, rules_stats = build_competition_rules(span_records)
        rules_check = checks.check_competition_rules(
            rules_stats, gate_bounds, span_records.span_bytes
        )
        checks.enforce_checks((rules_check,))
        self._store_reader_checks((rules_check,))
        return Table(rules, CompetitionRules)

    def player_match_stats(self) -> Table[PlayerMatchStats]:
        """Every match one of the save's players played that it still holds a record of.

        Rows come in player order and, inside each player, in the order the save stores his
        matches. **This is never a whole season and never a career**: the save keeps about
        twenty matches per player per spell at a team, **counted across all competitions at once
        rather than per competition**, and drops the oldest as new ones arrive. A player who has
        played more than that in his current spell has only his latest matches here, so **a
        per-competition total summed from these rows is short without saying so** — nothing in a
        row marks it as truncated. Friendlies, internationals and youth matches are kept apart
        from these records and are not here at all.

        Each row carries the competition id the record itself stores, which is in the stage id
        space, and joins to a club through the opponent's team id; a team id no club lists
        leaves the opponent fields empty rather than guessing them. A match the save keeps no
        performance body for carries its date, competition and opponent, and every field that
        would come from the body is empty.

        This reader decodes the players to fill `player_name`, so a cold call pays for the
        player pass; a caller who has already called `players()` pays nothing extra for it. The
        table is read on the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: The club or player readers this one joins through failed their own
                checks; no club record is accepted; a club uid or club index appears in two
                records; a team id is listed twice; no player records were found; two player
                records share a uid; no stage table was found in the tail of the game database;
                the save's in-game date is unreadable, so the years a match may be dated in
                cannot be worked out; or, on a full-size save, the records decoded fall outside
                the checks' bounds.
        """
        context = self._context
        return context.cached(PLAYER_MATCH_STATS_TABLE_CACHE_KEY, self._read_player_match_stats)

    def _read_player_match_stats(self) -> Table[PlayerMatchStats]:
        context = self._context
        save_info = context.info
        clock = save_info.game_date
        if clock is None:
            raise ReaderCheckError(
                f"{save_info.file_name}: the save's in-game date is unreadable, so the years a "
                "match record may be dated in cannot be worked out"
            )
        gate_bounds = self._gate_bounds()
        layout = find_match_record_layout(
            save_info.section_schemas.get(GAME_DB_SECTION), save_info.build
        )
        # One game_db borrow covers the record search and every index the joins go through, so a
        # cold call decompresses that section once rather than once per index.
        with context.section(GAME_DB_SECTION) as game_db:
            # These two hand their data straight out: the player uid and name on every row, and
            # the opponent club's names and team slot. Each is therefore read through the reader
            # that enforces its own checks, never through the raw index behind it, so forcing
            # the player or club bounds to something unmeetable stops this call instead of
            # leaving it handing out names from an index whose checks never ran. Both run inside
            # this borrow, so they still share the one decompression.
            players = self.players()
            self.clubs()
            club_index = context.club_index()
            player_records = context.player_records()
            # The stage index is read straight from the cache, without the stage reader's
            # checks, because nothing of it reaches a caller: a record carries its own
            # competition id, and this index is used only to count how many of those ids the
            # stage table names, which is what one of this reader's own checks judges.
            stage_index = context.stage_index()
            records_by_position = locate_match_records(game_db, player_records, layout, clock)
            game_db_length = len(game_db)
        match_rows, match_stats = build_player_match_stats(
            records_by_position, player_records, players, club_index, stage_index, layout
        )
        match_check = checks.check_player_match_stats(match_stats, gate_bounds, game_db_length)
        checks.enforce_checks((match_check,))
        self._store_reader_checks((match_check,))
        return Table(match_rows, PlayerMatchStats)

    def _reader_check(self, reader_name: str) -> ReaderCheck | None:
        """The checks a reader passed when its table was read, or None before it was read."""
        stored = self._context.cached_value(_check_cache_key(reader_name))
        return stored if isinstance(stored, ReaderCheck) else None

    def _shared_pass_cached(self, pass_name: str) -> bool:
        """Whether the decode the readers of a pass share has finished and been kept.

        A failure raised before it finished is a failure of the pass: every other reader of
        that pass would run the same decode again only to raise the same error, which for the
        span means streaming it once per reader. A failure raised after it was kept is the
        reader's own, and the rest of the pass still has its own work to do.
        """
        cache_key = _SHARED_PASS_CACHE_KEYS.get(pass_name)
        if cache_key is None:
            return False
        return self._context.cached_value(cache_key) is not None

    def _gate_bounds(self) -> GateBounds:
        save_info = self._context.info
        return find_layout(
            GateBounds,
            GAME_DB_SECTION,
            save_info.section_schemas.get(GAME_DB_SECTION),
            save_info.build,
        ).layout

    def _store_reader_checks(self, reader_checks: Sequence[ReaderCheck]) -> None:
        """Keep checks that passed next to their tables, for the validation report."""
        context = self._context
        for reader_check in reader_checks:
            context.cached(_check_cache_key(reader_check.reader), _returning(reader_check))

    def _read_clubs(self) -> Table[Club]:
        gate_bounds = self._gate_bounds()
        club_index = self._context.club_index()
        club_check = checks.check_clubs(club_index.stats, gate_bounds, club_index.game_db_bytes)
        checks.enforce_checks((club_check,))
        self._store_reader_checks((club_check,))
        return Table(club_index.clubs, Club)

    def _read_managed_clubs(self) -> Table[ManagedClub]:
        context = self._context
        save_info = context.info
        clock = save_info.game_date
        if clock is None:
            raise ReaderCheckError(
                f"{save_info.file_name}: the save's in-game date is unreadable, so contract "
                "chain records cannot be decoded"
            )
        layouts = find_managed_club_layouts(save_info.section_schemas, save_info.build)
        gate_bounds = self._gate_bounds()
        with (
            context.section(HUMANS_SECTION) as humans,
            context.section(SAVE_SUMMARY_SECTION) as summary,
            context.section(GAME_DB_SECTION) as game_db,
        ):
            club_index = context.club_index()
            managed_clubs, managed_stats = resolve_managed_clubs(
                humans, game_db, summary, club_index, clock, layouts, save_info.file_name
            )
            game_db_length = len(game_db)
        managed_check = checks.check_managed(managed_stats, gate_bounds, game_db_length)
        checks.enforce_checks((managed_check,))
        self._store_reader_checks((managed_check,))
        return Table(managed_clubs, ManagedClub)

    def _read_stages(self) -> Table[Stage]:
        context = self._context
        gate_bounds = self._gate_bounds()
        # With a name map the competitions are read first, checks and all. Every name a stage
        # row carries comes out of the competition index, so that index must have passed its
        # own checks before a name of its leaves this reader: a build that mis-paired entity
        # ids with database ids would otherwise put another competition's name on every stage
        # row and raise nothing at all. Reading the competition table runs those checks, and it
        # builds the stage index inside its own game_db borrow, so both indexes still come out
        # of a single decompression. Without a map every competition_name would be None anyway,
        # so the stage index is read on its own and the id-pair pass that names competitions is
        # never paid for. Either way this reader needs no part of game_db beyond the cached
        # indexes, so a warm call decompresses nothing.
        name_for: Callable[[int | None], str | None] | None = None
        if context.competition_names:
            self.competitions()
            name_for = context.competition_index().name_for
        stage_index = context.stage_index()
        stage_check = checks.check_stages(stage_index.stats, gate_bounds, stage_index.game_db_bytes)
        checks.enforce_checks((stage_check,))
        self._store_reader_checks((stage_check,))
        stages = stage_index.stages
        return Table(stages if name_for is None else named_stages(stages, name_for), Stage)

    def _read_competitions(self) -> Table[Competition]:
        context = self._context
        gate_bounds = self._gate_bounds()
        competition_index = context.competition_index()
        # The stage index the competitions were built from is cached by the call above and
        # already carries the section length the checks want, so game_db is read once in all.
        game_db_length = context.stage_index().game_db_bytes
        competition_check = checks.check_competitions(
            competition_index.stats, gate_bounds, game_db_length
        )
        checks.enforce_checks((competition_check,))
        self._store_reader_checks((competition_check,))
        return Table(competition_index.competitions, Competition)

    def _read_transfer_windows(self) -> Table[TransferWindow]:
        context = self._context
        save_info = context.info
        gate_bounds = self._gate_bounds()
        tagged_layout, window_layout = find_transfer_window_layouts(
            save_info.section_schemas.get(GAME_DB_SECTION), save_info.build
        )
        with context.section(GAME_DB_SECTION) as game_db:
            windows, window_stats = read_transfer_windows(game_db, tagged_layout, window_layout)
            game_db_length = len(game_db)
        window_check = checks.check_transfer_windows(window_stats, gate_bounds, game_db_length)
        checks.enforce_checks((window_check,))
        self._store_reader_checks((window_check,))
        return Table(windows, TransferWindow)

    def _players_table_entry_point(self) -> Table[Player]:
        tables = self._decode_player_tables()
        context = self._context
        self._store_reader_checks(tables.reader_checks)
        context.cached(CONTRACTS_TABLE_CACHE_KEY, lambda: tables.contracts)
        context.cached(SUSPENSIONS_TABLE_CACHE_KEY, lambda: tables.suspensions)
        return tables.players

    def _contracts_table_entry_point(self) -> Table[Contract]:
        tables = self._decode_player_tables()
        context = self._context
        self._store_reader_checks(tables.reader_checks)
        context.cached(PLAYERS_TABLE_CACHE_KEY, lambda: tables.players)
        context.cached(SUSPENSIONS_TABLE_CACHE_KEY, lambda: tables.suspensions)
        return tables.contracts

    def _suspensions_table_entry_point(self) -> Table[Suspension]:
        tables = self._decode_player_tables()
        context = self._context
        self._store_reader_checks(tables.reader_checks)
        context.cached(PLAYERS_TABLE_CACHE_KEY, lambda: tables.players)
        context.cached(CONTRACTS_TABLE_CACHE_KEY, lambda: tables.contracts)
        return tables.suspensions

    def _decode_player_tables(self) -> _PlayerTables:
        context = self._context
        save_info = context.info
        clock = save_info.game_date
        if clock is None:
            raise ReaderCheckError(
                f"{save_info.file_name}: the save's in-game date is unreadable, so person "
                "blocks and ages cannot be decoded"
            )
        game_db_schema = save_info.section_schemas.get(GAME_DB_SECTION)
        gate_bounds = self._gate_bounds()
        with context.section(GAME_DB_SECTION) as game_db:
            club_index = context.club_index()
            player_records = context.player_records()
            name_pools = context.name_pools()
            person_layout = find_layout(
                PersonBlockLayout, GAME_DB_SECTION, game_db_schema, save_info.build
            ).layout
            contract_layout = find_layout(
                ContractLayout, GAME_DB_SECTION, game_db_schema, save_info.build
            ).layout
            suspension_layout = find_layout(
                SuspensionLayout, GAME_DB_SECTION, game_db_schema, save_info.build
            ).layout
            decoder = build_player_decoder(
                player_records.layout,
                club_index,
                name_pools,
                clock,
                person_layout,
                contract_layout,
                save_info.file_name,
            )
            suspension_entries_by_position = locate_suspensions(
                game_db, player_records, suspension_layout
            )
            no_suspension_entries: tuple[SuspensionEntry, ...] = ()
            suspension_entries_for = suspension_entries_by_position.get
            decoded_players: list[Player] = []
            decoded_contracts: list[Contract] = []
            decoded_suspensions: list[Suspension] = []
            append_player = decoded_players.append
            append_contract = decoded_contracts.append
            extend_suspensions = decoded_suspensions.extend
            record_offsets = player_records.record_offsets
            game_db_length = len(game_db)
            last_position = len(record_offsets) - 1
            for position, record_offset in enumerate(record_offsets):
                record_window_end = window_end(player_records, position, game_db_length)
                suspension_entries = suspension_entries_for(position, no_suspension_entries)
                player, contract = decoder.decode(
                    game_db,
                    record_offset,
                    record_window_end,
                    is_last_record=position == last_position,
                    suspension_entries=suspension_entries,
                )
                append_player(player)
                if contract is not None:
                    append_contract(contract)
                if suspension_entries:
                    extend_suspensions(suspension_rows(player, suspension_entries))
        # All records are decoded above. Every check of the pass runs here, before any table is
        # built: when one fails, nothing is cached and the next call decodes and checks again.
        player_count = len(decoded_players)
        reader_checks = (
            checks.check_players(
                collect_player_stats(
                    decoded_players, decoder, player_records.markerless_count, gate_bounds
                ),
                gate_bounds,
                game_db_length,
            ),
            checks.check_contracts(
                decoder.contract_decoder.stats(player_count, len(decoded_contracts)),
                gate_bounds,
                game_db_length,
            ),
            checks.check_suspensions(
                suspension_stats(suspension_entries_by_position, player_count, clock),
                gate_bounds,
                game_db_length,
            ),
        )
        checks.enforce_checks(reader_checks)
        return _PlayerTables(
            Table(tuple(decoded_players), Player),
            Table(tuple(decoded_contracts), Contract),
            Table(tuple(decoded_suspensions), Suspension),
            reader_checks,
        )

    def close(self) -> None:
        """Close the save and release its cached results.

        Calling a reader afterwards raises SaveClosedError; tables already returned keep working.
        """
        self._context.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<fmsave.Save {self._info.game} {self._info.build} {state}>"

    def _require_open(self) -> ContainerIndex:
        if self.closed:
            raise closed_save_error()
        return self._container_index

    def _read_section(self, name: str) -> bytes:
        """Read one whole section; readers borrow sections through SaveContext.section instead.

        Meant for the small sections read when the save is opened.
        """
        return read_section(self._require_open(), name)


def open_save(
    path: str | os.PathLike[str],
    *,
    competition_names: Mapping[int, str] | str | os.PathLike[str] | None = None,
) -> Save:
    """Open a Football Manager 26 save file for reading.

    Args:
        path: The save file to read.
        competition_names: Names for competitions, keyed on `Competition.database_id`, either
            as a mapping or as the path of a two-column CSV that
            `fmsave.read_competition_names` reads. No save stores a competition name and fmsave
            ships none, so without this every `Competition.name` and every denormalised
            `competition_name` is None. Tables are read once and then kept, so the map cannot be
            changed afterwards: open the save again to read it under a different one.

    Raises:
        FileNotFoundError: The file does not exist.
        NotAFmSaveError: The file is not a Football Manager save.
        CorruptSaveError: The save is damaged or was being written.
        UnsupportedGameError: The save is from another Football Manager version.
        ReaderCheckError: The save metadata does not match the expected layout.
        OSError: A competition name CSV cannot be opened or read.
        TypeError: A competition name mapping holds a key that is not an int, or a name that is
            not a str.
        ValueError: A competition name CSV is malformed, or a supplied name is empty.

    Warns:
        UnknownBuildWarning: The save comes from an FM26 build without layout tables.
    """
    # The map is checked before the file is touched, so a mistake in it costs none of the work
    # of opening a save.
    names = normalize_competition_names(competition_names)
    container_index = read_index(path)
    return Save(container_index, read_save_info(container_index), competition_names=names)
