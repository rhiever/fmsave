"""The Save object returned by fmsave.open."""

from __future__ import annotations

import os
from types import TracebackType
from typing import NamedTuple, Self

from fmsave._container import ContainerIndex, read_index, read_section
from fmsave._context import SaveContext, closed_save_error
from fmsave._errors import ReaderCheckError
from fmsave._layouts import ContractLayout, PersonBlockLayout, SuspensionLayout, find_layout
from fmsave._version import read_save_info
from fmsave.models.clubs import Club
from fmsave.models.contracts import Contract
from fmsave.models.managed import ManagedClub
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.models.suspensions import Suspension
from fmsave.readers._common import GAME_DB_SECTION, HUMANS_SECTION, SAVE_SUMMARY_SECTION
from fmsave.readers.managed import find_managed_club_layouts, resolve_managed_clubs
from fmsave.readers.player_scan import window_end
from fmsave.readers.players import build_player_decoder
from fmsave.readers.suspensions import SuspensionEntry, locate_suspensions, suspension_rows
from fmsave.table import Table

CLUBS_TABLE_CACHE_KEY = "table:clubs"
PLAYERS_TABLE_CACHE_KEY = "table:players"
CONTRACTS_TABLE_CACHE_KEY = "table:contracts"
SUSPENSIONS_TABLE_CACHE_KEY = "table:suspensions"
MANAGED_CLUBS_TABLE_CACHE_KEY = "table:managed_clubs"


class _PlayerTables(NamedTuple):
    """The three tables one decode pass over the player records builds."""

    players: Table[Player]
    contracts: Table[Contract]
    suspensions: Table[Suspension]


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
                in two records, or a team id is listed twice (by one club or by two).
        """
        context = self._context
        return context.cached(
            CLUBS_TABLE_CACHE_KEY, lambda: Table(context.club_index().clubs, Club)
        )

    def players(self) -> Table[Player]:
        """Every player in the save's game database, in record offset order.

        Person fields (name, birth date, nationality, personality, traits and the rest) are filled
        in from each player's person block, or stay None or empty when no block validates.
        The table is read on the first call to `players()`, `contracts()` or `suspensions()`,
        from one decode pass; later calls to any of them return the same tables.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, or the save's in-game
                date is unreadable.
        """
        context = self._context
        return context.cached(PLAYERS_TABLE_CACHE_KEY, self._players_table_entry_point)

    def contracts(self) -> Table[Contract]:
        """Every player's contract in the save's game database, in player order.

        Only players whose contract is not None appear. The table is read on the first
        call to `players()`, `contracts()` or `suspensions()`, from one decode pass; later
        calls to any of them return the same tables.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, or the save's in-game
                date is unreadable.
        """
        context = self._context
        return context.cached(CONTRACTS_TABLE_CACHE_KEY, self._contracts_table_entry_point)

    def suspensions(self) -> Table[Suspension]:
        """Every unserved suspension in the save's game database, in player order.

        Each player's suspensions keep the order the save stores them in, and each row
        carries the player's current club. The table is read on the first call to
        `players()`, `contracts()` or `suspensions()`, from one decode pass; later calls to
        any of them return the same tables.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written, a player's relation
                header or entry list runs past its record window, or a legal name is not
                valid UTF-8.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, two player records share a uid, or the save's in-game
                date is unreadable.
        """
        context = self._context
        return context.cached(SUSPENSIONS_TABLE_CACHE_KEY, self._suspensions_table_entry_point)

    def managed_clubs(self) -> Table[ManagedClub]:
        """The club run by the save's first human manager, or an empty table when there is none.

        The link from a human manager to a club is proven only on saves with a single human
        manager; on a save with several, only the first is listed. The club comes from the
        manager's contract and is checked against the save summary, which also stores the
        manager's name. The table is read on the first call; later calls return the same table.
        It does not decode players.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No club record is accepted, a club uid or club index appears in
                two records, a team id is listed twice, the save's in-game date is unreadable,
                the contract and the save summary link the manager to different clubs, or the
                save lists a human manager but no club can be linked to them.
        """
        context = self._context
        return context.cached(MANAGED_CLUBS_TABLE_CACHE_KEY, self._read_managed_clubs)

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
        with (
            context.section(HUMANS_SECTION) as humans,
            context.section(SAVE_SUMMARY_SECTION) as summary,
            context.section(GAME_DB_SECTION) as game_db,
        ):
            club_index = context.club_index()
            managed_clubs = resolve_managed_clubs(
                humans, game_db, summary, club_index, clock, layouts, save_info.file_name
            )
        return Table(managed_clubs, ManagedClub)

    def _players_table_entry_point(self) -> Table[Player]:
        tables = self._decode_player_tables()
        context = self._context
        context.cached(CONTRACTS_TABLE_CACHE_KEY, lambda: tables.contracts)
        context.cached(SUSPENSIONS_TABLE_CACHE_KEY, lambda: tables.suspensions)
        return tables.players

    def _contracts_table_entry_point(self) -> Table[Contract]:
        tables = self._decode_player_tables()
        context = self._context
        context.cached(PLAYERS_TABLE_CACHE_KEY, lambda: tables.players)
        context.cached(SUSPENSIONS_TABLE_CACHE_KEY, lambda: tables.suspensions)
        return tables.contracts

    def _suspensions_table_entry_point(self) -> Table[Suspension]:
        tables = self._decode_player_tables()
        context = self._context
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
        # All records are decoded above; the three tables are built from here on, and cached
        # only by the entry point that asked for them.
        return _PlayerTables(
            Table(tuple(decoded_players), Player),
            Table(tuple(decoded_contracts), Contract),
            Table(tuple(decoded_suspensions), Suspension),
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
