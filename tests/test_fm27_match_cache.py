"""Fictional owned FM27 cache declarations, never fabricated match output."""

from __future__ import annotations

import dataclasses
import struct
from datetime import date

import pytest

import fmsave.readers.matches as matches_module
from fmsave._errors import UnsupportedGameError
from fmsave._layouts import MatchRecordLayout
from fmsave._layouts.fm26_26_3_2 import MATCH_RECORDS
from fmsave.readers.match_cache import MatchCacheWalker
from fmsave.readers.matches import locate_match_records
from tests.fixtures.game_db import match_list_bytes, match_record_bytes
from tests.test_player_match_stats import synthetic_player_records

ABILITY = 30
NULL_DATE = b"\x01\x00\x6c\x07"
VALID_DATE = struct.pack("<HH", 100, 2032)


def fm27_layout() -> MatchRecordLayout:
    assert MATCH_RECORDS.cache_layout is not None
    cache = dataclasses.replace(
        MATCH_RECORDS.cache_layout,
        header_marker=b"\x0c\x07",
        reference_bytes=15,
        medical_row_bytes=33,
        nullable_suffix_bytes=(43, 60, 70, 14, 18),
        nullable_prefix_second_marker=b"\x01\x03",
        medical_row_lead_byte=3,
        nullable_suffix_first_marker=b"\x01\x04",
        nullable_suffix_first_date_offset=38,
    )
    return dataclasses.replace(MATCH_RECORDS, cache_layout=cache, nonempty_supported=False)


def fm27_prefix(*, typed_second: bool = False) -> bytes:
    # Deliberately independently sized bytes, not generated from the production layout.
    second = b"\x01\x03" + bytes(3) + VALID_DATE + bytes(3) if typed_second else b"\x00"
    return (
        bytes(159)
        + struct.pack("<I", 3)
        + b"\x0b\x07\x04"
        + b"\x93\x42\x17\x08\x0c\x07"
        + bytes(9)
        + b"\x00\x00"
        + struct.pack("<IHH", 2, 42, 65535)
        + b"\x00"
        + second
        + b"\x00"
        + b"\x02"
        + b"\x7b" * 31
        + NULL_DATE
        + b"\x00"
        + VALID_DATE
        + NULL_DATE
        + b"\x24\x35"
        + struct.pack("<I", 0)
        + b"\x19" * 12
        + b"\x00"
    )


def fm27_predecessor(*, medical: bool = False, typed_suffix: bool = False) -> bytes:
    row = bytearray(b"\x78" * 33)
    row[0] = 3
    row[3] = 0
    row[4:8] = VALID_DATE
    medical_part = b"\x01" + bytes(row) if medical else b"\x00"
    suffix = bytearray(b"\x01\x04" + b"\x67" * 41)
    suffix[38:42] = VALID_DATE
    suffix[42] = 0
    suffix_part = bytes(suffix) + bytes(4) if typed_suffix else bytes(5)
    return b"\x01" + medical_part + b"\x00" + suffix_part


@pytest.mark.parametrize(
    "declaration,state",
    [
        (b"\x00", "containing_null"),
        (fm27_predecessor() + b"\x00", "null"),
        (fm27_predecessor(medical=True, typed_suffix=True) + b"\x01\x00", "empty"),
    ],
    ids=("containing-null", "null", "explicit-empty"),
)
def test_absence_only_mode_requires_owned_declarations(declaration: bytes, state: str) -> None:
    data = fm27_prefix(typed_second=True) + declaration
    located = locate_match_records(
        data, synthetic_player_records((ABILITY,)), fm27_layout(), date(2032, 5, 1)
    )
    assert not located
    assert located.lists_found == located.lists_decoded == 0
    assert located.history_declarations is not None
    assert getattr(located.history_declarations, state) == 1
    assert located.history_declarations.unknown == 0


@pytest.mark.parametrize("declaration", [b"\x02", b"\x01", fm27_predecessor() + b"\x01\x01"])
def test_unknown_or_nonempty_does_not_reach_match_row_parser(
    declaration: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object) -> None:
        raise AssertionError("unproven FM27 match row parser must not run")

    monkeypatch.setattr(matches_module, "_read_match_record", forbidden)
    data = fm27_prefix() + declaration
    with pytest.raises(UnsupportedGameError):
        locate_match_records(
            data, synthetic_player_records((ABILITY,)), fm27_layout(), date(2032, 5, 1)
        )


@pytest.mark.parametrize("damage", ["header", "medical", "truncated", "shifted", "all-zero"])
def test_invalid_owned_grammar_never_establishes_absence(damage: str) -> None:
    prefix = fm27_prefix()
    data = bytearray(prefix + fm27_predecessor(medical=True) + b"\x00")
    ability = ABILITY
    if damage == "header":
        data[159 + 4 + 3 + 4] ^= 0xFF
    elif damage == "medical":
        data[len(prefix) + 2] = 2
    elif damage == "truncated":
        del data[len(prefix) :]
    elif damage == "shifted":
        ability += 1
    else:
        data[:] = bytes(len(data))
    with pytest.raises(UnsupportedGameError):
        locate_match_records(
            bytes(data), synthetic_player_records((ability,)), fm27_layout(), date(2032, 5, 1)
        )


def test_empty_declaration_with_complete_undeclared_child_fails_closed() -> None:
    record = match_record_bytes(
        day_of_year=100, year=2032, opponent_team_id=100, competition_id=12, played=False
    )
    child = match_list_bytes(record, team_id=100)[2:]
    data = fm27_prefix() + fm27_predecessor() + b"\x01\x00" + child
    with pytest.raises(UnsupportedGameError):
        locate_match_records(
            data, synthetic_player_records((ABILITY,)), fm27_layout(), date(2032, 5, 1)
        )


def test_absence_only_mode_rejects_missing_layout_or_population() -> None:
    for layout, offsets in (
        (dataclasses.replace(fm27_layout(), cache_layout=None), (ABILITY,)),
        (fm27_layout(), ()),
    ):
        with pytest.raises(UnsupportedGameError):
            locate_match_records(
                fm27_prefix() + b"\x00", synthetic_player_records(offsets), layout, date(2032, 5, 1)
            )


def test_new_typed_markers_do_not_silently_fit_the_fm26_cache_walk() -> None:
    assert MATCH_RECORDS.cache_layout is not None
    data = (
        fm27_prefix(typed_second=True) + fm27_predecessor(medical=True, typed_suffix=True) + b"\x00"
    )
    assert (
        MatchCacheWalker(MATCH_RECORDS.cache_layout).locate(data, ABILITY, len(data)).state
        == "unknown"
    )


def declared_layout() -> MatchRecordLayout:
    return dataclasses.replace(
        fm27_layout(), nonempty_supported=True, declared_histories_required=True
    )


def played_record(**fields: int) -> bytes:
    return match_record_bytes(
        day_of_year=100,
        year=2032,
        opponent_team_id=100,
        competition_id=12,
        played=True,
        **fields,
    )


def test_declared_mode_reads_a_populated_history_its_declaration_names() -> None:
    records = played_record(goals=2, minutes=90) + match_record_bytes(
        day_of_year=104, year=2032, opponent_team_id=101, competition_id=12, played=False
    )
    data = fm27_prefix() + fm27_predecessor() + match_list_bytes(records, team_id=100)
    located = locate_match_records(
        data, synthetic_player_records((ABILITY,)), declared_layout(), date(2032, 5, 1)
    )
    assert [(row.goals, row.has_stats) for row in located[0]] == [(2, True), (None, False)]
    assert located.lists_found == located.lists_decoded == 1
    assert located.history_declarations is not None
    assert located.history_declarations.nonempty == 1
    assert located.history_declarations.unknown == 0


def test_declared_mode_reads_a_proven_empty_save_as_no_rows() -> None:
    data = fm27_prefix() + fm27_predecessor() + b"\x00"
    located = locate_match_records(
        data, synthetic_player_records((ABILITY,)), declared_layout(), date(2032, 5, 1)
    )
    assert not located
    assert located.history_declarations is not None
    assert located.history_declarations.null == 1


@pytest.mark.parametrize("damage", ["short-list", "undeclared-list", "unknown-declaration"])
def test_declared_mode_fails_closed_when_declarations_and_lists_disagree(damage: str) -> None:
    child = match_list_bytes(played_record(), team_id=100)
    if damage == "short-list":
        # The declaration names a populated history whose list claims a record it lacks.
        listed = bytearray(child)
        struct.pack_into("<I", listed, 8, 2)
        declaration = bytes(listed)
    elif damage == "undeclared-list":
        # A null declaration, then a complete list no declaration names.
        declaration = b"\x00" + child
    else:
        declaration = b"\x02" + child
    data = fm27_prefix() + fm27_predecessor() + declaration
    with pytest.raises(UnsupportedGameError, match="declaration"):
        locate_match_records(
            data, synthetic_player_records((ABILITY,)), declared_layout(), date(2032, 5, 1)
        )


def test_declared_mode_rejects_a_save_without_players() -> None:
    with pytest.raises(UnsupportedGameError, match="declaration"):
        locate_match_records(
            fm27_prefix() + b"\x00",
            synthetic_player_records(()),
            declared_layout(),
            date(2032, 5, 1),
        )


def test_default_layout_keeps_reading_lists_without_declarations() -> None:
    data = bytes(40) + match_list_bytes(played_record(), team_id=100)
    located = locate_match_records(
        data, synthetic_player_records((ABILITY,)), MATCH_RECORDS, date(2032, 5, 1)
    )
    assert len(located[0]) == 1
