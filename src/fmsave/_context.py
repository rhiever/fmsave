"""Per-save state that readers share: decompressed sections on loan, and cached results.

A reader borrows a section's bytes with `section(name)`. Nested borrows of the same
section share one decompressed bytes object, which is dropped when the outermost borrow
ends, so a whole section is never kept alive between reader calls. Results that are
cheap to keep (tables and small indexes) go in the cache through `cached(key, build)`.
Closing the context drops both; values already handed out keep working.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from typing import cast

from fmsave._container import ContainerIndex, read_region_frames, read_section
from fmsave._errors import SaveClosedError
from fmsave._layouts import NamePoolLayout, PlayerRecordLayout, find_layout
from fmsave.models.meta import SaveInfo
from fmsave.readers._common import GAME_DB_SECTION, SPAN_REGION
from fmsave.readers.clubs import ClubIndex, find_club_layouts, read_club_index
from fmsave.readers.names import NAME_POOLS_CACHE_KEY, NamePools, locate_name_pools
from fmsave.readers.player_scan import (
    PLAYER_RECORDS_CACHE_KEY,
    PlayerRecords,
    locate_player_records,
)
from fmsave.readers.span import (
    SPAN_RECORDS_CACHE_KEY,
    SpanRecords,
    find_span_layouts,
    missing_clock_error,
    scan_span,
)

CLUB_INDEX_CACHE_KEY = "club_index"


def closed_save_error() -> SaveClosedError:
    return SaveClosedError("this save is closed; open it again with fmsave.open()")


class SaveContext:
    """Section loans and a result cache for one open save. Not thread-safe."""

    __slots__ = (
        "_cache",
        "_closed",
        "_container_index",
        "_info",
        "_loan_counts",
        "_loaned_sections",
    )

    def __init__(self, container_index: ContainerIndex, info: SaveInfo) -> None:
        self._container_index = container_index
        self._info = info
        self._closed = False
        self._cache: dict[str, object] = {}
        self._loaned_sections: dict[str, bytes] = {}
        self._loan_counts: dict[str, int] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def info(self) -> SaveInfo:
        return self._info

    def section(self, name: str) -> AbstractContextManager[bytes]:
        """Borrow the decompressed bytes of section `name` for the length of a `with` block.

        Raises:
            SaveClosedError: The context is closed.
        """
        self._require_open()
        return self._section_loan(name)

    def cached[ValueT](self, key: str, build: Callable[[], ValueT]) -> ValueT:
        """Return the value stored under `key`, building and storing it on first use.

        A build that raises stores nothing. Never store section bytes here.

        Raises:
            SaveClosedError: The context is closed.
        """
        self._require_open()
        if key in self._cache:
            return cast("ValueT", self._cache[key])
        value = build()
        if not self._closed:
            self._cache[key] = value
        return value

    def cached_value(self, key: str) -> object | None:
        """Return the value stored under `key`, or None when nothing is stored.

        Raises:
            SaveClosedError: The context is closed.
        """
        self._require_open()
        return self._cache.get(key)

    def club_index(self) -> ClubIndex:
        """Every club with the team to club map, read from `game_db` once and then cached.

        Raises:
            SaveClosedError: The context is closed.
            ReaderCheckError: No club record is accepted, a club uid or club index appears
                in two records, or a team id is listed twice (by one club or by two).
        """
        return self.cached(CLUB_INDEX_CACHE_KEY, self._build_club_index)

    def _build_club_index(self) -> ClubIndex:
        save_info = self._info
        layouts = find_club_layouts(save_info.section_schemas.get(GAME_DB_SECTION), save_info.build)
        with self.section(GAME_DB_SECTION) as game_db:
            return read_club_index(game_db, layouts, save_info.file_name)

    def name_pools(self) -> NamePools:
        """The three name pools, read from `game_db` once and then cached.

        Raises:
            SaveClosedError: The context is closed.
            ReaderCheckError: The signature is missing or appears more than once, an entry id
                differs from its index, a name is longer than the layout allows, or (on a
                full-size `game_db`) a pool has fewer entries than the layout requires.
            CorruptSaveError: A pool runs past the end of `game_db`.
        """
        return self.cached(NAME_POOLS_CACHE_KEY, self._build_name_pools)

    def _build_name_pools(self) -> NamePools:
        save_info = self._info
        layout = find_layout(
            NamePoolLayout,
            GAME_DB_SECTION,
            save_info.section_schemas.get(GAME_DB_SECTION),
            save_info.build,
        ).layout
        with self.section(GAME_DB_SECTION) as game_db:
            return locate_name_pools(game_db, layout, save_info.file_name)

    def player_records(self) -> PlayerRecords:
        """Every accepted player record's offset, pindex and uid, read once and then cached.

        Raises:
            SaveClosedError: The context is closed.
            ReaderCheckError: No player records were found, a pindex or uid appears in two
                records, or the name pools cannot be located.
            CorruptSaveError: A player record runs past the end of `game_db`.
        """
        return self.cached(PLAYER_RECORDS_CACHE_KEY, self._build_player_records)

    def _build_player_records(self) -> PlayerRecords:
        save_info = self._info
        layout = find_layout(
            PlayerRecordLayout,
            GAME_DB_SECTION,
            save_info.section_schemas.get(GAME_DB_SECTION),
            save_info.build,
        ).layout
        with self.section(GAME_DB_SECTION) as game_db:
            # name_pools() is called inside this borrow so its own internal borrow shares
            # this one, instead of decompressing game_db a second time on a cold call.
            name_pools = self.name_pools()
            return locate_player_records(
                game_db, name_pools.end_offset, layout, save_info.file_name
            )

    def span_records(self) -> SpanRecords:
        """Fixtures, league-table blocks and rules preambles from one streamed pass over the
        unnamed span, read once and then cached.

        Raises:
            SaveClosedError: The context is closed.
            CorruptSaveError: The span is damaged or was being written.
            ReaderCheckError: The save's in-game date is unreadable, so the fixture year
                window cannot be built.
        """
        return self.cached(SPAN_RECORDS_CACHE_KEY, self._build_span_records)

    def _build_span_records(self) -> SpanRecords:
        save_info = self._info
        clock = save_info.game_date
        if clock is None:
            raise missing_clock_error(save_info.file_name)
        # The span is a run of unlisted frames, not a section: it is streamed one frame at a
        # time through read_region_frames, and never borrowed whole through section().
        frames = read_region_frames(self._container_index, SPAN_REGION)
        return scan_span(frames, find_span_layouts(save_info.build), clock, save_info.file_name)

    def close(self) -> None:
        """Drop cached values and section loans. Calling it again does nothing."""
        self._closed = True
        self._cache.clear()
        self._loaned_sections.clear()
        self._loan_counts.clear()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<fmsave SaveContext {state}, {len(self._cache)} cached>"

    def _require_open(self) -> None:
        if self._closed:
            raise closed_save_error()

    @contextmanager
    def _section_loan(self, name: str) -> Generator[bytes]:
        self._require_open()
        section_bytes = self._loaned_sections.get(name)
        if section_bytes is None:
            section_bytes = read_section(self._container_index, name)
            self._loaned_sections[name] = section_bytes
        self._loan_counts[name] = self._loan_counts.get(name, 0) + 1
        try:
            yield section_bytes
        finally:
            self._end_loan(name)

    def _end_loan(self, name: str) -> None:
        remaining_loans = self._loan_counts.get(name, 0) - 1
        if remaining_loans > 0:
            self._loan_counts[name] = remaining_loans
            return
        self._loan_counts.pop(name, None)
        self._loaned_sections.pop(name, None)
