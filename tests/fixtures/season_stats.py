"""Season-statistics section bytes for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. The section is an unlisted frame of the span region: the section header with schema 15,
then one record per player back to back, then a zero byte ending the list and a 16-byte footer.

A record is `01`, the u32 key (the player's pindex plus one), a 16-byte header, 8 slots, a
20-byte block, a u32 count of other teams each carrying a byte, a u32 team id and 6 slots, a
u32 count of 8-byte rating items, then a form list: a byte count of at most 16 and 3 bytes
each. A slot is a single zero byte when absent, or a 139-byte line starting `01 06`.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from tests.fixtures.container import section_body

SECTION_SCHEMA = 15
LINE_BYTES = 139
HEADER_BYTES = 16
BLOCK_BYTES = 20
FOOTER_BYTES = 16
RATING_ITEM_BYTES = 8
OWN_SLOTS = 8
OTHER_TEAM_SLOTS = 6

# Each line field: (offset from the line start, struct code, stored units per public unit).
LINE_FIELDS: Mapping[str, tuple[int, str, int]] = {
    "rating_sum": (2, "<H", 1),
    "minutes": (4, "<H", 1),
    "starts": (6, "B", 1),
    "substitute_appearances": (7, "B", 1),
    "rated_appearances": (8, "B", 1),
    "goals": (9, "B", 1),
    "assists": (10, "B", 1),
    "goals_allowed": (11, "B", 1),
    "penalties_taken": (12, "B", 1),
    "penalties_scored": (13, "B", 1),
    "player_of_the_match": (14, "B", 1),
    "red_cards": (15, "B", 1),
    "yellow_cards": (16, "B", 1),
    "clean_sheets": (17, "B", 1),
    "passes_attempted": (27, "<H", 1),
    "passes_completed": (29, "<H", 1),
    "tackles_attempted": (31, "<H", 1),
    "tackles_completed": (33, "<H", 1),
    "word_35": (35, "<H", 1),
    "word_37": (37, "<H", 1),
    "dribbles": (39, "<H", 1),
    "fouls_made": (41, "<H", 1),
    "fouls_against": (43, "<H", 1),
    "shots": (45, "<H", 1),
    "shots_on_target": (47, "<H", 1),
    "mistakes_leading_to_goal": (59, "<H", 1),
    "minutes_since_last_goal": (61, "<H", 1),
    "distance_km": (65, "<H", 10),
    "offsides": (67, "<H", 1),
    "word_69": (69, "<H", 1),
    "word_71": (71, "<H", 1),
    "key_passes": (73, "<H", 1),
    "key_tackles": (75, "<H", 1),
    "key_headers": (77, "<H", 1),
    "interceptions": (79, "<H", 1),
    "clear_cut_chances_created": (81, "<H", 1),
    "word_83": (83, "<H", 1),
    "possession_lost": (87, "<H", 1),
    "possession_won": (89, "<H", 1),
    "expected_goals": (91, "<H", 100),
    "expected_assists": (93, "<H", 100),
    "word_95": (95, "<H", 1),
    "free_kick_shots": (99, "<H", 1),
    "goals_outside_box": (101, "<H", 1),
    "open_play_crosses_attempted": (109, "<H", 1),
    "shots_outside_box": (111, "<H", 1),
    "expected_goals_prevented": (113, "<h", 100),
    "high_intensity_sprints": (115, "<H", 1),
    "progressive_passes": (119, "<H", 1),
    "pressures_attempted": (121, "<H", 1),
    "pressures_completed": (123, "<H", 1),
    "open_play_key_passes": (125, "<H", 1),
    "non_penalty_expected_goals": (127, "<H", 100),
    "crosses_attempted": (131, "<H", 1),
    "crosses_completed": (133, "<H", 1),
    "shots_blocked": (135, "<H", 1),
}


def stat_line(**values: float) -> bytes:
    """One 139-byte line: `01 06`, then each named field at its offset, zero elsewhere.

    A value is given in public units (xG as 1.25, distance in km) and stored scaled.
    """
    line = bytearray(LINE_BYTES)
    line[0:2] = b"\x01\x06"
    for name, value in values.items():
        offset, code, scale = LINE_FIELDS[name]
        struct.pack_into(code, line, offset, round(value * scale))
    return bytes(line)


def slots_bytes(slots: Sequence[bytes | None]) -> bytes:
    return b"".join(b"\x00" if line is None else line for line in slots)


@dataclass(frozen=True)
class ExampleRecord:
    """One player's record; `own_slots` has 8 entries and each other team's slots 6."""

    key: int
    own_slots: Sequence[bytes | None] = (None,) * OWN_SLOTS
    other_teams: Sequence[tuple[int, Sequence[bytes | None]]] = ()
    rating_items: int = 1
    form_entries: int = 16
    header: bytes = field(default=bytes(HEADER_BYTES))

    def to_bytes(self) -> bytes:
        if len(self.own_slots) != OWN_SLOTS:
            raise ValueError(f"a record has {OWN_SLOTS} own slots, not {len(self.own_slots)}")
        record = bytearray(b"\x01" + struct.pack("<I", self.key) + self.header)
        record += slots_bytes(self.own_slots)
        record += bytes(BLOCK_BYTES)
        record += struct.pack("<I", len(self.other_teams))
        for team_id, team_slots in self.other_teams:
            if len(team_slots) != OTHER_TEAM_SLOTS:
                raise ValueError(f"another team has {OTHER_TEAM_SLOTS} slots")
            record += b"\x00" + struct.pack("<I", team_id) + slots_bytes(team_slots)
        record += struct.pack("<I", self.rating_items)
        for _ in range(self.rating_items):
            record += bytes([2]) + bytes(RATING_ITEM_BYTES - 1)
        record += bytes([self.form_entries]) + bytes([64, 5, 6]) * self.form_entries
        return bytes(record)


def season_stats_body(
    records: Sequence[ExampleRecord], *, footer: bytes = bytes(FOOTER_BYTES), schema: int = 15
) -> bytes:
    """The whole section body: header, records, the zero that ends the list, the footer."""
    payload = b"".join(record.to_bytes() for record in records) + b"\x00" + footer
    return section_body(".dat", schema, payload)
