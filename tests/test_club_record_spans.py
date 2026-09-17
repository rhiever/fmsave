"""The byte ranges of club records, the humans selector, and the staff-list builder.

These three are shared: the finance reader works inside a club's own record, and later readers
of the same record and of the human manager join through the same two helpers.
"""

from __future__ import annotations

import struct
from itertools import pairwise
from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import ClubRecordLayout, HumansLayout, find_layout
from fmsave.readers._common import GAME_DB_SECTION, HUMANS_SECTION
from fmsave.readers.clubs import find_club_layouts, read_club_index
from fmsave.readers.managed import first_human_selector
from tests.fixtures.career import (
    ATHLETIC_UID,
    BUILD_STRING,
    GAME_DB_SCHEMA,
    NORTHBRIDGE_UID,
    SOUTHPORT_UID,
)
from tests.fixtures.game_db import club_record_bytes, game_db_body, humans_body

FILE_NAME = "career example.fm"
HUMANS_SCHEMA = 21
EXAMPLE_SELECTOR = 500
MISSING_SELECTOR = 0xFFFFFFFF


def humans_layout() -> HumansLayout:
    return find_layout(HumansLayout, HUMANS_SECTION, HUMANS_SCHEMA, BUILD_STRING).layout


def club_record_layout() -> ClubRecordLayout:
    return find_layout(ClubRecordLayout, GAME_DB_SECTION, GAME_DB_SCHEMA, BUILD_STRING).layout


def test_record_spans_cover_every_record_back_to_back(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        context = career_save._context
        with context.section(GAME_DB_SECTION) as game_db:
            spans = context.club_index().record_spans
            game_db_bytes = len(game_db)
    assert [span.club_uid for span in spans] == [NORTHBRIDGE_UID, SOUTHPORT_UID, ATHLETIC_UID]
    for span, next_span in pairwise(spans):
        assert span.record_end == next_span.record_start
    assert spans[-1].record_end == min(
        spans[-1].record_start + club_record_layout().stop_gap_bytes, game_db_bytes
    )


def test_every_team_list_end_points_at_the_affiliated_team_count(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        context = career_save._context
        with context.section(GAME_DB_SECTION) as game_db:
            spans = context.club_index().record_spans
            # Southport's team list is found by the float anchor alone, so its end is measured
            # from a different anchor than the other two clubs'.
            counts = [
                game_db[span.team_list_end] for span in spans if span.team_list_end is not None
            ]
    assert counts == [0, 0, 0]


def test_a_record_without_a_parsed_team_list_has_no_team_list_end() -> None:
    # A team count of zero is outside the layout's range, so neither anchor parses the list.
    record = club_record_bytes(
        club_index=1,
        uid=4001,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Northbridge FC",
        short_name="Northbridge",
        team_ids=(),
    )
    game_db = game_db_body([record], [], gap_bytes=256)
    layouts = find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING)
    club_index = read_club_index(game_db, layouts, FILE_NAME)
    assert [span.team_list_end for span in club_index.record_spans] == [None]


def test_the_first_human_selector_is_read_from_the_humans_section() -> None:
    layout = humans_layout()
    body = humans_body(count=1, selector=EXAMPLE_SELECTOR)
    assert first_human_selector(body, layout, FILE_NAME) == EXAMPLE_SELECTOR
    assert first_human_selector(humans_body(count=0, selector=0), layout, FILE_NAME) is None
    assert first_human_selector(humans_body(count=1, selector=0), layout, FILE_NAME) is None
    assert (
        first_human_selector(humans_body(count=1, selector=MISSING_SELECTOR), layout, FILE_NAME)
        is None
    )
    with pytest.raises(fmsave.CorruptSaveError, match=f"section {HUMANS_SECTION!r}"):
        first_human_selector(bytes(9), layout, FILE_NAME)


def example_record(
    *, staff_lists: tuple[tuple[int, ...], ...] | None = None, trailing_bytes: bytes = b""
) -> bytes:
    return club_record_bytes(
        club_index=1,
        uid=4001,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Northbridge FC",
        short_name="Northbridge",
        team_ids=(70001,),
        staff_lists=staff_lists,
        trailing_bytes=trailing_bytes,
    )


def test_staff_lists_are_written_after_the_affiliated_team_ids() -> None:
    # A record built without the new parameters is byte for byte the record the older
    # fragments hold, which is what keeps every other test built on them unchanged.
    without_lists = example_record()
    assert without_lists.endswith(struct.pack("<IB", 70001, 0))
    assert example_record(staff_lists=((501, 502), (), ())) == (
        without_lists + bytes([2]) + struct.pack("<II", 501, 502) + bytes(2)
    )
    assert example_record(trailing_bytes=b"\x07\x07") == without_lists + b"\x07\x07"
