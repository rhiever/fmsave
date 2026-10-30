"""Fictional FM27 calendar fragments, built independently of production offsets."""

from __future__ import annotations

import json
import struct
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._layouts.fm26_26_3_2 import TRAINING as FM26_TRAINING
from fmsave.models.training import TeamTraining, TrainingWeek
from fmsave.readers.training import build_training_tables, walk_training_blocks
from fmsave.table import Table
from tests.fixtures.career import (
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    career_fragment,
)
from tests.fixtures.container import length_prefixed, packed_date, section_body

LAYOUT = replace(
    FM26_TRAINING,
    block_lead_byte=2,
    day_block_bytes=8,
    day_block_lead_byte=4,
    week_name_offset=62,
    week_record_fixed_bytes=80,
    header_entries_supported=False,
    mentoring_groups_supported=False,
)
TEAMS = frozenset({NORTHBRIDGE_TEAM_A})


def fm27_week(day: int, name: str) -> bytes:
    """Seven independently encoded eight-byte days, then the week's own label."""
    days = (b"\x04" + struct.pack("<3H", 11, 10, 6) + b"\x00") * 7
    return b"\x0b" + packed_date(day, 2031) + b"\x01" + days + length_prefixed(name) + bytes(14)


def fm27_section(
    *,
    days: tuple[int, ...] = (48, 55),
    names: tuple[str, ...] = ("Example Light", "Example Balanced"),
    header_count: int = 0,
    group_count: int = 0,
    entry_count: int = 1,
    claimed_weeks: int | None = None,
    team_id: int = NORTHBRIDGE_TEAM_A,
) -> bytes:
    payload = struct.pack("<II", 581, 1) + bytes(10) + struct.pack("<I", header_count)
    payload += bytes((1, 0, 0))
    payload += struct.pack("<IBI", team_id, 2, entry_count)
    payload += (b"\x05" + bytes(13)) * entry_count
    payload += struct.pack("<I", len(days) if claimed_weeks is None else claimed_weeks)
    payload += b"".join(fm27_week(day, name) for day, name in zip(days, names, strict=True))
    payload += bytes(36) + struct.pack("<I", group_count)
    return section_body(".dat", 32, payload)


def test_fm27_calendar_pairs_each_name_with_its_own_date() -> None:
    body = fm27_section()
    blocks, counts = walk_training_blocks(body, TEAMS, LAYOUT, "fictional.bin")

    assert len(blocks) == 1
    assert blocks[0].team_id == NORTHBRIDGE_TEAM_A
    assert blocks[0].weeks == (
        TrainingWeek(date(2031, 2, 17), "Example Light"),
        TrainingWeek(date(2031, 2, 24), "Example Balanced"),
    )
    assert blocks[0].groups == ()
    assert counts.weeks == 2
    assert counts.week_steps == counts.seven_day_steps == 1
    assert counts.undated_weeks == 0
    assert counts.blocks_end == len(body)


def test_fm27_multiple_team_blocks_consume_variable_length_week_names() -> None:
    first = fm27_section(days=(48,), names=("Example Light",))
    second = fm27_section(
        days=(55,), names=("Example Récovery " + "E" * 40,), team_id=NORTHBRIDGE_TEAM_B
    )
    # Both builders independently place their first block after the 33-byte section header.
    body = first + b"\x00" + second[33:]
    blocks, counts = walk_training_blocks(
        body, frozenset({NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B}), LAYOUT, "fictional.bin"
    )
    assert [block.team_id for block in blocks] == [NORTHBRIDGE_TEAM_A, NORTHBRIDGE_TEAM_B]
    assert blocks[1].weeks[0].schedule_name == "Example Récovery " + "E" * 40
    assert counts.blocks_end == len(body)
    assert counts.weeks == 2
    assert counts.week_steps == 0


def test_fm27_claimed_entry_count_is_bounded_by_fragment() -> None:
    body = bytearray(fm27_section())
    struct.pack_into("<I", body, 38, 2**32 - 1)
    with pytest.raises(ReaderCheckError, match="entries"):
        walk_training_blocks(bytes(body), TEAMS, LAYOUT, "fictional.bin")


def test_fm27_nonseven_day_step_is_not_counted_as_verified() -> None:
    _blocks, counts = walk_training_blocks(
        fm27_section(days=(48, 56)), TEAMS, LAYOUT, "fictional.bin"
    )
    assert counts.week_steps == 1
    assert counts.seven_day_steps == 0


@pytest.mark.parametrize("header_count", (1, 2**32 - 1))
def test_unobserved_nonempty_header_is_rejected_before_its_shape(header_count: int) -> None:
    with pytest.raises(UnsupportedGameError, match="header"):
        walk_training_blocks(
            fm27_section(header_count=header_count), TEAMS, LAYOUT, "fictional.bin"
        )


@pytest.mark.parametrize("group_count", (1, 2**32 - 1))
def test_unobserved_nonempty_mentoring_is_rejected_before_its_shape(group_count: int) -> None:
    with pytest.raises(UnsupportedGameError, match="mentoring"):
        walk_training_blocks(fm27_section(group_count=group_count), TEAMS, LAYOUT, "fictional.bin")


@pytest.mark.parametrize("offset", (42, 60, 65, 66))
def test_fm27_bad_entry_week_marker_or_day_lead_is_rejected(offset: int) -> None:
    # First entry starts at42, first week at60, marker at65, first day at66.
    body = bytearray(fm27_section())
    body[offset] ^= 0x01
    with pytest.raises(ReaderCheckError):
        walk_training_blocks(bytes(body), TEAMS, LAYOUT, "fictional.bin")


def test_fm27_wrong_block_lead_never_yields_a_calendar() -> None:
    body = bytearray(fm27_section())
    body[37] = 1
    blocks, counts = walk_training_blocks(bytes(body), TEAMS, LAYOUT, "fictional.bin")
    assert blocks == ()
    assert counts.blocks_end == 33


@pytest.mark.parametrize("claimed_weeks", (3, 2**32 - 1))
def test_fm27_week_count_cannot_run_beyond_fragment(claimed_weeks: int) -> None:
    with pytest.raises(ReaderCheckError):
        walk_training_blocks(
            fm27_section(claimed_weeks=claimed_weeks), TEAMS, LAYOUT, "fictional.bin"
        )


@pytest.mark.parametrize("length", (0, 29, 42, 61, 125, 145))
def test_fm27_truncated_header_entry_or_week_is_rejected(length: int) -> None:
    with pytest.raises(ReaderCheckError):
        walk_training_blocks(fm27_section()[:length], TEAMS, LAYOUT, "fictional.bin")


def test_unknown_library_exports_null_with_zero_coverage(tmp_path: Path) -> None:
    blocks, counts = walk_training_blocks(fm27_section(), TEAMS, LAYOUT, "fictional.bin")
    path = career_fragment().write(tmp_path / "fictional.bin")
    with fmsave.open(path) as save:
        rows, groups, stats = build_training_tables(
            blocks,
            None,
            save._context.club_index(),
            save._context.player_records(),
            save.players(),
            NORTHBRIDGE_UID,
            counts,
        )
    table = Table(rows, TeamTraining)
    assert len(table) == 1
    assert table[0].schedule_library is None
    assert groups == ()
    assert stats.library_entries == 0
    assert table.coverage["schedule_library"] == 0.0
    assert table.to_dicts(json_ready=True)[0]["schedule_library"] is None
    output = tmp_path / "training.json"
    table.write_json(output)
    assert json.loads(output.read_text())[0]["schedule_library"] is None


def test_known_empty_library_stays_distinct_from_unsupported() -> None:
    row = TeamTraining(NORTHBRIDGE_TEAM_A, NORTHBRIDGE_UID, "Northbridge FC", 0, (), ())
    table = Table((row,), TeamTraining)
    assert table.to_dicts(json_ready=True)[0]["schedule_library"] == []
    assert table.coverage["schedule_library"] == 1.0
