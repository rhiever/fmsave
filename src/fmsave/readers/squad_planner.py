"""Reading the numbered slots in a single human manager's squad planner."""

from __future__ import annotations

import struct

from fmsave._errors import CorruptSaveError, UnsupportedGameError
from fmsave._layouts import SquadPlannerLayout, find_layout
from fmsave._scan import decode_date
from fmsave.models.squad_planner import SquadPlannerSlot
from fmsave.readers._common import HUMANS_SECTION, layout_mismatch, section_label
from fmsave.readers.player_scan import PlayerRecords

_GROUPS = 4
_EXPOSED_GROUPS = 3
_SLOTS = 27
_SELECTOR_BYTES = 4
_SCOUTING_DATE_PLACEHOLDER = b"\x01\x00\x6c\x07"

type PlannerSelectors = tuple[tuple[tuple[int, ...], ...], ...]


def find_squad_planner_layout(game: str, schema: int | None, build: str) -> SquadPlannerLayout:
    if game == "FM27":
        match = find_layout(SquadPlannerLayout, HUMANS_SECTION, schema, build)
        if match.exact:
            return match.layout
    raise UnsupportedGameError(f"squad planner has no supported layout for {game} build {build}")


def _qualified_lead(humans: bytes, marker_at: int, layout: SquadPlannerLayout) -> bool:
    if humans[marker_at - 14 : marker_at - 12] != layout.lead_date_marker:
        return False
    # The first scouting settings vary by career. The neighboring block uses the same
    # short marker, so also check the lead before and after it.
    if decode_date(humans, marker_at - 12) is None:
        return False
    for date_at in (marker_at - 8, marker_at - 4):
        if (
            not humans.startswith(_SCOUTING_DATE_PLACEHOLDER, date_at)
            and decode_date(humans, date_at) is None
        ):
            return False
    return (
        humans.startswith(bytes(4), marker_at + 16)
        and humans.startswith(b"\x01", marker_at + 22)
        and humans.startswith(layout.lead_tail, marker_at + 27)
    )


def _planner_start(
    humans: bytes, search_start: int, layout: SquadPlannerLayout, file_name: str
) -> int:
    start: int | None = None
    marker_at = humans.find(layout.lead_marker, search_start + 14)
    while marker_at >= 0:
        if _qualified_lead(humans, marker_at, layout):
            if start is not None:
                raise layout_mismatch(
                    file_name, "the squad planner lead is ambiguous", HUMANS_SECTION
                )
            start = marker_at + 31
        marker_at = humans.find(layout.lead_marker, marker_at + 1)
    if start is None:
        raise layout_mismatch(file_name, "no squad planner lead was found", HUMANS_SECTION)
    return start


def read_planner_selectors(
    humans: bytes,
    search_start: int,
    layout: SquadPlannerLayout,
    scouting_marker: bytes,
    file_name: str,
) -> PlannerSelectors:
    """Walk every counted set. Keep the first set of each of the first three groups."""
    offset = _planner_start(humans, search_start, layout, file_name)
    groups: list[tuple[tuple[int, ...], ...]] = []
    label = section_label(file_name, HUMANS_SECTION)
    for group in range(_GROUPS):
        for set_index, marker in enumerate(
            (layout.group_marker, layout.set_marker, layout.set_marker)
        ):
            if not humans.startswith(marker, offset):
                raise layout_mismatch(
                    file_name, "a squad planner set header is missing", HUMANS_SECTION
                )
            offset += len(marker)
            keep = group < _EXPOSED_GROUPS and set_index == 0
            slots: list[tuple[int, ...]] = []
            for _ in range(_SLOTS):
                if offset >= len(humans):
                    raise CorruptSaveError(
                        f"{label}: squad planner slot count runs past the section"
                    )
                count = humans[offset]
                offset += 1
                end = offset + _SELECTOR_BYTES * count
                if end > len(humans):
                    raise CorruptSaveError(
                        f"{label}: squad planner slot data runs past the section"
                    )
                if keep:
                    slots.append(struct.unpack_from(f"<{count}I", humans, offset))
                offset = end
            if keep:
                groups.append(tuple(slots))
    # The following settings anchor the walk's end after all four groups.
    if not humans.startswith(layout.footer_marker, offset + 26) or not humans.startswith(
        scouting_marker, offset + 91
    ):
        raise layout_mismatch(file_name, "the squad planner footer is missing", HUMANS_SECTION)
    return tuple(groups)


def build_squad_planner(
    groups: PlannerSelectors, records: PlayerRecords | None
) -> tuple[SquadPlannerSlot, ...]:
    def uid_for_selector(selector: int) -> int | None:
        if records is None:
            return None
        position = records.position_by_pindex.get(selector - 1)
        return None if position is None else records.uids[position]

    return tuple(
        SquadPlannerSlot(season, slot, tuple(uid_for_selector(value) for value in selectors))
        for season, slots in enumerate(groups)
        for slot, selectors in enumerate(slots, start=1)
    )
