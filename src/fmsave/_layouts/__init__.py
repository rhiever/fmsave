"""Private layout tables: where fields sit inside each region.

Layouts are keyed by (region, schema number) with the game build as a fallback,
because some regions carry no schema number. Modules are organised per game year
and build.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GameInfoLayout:
    """Offsets inside `game_info`.

    Offsets named `*_after_db_version` count from the end of the length-prefixed
    database version string, whose length varies.
    """

    db_version_length_offset: int
    max_db_version_bytes: int
    build_number_offsets_after_db_version: tuple[int, ...]
    game_date_offset_after_db_version: int


@dataclass(frozen=True, slots=True)
class SaveSummaryLayout:
    """How to find the `MAJOR.MINOR.PATCH+BUILD` version string in `save_game_summary`."""

    version_pattern: str
    max_version_bytes: int


type Layout = GameInfoLayout | SaveSummaryLayout


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    region: str
    schema: int | None
    build: str
    layout: Layout


@dataclass(frozen=True, slots=True)
class LayoutMatch[LayoutT]:
    layout: LayoutT
    exact: bool


FALLBACK_BUILD = "26.3.2+2329565"


def registered_layouts() -> tuple[LayoutEntry, ...]:
    from fmsave._layouts import fm26_26_3_2

    return fm26_26_3_2.LAYOUTS


def known_builds() -> frozenset[str]:
    return frozenset(entry.build for entry in registered_layouts())


def find_layout[LayoutT: GameInfoLayout | SaveSummaryLayout](
    layout_type: type[LayoutT], region: str, schema: int | None, build: str
) -> LayoutMatch[LayoutT]:
    candidates = [
        entry
        for entry in registered_layouts()
        if entry.region == region and isinstance(entry.layout, layout_type)
    ]
    for entry in candidates:
        if schema is not None and entry.schema == schema and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=True)
    for entry in candidates:
        if entry.build == build and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=entry.schema is None)
    for entry in candidates:
        if entry.build == FALLBACK_BUILD and isinstance(entry.layout, layout_type):
            return LayoutMatch(entry.layout, exact=False)
    raise LookupError(f"no {layout_type.__name__} registered for region {region!r}")
