"""The Save object returned by fmsave.open."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import NamedTuple, Self

from fmsave import checks
from fmsave._container import ContainerIndex, read_index, read_section
from fmsave._context import SaveContext, closed_save_error
from fmsave._errors import ReaderCheckError
from fmsave._layouts import (
    ContractLayout,
    GateBounds,
    PersonBlockLayout,
    SuspensionLayout,
    find_layout,
)
from fmsave._version import read_save_info
from fmsave.checks import ReaderCheck
from fmsave.models.clubs import Club
from fmsave.models.competitions import Competition, Stage
from fmsave.models.contracts import Contract
from fmsave.models.managed import ManagedClub
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.models.suspensions import Suspension
from fmsave.readers._common import GAME_DB_SECTION, HUMANS_SECTION, SAVE_SUMMARY_SECTION
from fmsave.readers.managed import find_managed_club_layouts, resolve_managed_clubs
from fmsave.readers.player_scan import window_end
from fmsave.readers.players import build_player_decoder, collect_player_stats
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

    def __init__(self, container_index: ContainerIndex, info: SaveInfo) -> None:
        self._container_index = container_index
        self._info = info
        self._context = SaveContext(container_index, info)

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
        what fixtures, league-table groups and per-match records join through. Competition
        names are not stored in the save, so `competition_name` is None. The table is read on
        the first call; later calls return the same table.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No stage table was found in the tail of the game database, a
                stage id appears in two rows, or, on a full-size save, the stage table falls
                outside the checks' bounds.
        """
        context = self._context
        return context.cached(STAGES_TABLE_CACHE_KEY, self._read_stages)

    def competitions(self) -> Table[Competition]:
        """Every competition the save's stage table names, in ascending competition id.

        Each row carries the ids of its stages. The save stores no competition names and no
        editor database ids are read yet, so `name` and `database_id` are None on every row.
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

    def _reader_check(self, reader_name: str) -> ReaderCheck | None:
        """The checks a reader passed when its table was read, or None before it was read."""
        stored = self._context.cached_value(_check_cache_key(reader_name))
        return stored if isinstance(stored, ReaderCheck) else None

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
        # The index is built inside this borrow, so a cold call decompresses game_db once.
        with context.section(GAME_DB_SECTION):
            stage_index = context.stage_index()
        stage_check = checks.check_stages(stage_index.stats, gate_bounds, stage_index.game_db_bytes)
        checks.enforce_checks((stage_check,))
        self._store_reader_checks((stage_check,))
        return Table(stage_index.stages, Stage)

    def _read_competitions(self) -> Table[Competition]:
        context = self._context
        gate_bounds = self._gate_bounds()
        with context.section(GAME_DB_SECTION) as game_db:
            competition_index = context.competition_index()
            game_db_length = len(game_db)
        competition_check = checks.check_competitions(
            competition_index.stats, gate_bounds, game_db_length
        )
        checks.enforce_checks((competition_check,))
        self._store_reader_checks((competition_check,))
        return Table(competition_index.competitions, Competition)

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


def open_save(path: str | os.PathLike[str]) -> Save:
    """Open a Football Manager 26 save file for reading.

    Raises:
        FileNotFoundError: The file does not exist.
        NotAFmSaveError: The file is not a Football Manager save.
        CorruptSaveError: The save is damaged or was being written.
        UnsupportedGameError: The save is from another Football Manager version.
        ReaderCheckError: The save metadata does not match the expected layout.

    Warns:
        UnknownBuildWarning: The save comes from an FM26 build without layout tables.
    """
    container_index = read_index(path)
    return Save(container_index, read_save_info(container_index))
