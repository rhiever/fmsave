from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import TransferWindowStats
from fmsave.checks import GateResult, evaluate_transfer_windows
from fmsave.export import column_names
from fmsave.models.rules import TransferWindow
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.rules import find_transfer_window_layouts, read_transfer_windows
from tests.fixtures.career import (
    SUMMER_WINDOW_CLOSE_TIME,
    SUMMER_WINDOW_TYPE,
    WINTER_WINDOW_CLOSE_TIME,
    career_tagged_stream,
)
from tests.fixtures.game_db import (
    TAGGED_U32_TYPES,
    tagged_value_bytes,
    transfer_window_bytes,
)

GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 300 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
TRANSFER_WINDOW_GATE_NAMES = ("transfer_windows_minimum", "transfer_window_dates")
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
TAGGED_LAYOUT, WINDOW_LAYOUT = find_transfer_window_layouts(GAME_DB_SCHEMA, "")


def decode(stream: bytes) -> tuple[tuple[TransferWindow, ...], TransferWindowStats]:
    return read_transfer_windows(stream, TAGGED_LAYOUT, WINDOW_LAYOUT)


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_window_stats() -> TransferWindowStats:
    """Counts as every save measured reports them.

    These two are kept exact, unlike the invented populations the other reader tests are judged
    on, because the windows are installed-database content rather than career state: every save
    written from one database holds the same records, whoever played it and however long for.
    So they carry nothing about any particular save, and the gates are worth judging on the
    figures a real database gives.
    """
    return TransferWindowStats(markers=1_766, windows=54, incomplete=0)


def test_the_windows_are_read_in_stored_order() -> None:
    """The third record of the fixture carries no closing time, so it is not a window."""
    windows, stats = decode(career_tagged_stream())

    assert [(window.opens_month, window.closes_month) for window in windows] == [(7, 8), (1, 1)]
    assert stats == TransferWindowStats(markers=3, windows=2, incomplete=0)


def test_the_windows_carry_their_dates_season_offsets_and_unnamed_values() -> None:
    """The year is an offset from the season start, so 2000 reads 0 and 2001 reads 1.

    The winter window opens in the calendar year after the season starts, which is what its
    offset of 1 says, and it stores no window type at all, so that key is simply absent rather
    than guessed at.
    """
    summer_window, winter_window = decode(career_tagged_stream())[0]

    assert (summer_window.opens_day, summer_window.opens_month) == (1, 7)
    assert (summer_window.closes_day, summer_window.closes_month) == (31, 8)
    assert summer_window.opens_season_year_offset == 0
    assert summer_window.closes_season_year_offset == 0
    assert dict(summer_window.unknown) == {
        "close_time": SUMMER_WINDOW_CLOSE_TIME,
        "window_type": SUMMER_WINDOW_TYPE,
    }
    assert winter_window.opens_season_year_offset == 1
    assert winter_window.closes_season_year_offset == 1
    assert dict(winter_window.unknown) == {"close_time": WINTER_WINDOW_CLOSE_TIME}


def test_a_dated_record_without_a_closing_time_is_not_a_window() -> None:
    """Most dated records of this stream are not windows, and none of them counts as a fault."""
    stream = transfer_window_bytes(opens=(1, 7, 2000), closes=(31, 8, 2000), close_time=None)

    windows, stats = decode(stream)

    assert windows == ()
    assert stats == TransferWindowStats(markers=1, windows=0, incomplete=0)


def test_a_record_with_no_end_dates_is_incomplete() -> None:
    """A closing time with no end sub-list is a window whose dates did not decode."""
    start_only = transfer_window_bytes(opens=(1, 7, 2000), closes=(31, 8, 2000))
    end_list_at = start_only.index(b"tdne")
    stream = start_only[:end_list_at] + tagged_value_bytes("wnCT", 0x12, 2400)

    windows, stats = decode(stream)

    assert windows == ()
    assert stats.incomplete == 1


def test_a_date_outside_its_range_is_not_returned() -> None:
    """Every way a date can fall outside its range: month, day, year and the closing date."""
    out_of_range = {
        "month-13": ((1, 13, 2000), (31, 8, 2000)),
        "day-0": ((0, 7, 2000), (31, 8, 2000)),
        "year-below-the-season-base": ((1, 7, 1999), (31, 8, 2000)),
        "closing-day-32": ((1, 7, 2000), (32, 8, 2000)),
    }

    decoded = {
        label: decode(transfer_window_bytes(opens=opens, closes=closes))
        for label, (opens, closes) in out_of_range.items()
    }

    assert {label: windows for label, (windows, _) in decoded.items()} == dict.fromkeys(
        out_of_range, ()
    )
    assert {label: stats.incomplete for label, (_, stats) in decoded.items()} == dict.fromkeys(
        out_of_range, 1
    )


def test_a_closing_time_beyond_the_scan_window_is_not_returned() -> None:
    """The record ends at the closing time, so one pushed out of reach is never found."""
    padding_record = tagged_value_bytes("fill", TAGGED_U32_TYPES[0], 0)
    padding = padding_record * (WINDOW_LAYOUT.window_scan_bytes // len(padding_record) + 1)
    stream = transfer_window_bytes(opens=(1, 7, 2000), closes=(31, 8, 2000), filler=padding)

    windows, stats = decode(stream)

    assert windows == ()
    assert stats == TransferWindowStats(markers=1, windows=0, incomplete=0)


def test_the_columns_are_the_field_names_in_order() -> None:
    assert column_names(TransferWindow) == (
        "opens_day",
        "opens_month",
        "opens_season_year_offset",
        "closes_day",
        "closes_month",
        "closes_season_year_offset",
        "unknown_close_time",
        "unknown_window_type",
    )


def test_a_window_survives_pickle_and_deepcopy() -> None:
    """Records must survive both, so a caller can cache or send one across a process.

    The pickled bytes are this test's own record, built in this process from the fixture
    above; nothing here loads a pickle from anywhere else.
    """
    summer_window = decode(career_tagged_stream())[0][0]

    assert pickle.loads(pickle.dumps(summer_window)) == summer_window
    assert copy.deepcopy(summer_window) == summer_window


def test_the_table_is_cached_and_closing_stops_it(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        windows_table = career_save.transfer_windows()
        assert len(windows_table) == 2
        assert career_save.transfer_windows() is windows_table

    with pytest.raises(fmsave.SaveClosedError):
        career_save.transfer_windows()


def test_the_window_gates_apply_and_fail_one_at_a_time() -> None:
    """Healthy counts pass, and each way a decode can break fails the gate that watches it.

    A decode that finds nothing leaves the date share with no denominator, and that fails
    rather than passing quietly: it is the case a rate gate would otherwise wave through, and
    exactly what a layout that has moved looks like from the counts. Below the size threshold
    no gate applies at all, since a fragment cannot meet full-save counts.
    """
    healthy = healthy_window_stats()

    healthy_results = evaluate_transfer_windows(healthy, BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert tuple(result.name for result in healthy_results) == TRANSFER_WINDOW_GATE_NAMES
    assert all(result.applied and result.passed for result in healthy_results)

    broken = {
        "a-decode-that-finds-nothing": (
            {"windows": 0, "incomplete": 0},
            list(TRANSFER_WINDOW_GATE_NAMES),
        ),
        "just-under-the-count-floor": ({"windows": 9}, ["transfer_windows_minimum"]),
        "exactly-on-the-count-floor": ({"windows": 10}, []),
        "dates-that-stopped-decoding": (
            {"windows": 20, "incomplete": 34},
            ["transfer_window_dates"],
        ),
    }

    failures = {
        label: failed_gate_names(
            evaluate_transfer_windows(
                dataclasses.replace(healthy, **changes), BOUNDS, FULL_SIZE_GAME_DB_BYTES
            )
        )
        for label, (changes, _) in broken.items()
    }

    assert failures == {label: expected for label, (_, expected) in broken.items()}

    small_save_results = evaluate_transfer_windows(
        dataclasses.replace(healthy, windows=0, incomplete=0), BOUNDS, SMALL_GAME_DB_BYTES
    )

    assert all(not result.applied and result.passed for result in small_save_results)
