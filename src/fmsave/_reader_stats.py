"""Counts the readers keep while they decode, for the reader checks in fmsave.checks.

Each record holds plain counts from one reader's existing pass; nothing here reads a save.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayerStats:
    """What one decode pass counted over the player records.

    `ages` holds every known age, for the median; `heights_median` is the low median of every
    record's height. Relation counts cover every entry of every validated person block. The
    `*_in_range` and `home_near_current` counts use the ranges in `GateBounds`.
    """

    records: int
    markerless: int
    with_person_block: int
    with_resolved_name: int
    relation_entries: int
    relation_sentinel_ok: int
    second_nation_entries: int
    second_nation_qualifier_ok: int
    handling_above_finishing: int
    with_natural_position: int
    height_in_range: int
    condition_sharpness_in_range: int
    with_valid_join_date: int
    world_not_above_current: int
    home_near_current: int
    with_team: int
    team_resolved: int
    aged_in_range: int
    home_grown_club_refs: int
    home_grown_club_refs_resolved: int
    ages: array[int]
    heights_median: int | None


@dataclass(frozen=True, slots=True)
class ContractStats:
    """What one decode pass counted over the players' contract chain records.

    `tail_ends` counts parsed tails with an end date, and `tail_ends_past` those whose end date
    is before the save's in-game date.
    """

    players: int
    contracts: int
    players_with_chain: int
    chain_records: int
    tails_parsed: int
    clause_tables: int
    clause_terminator_ok: int
    head_ok: int
    tail_ends: int
    tail_ends_past: int
    chain_teams_resolved: int


@dataclass(frozen=True, slots=True)
class ClubStats:
    """What the club pass counted: records, team lists and normal status records."""

    records: int
    team_lists_found: int
    status_normal: int
    status_confirmed: int


@dataclass(frozen=True, slots=True)
class SuspensionStats:
    """What the suspension search counted over the player region."""

    players: int
    entries: int
    players_with_entries: int
    issued_after_clock: int


@dataclass(frozen=True, slots=True)
class ManagedStats:
    """What the managed-club reader found: human managers, resolved routes (0 or 1) and rows."""

    human_count: int
    route_one_resolved: int
    route_two_resolved: int
    rows: int
