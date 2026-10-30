"""Fictional extended FM27 lines: no save bytes or real identities."""

from __future__ import annotations

import dataclasses
import struct

import pytest

from fmsave._errors import ReaderCheckError
from fmsave._layouts import SeasonStatsLayout
from fmsave._layouts.fm26_26_3_2 import SEASON_STATS as FM26_LAYOUT
from fmsave.export import record_to_dict
from fmsave.readers.season_stats import (
    SeasonPlayer,
    build_season_stats,
    decode_season_line,
    walk_season_stats,
)
from tests.fixtures.season_stats import ExampleRecord, season_stats_body, stat_line

OMITTED = ("goals_outside_box", "pressures_attempted", "pressures_completed")


def extended_layout() -> SeasonStatsLayout:
    return dataclasses.replace(
        FM26_LAYOUT,
        line_marker=b"\x01\x07",
        line_bytes=155,
        unsupported_fields=OMITTED,
        require_unique_keys=True,
    )


def extended_line() -> bytes:
    # Distinct, deliberately nonzero values prove omission rather than coincidental zeros.
    line = bytearray(
        stat_line(
            starts=2,
            minutes=180,
            goals=1,
            goals_outside_box=7,
            pressures_attempted=31,
            pressures_completed=19,
            expected_goals=1.25,
            passes_attempted=87,
            passes_completed=70,
        )
    )
    line[:2] = b"\x01\x07"
    return bytes(line) + bytes(range(16))


def extended_body(*, key: int = 12) -> bytes:
    slots = (None, extended_line(), None, None, None, extended_line(), None, None)
    return season_stats_body([ExampleRecord(key=key, own_slots=slots)])


def test_extended_lines_omit_only_explicitly_unsupported_metrics() -> None:
    layout = extended_layout()
    body = extended_body()
    walk = walk_season_stats(body, layout, "example.bin")
    rows, stats = build_season_stats(
        walk, body, {11: SeasonPlayer(900001, "Alex Example", 70001, False)}, {}, {}, layout
    )
    assert len(rows) == 2
    assert stats.overall_sums_competitions == 1
    assert stats.minutes_in_range == 2
    for row in rows:
        assert row.goals == 1
        assert row.expected_goals == 1.25
        assert row.passes_completed == 70
        assert row.goals_outside_box is None
        assert row.pressures_attempted is None
        assert row.pressures_completed is None
        assert row.pressures_attempted_per_90 is None
        assert row.pressures_completed_per_90 is None
        assert row.pass_completion_percent == pytest.approx(70 / 87 * 100)
        assert record_to_dict(row, json_ready=True)["pressures_attempted"] is None


def test_fm26_keeps_its_metric_values_and_rates() -> None:
    body = season_stats_body(
        [
            ExampleRecord(
                key=12, own_slots=(stat_line(minutes=90, pressures_attempted=7),) + (None,) * 7
            )
        ]
    )
    rows, _ = build_season_stats(
        walk_season_stats(body, FM26_LAYOUT, "example.bin"),
        body,
        {11: SeasonPlayer(900001, "Alex Example", 70001, False)},
        {},
        {},
        FM26_LAYOUT,
    )
    assert rows[0].pressures_attempted == 7
    assert rows[0].pressures_attempted_per_90 == 7


@pytest.mark.parametrize(
    "name", ["not_a_statistic", "player_uid", "average_rating", "minutes", "expected_goals"]
)
def test_omission_names_must_be_stored_statistic_fields(name: str) -> None:
    layout = dataclasses.replace(extended_layout(), unsupported_fields=(name,))
    with pytest.raises(ValueError, match="unsupported"):
        decode_season_line(extended_line(), 0, False, layout)


def test_duplicate_keys_fail_closed_in_the_fm27_walk_only() -> None:
    body = season_stats_body([ExampleRecord(key=12), ExampleRecord(key=12)])
    with pytest.raises(ReaderCheckError, match="repeat"):
        walk_season_stats(body, extended_layout(), "example.bin")
    assert len(walk_season_stats(body, FM26_LAYOUT, "example.bin").records) == 2


@pytest.mark.parametrize("damage", ["truncated", "extra-byte", "old-marker", "huge-count"])
def test_extended_record_damage_is_rejected(damage: str) -> None:
    data = bytearray(extended_body())
    if damage == "truncated":
        del data[-1:]
    elif damage == "extra-byte":
        data.append(0)
    elif damage == "old-marker":
        at = data.index(b"\x01\x07")
        data[at + 1] = 6
    else:
        # Own slots follow the independent 8-byte section and 21-byte record headers.
        other_count_at = 8 + 21 + 6 + 2 * 155 + 20
        struct.pack_into("<I", data, other_count_at, 0xFFFFFFFF)
    with pytest.raises(ReaderCheckError):
        walk_season_stats(bytes(data), extended_layout(), "example.bin")
