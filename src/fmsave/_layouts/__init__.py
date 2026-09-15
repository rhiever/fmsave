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
    """How to recognise the `MAJOR.MINOR.PATCH+BUILD` version string in `save_game_summary`.

    `version_pattern` must match a whole length-prefixed string, so it carries no anchors
    or lookarounds.
    """

    version_pattern: str
    max_version_bytes: int


# Count checks (such as the name pool minimum) apply only to a decompressed `game_db` at
# least this large; smaller sections come from fragments that cannot meet full-save counts.
FULL_SAVE_MINIMUM_GAME_DB_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NamePoolLayout:
    """How to find and check the three name pools in `game_db`.

    `signature` sits immediately before the first pool's entry count. The pool minimum
    applies only when `game_db` is at least `minimum_applies_from_bytes` long; the other
    checks always apply.
    """

    signature: bytes
    max_name_bytes: int
    minimum_entries_per_pool: int
    minimum_applies_from_bytes: int


@dataclass(frozen=True, slots=True)
class ClubRecordLayout:
    """How to recognise club records in `game_db` and where their fields sit.

    A candidate record starts `anchor_offset` bytes before each `anchor` hit, and every other
    offset counts from that start. The league nation is stored twice, as is the uid. Ranges
    are inclusive (lowest, highest). Once a record has been accepted, the scan ends at the
    first candidate `stop_gap_bytes` or more past the last accepted record start; that point
    also ends the last record.
    """

    anchor: bytes
    anchor_offset: int
    club_index_offset: int
    uid_offset: int
    uid_copy_offset: int
    zero_byte_offset: int
    nation_offset: int
    fa_nation_offset: int
    nation_copy_offset: int
    city_offset: int
    long_name_offset: int
    nation_id_range: tuple[int, int]
    max_name_bytes: int
    stop_gap_bytes: int


@dataclass(frozen=True, slots=True)
class TeamListLayout:
    """How to find and parse the team list inside one club record.

    The list starts at the record's first `null_date_triple`. When that does not parse, each
    `float_anchor` hit at least `minimum_float_anchor_record_offset` bytes into the record is
    tried, with the list starting `float_anchor_offset` bytes before it. Offsets count from
    the list start. At `counts_offset` comes a count of `first_entry_bytes`-byte entries that
    each begin with `first_entry_lead_byte`, then a count of `second_entry_bytes`-byte entries
    that each begin with `second_entry_lead_byte`, then `filler_bytes` bytes, then the team
    count and that many u32 team ids. Ranges are inclusive (lowest, highest).
    """

    null_date_triple: bytes
    float_anchor: bytes
    float_anchor_offset: int
    minimum_float_anchor_record_offset: int
    counts_offset: int
    first_entry_bytes: int
    first_entry_lead_byte: int
    second_entry_bytes: int
    second_entry_lead_byte: int
    filler_bytes: int
    team_count_range: tuple[int, int]
    team_id_range: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ClubStatusLayout:
    """Where a club's reputation and last league position sit in the club-status table.

    Offsets count from a hit of the club's stored uid (uid minus 1) written twice, so
    `ordinal_offset` is negative. A hit counts when its ordinal is above the last accepted
    ordinal and below `ordinal_limit`, and its kind byte is `normal_kind` or `stub_kind`. Only
    normal records hold a position and a reputation. Ranges are inclusive (lowest, highest).
    """

    ordinal_offset: int
    ordinal_limit: int
    kind_offset: int
    normal_kind: int
    stub_kind: int
    position_offset: int
    reputation_offset: int
    reputation_range: tuple[int, int]


type Layout = (
    GameInfoLayout
    | SaveSummaryLayout
    | NamePoolLayout
    | ClubRecordLayout
    | TeamListLayout
    | ClubStatusLayout
)


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


def find_layout[LayoutT: Layout](
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
