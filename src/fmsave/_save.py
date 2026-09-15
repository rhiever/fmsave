"""The Save object returned by fmsave.open."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Self

from fmsave._container import ContainerIndex, read_index, read_section
from fmsave._context import SaveContext, closed_save_error
from fmsave._layouts import NamePoolLayout, PlayerRecordLayout, find_layout
from fmsave._version import read_save_info
from fmsave.models.clubs import Club
from fmsave.models.meta import SaveInfo
from fmsave.models.players import Player
from fmsave.readers.names import NAME_POOLS_CACHE_KEY, locate_name_pools
from fmsave.readers.players import (
    PLAYER_RECORDS_CACHE_KEY,
    decode_player_record,
    locate_player_records,
)
from fmsave.table import Table

CLUBS_TABLE_CACHE_KEY = "table:clubs"
PLAYERS_TABLE_CACHE_KEY = "table:players"
_GAME_DB_SECTION = "game_db"


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

        The table is read on the first call; later calls return the same table. Person
        fields (name, birth date, nationality, personality, traits and the rest) are None
        or empty for now.

        Raises:
            SaveClosedError: The save is closed.
            SaveChangedError: The file changed on disk after it was opened.
            CorruptSaveError: The save is damaged or was being written.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, a team id is listed twice (by one club or by two), no player
                records were found, or two player records share a uid.
        """
        context = self._context
        return context.cached(PLAYERS_TABLE_CACHE_KEY, self._build_players_table)

    def _build_players_table(self) -> Table[Player]:
        context = self._context
        save_info = self._info
        club_index = context.club_index()
        schema = save_info.section_schemas.get(_GAME_DB_SECTION)
        record_layout = find_layout(
            PlayerRecordLayout, _GAME_DB_SECTION, schema, save_info.build
        ).layout
        name_pool_layout = find_layout(
            NamePoolLayout, _GAME_DB_SECTION, schema, save_info.build
        ).layout
        with context.section(_GAME_DB_SECTION) as game_db:
            name_pools = context.cached(
                NAME_POOLS_CACHE_KEY,
                lambda: locate_name_pools(game_db, name_pool_layout, save_info.file_name),
            )
            player_records = context.cached(
                PLAYER_RECORDS_CACHE_KEY,
                lambda: locate_player_records(
                    game_db, name_pools.end_offset, record_layout, save_info.file_name
                ),
            )
            players = tuple(
                decode_player_record(game_db, record_offset, club_index)
                for record_offset in player_records.record_offsets
            )
        return Table(players, Player)

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
