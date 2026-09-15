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

from fmsave._container import ContainerIndex, read_section
from fmsave._errors import SaveClosedError
from fmsave.models.meta import SaveInfo
from fmsave.readers.clubs import GAME_DB_SECTION, ClubIndex, find_club_layouts, read_club_index

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
