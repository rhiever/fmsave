from __future__ import annotations

import copy
import dataclasses
import functools
import pickle
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fmsave
from fmsave._checks import GateResult, evaluate_injury_types
from fmsave._container import (
    DirectoryEntry,
    match_file_entries,
    read_directory_entry,
    read_index,
)
from fmsave._errors import SaveClosedError
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import InjuryTypeStats
from fmsave.export import column_names
from fmsave.models.injuries import InjuryType
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.injuries import (
    find_injury_type_layout,
    locate_injury_type_table,
    read_injury_types,
)
from tests.fixtures.career import CAREER_ATTACHMENTS, career_fragment
from tests.fixtures.injuries import (
    CAREER_INJURY_TYPES,
    TYPE_TABLE_TRAILER,
    injury_type_entries,
    injury_type_entry_bytes,
    match_file_body,
    match_file_magic_only,
)

GAME_DB_SCHEMA = 4000
MEBIBYTE = 1024 * 1024
FULL_SIZE_GAME_DB_BYTES = 100 * MEBIBYTE
SMALL_GAME_DB_BYTES = 1 * MEBIBYTE
INJURY_TYPE_GATE_NAME = "injury_type_entries_minimum"
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, "").layout
LAYOUT = find_injury_type_layout("")
# One below the gate's floor, and the count every save measured carries.
FAILING_TABLE_ENTRIES = 19
HEALTHY_TABLE_ENTRIES = 93
# More entries carrying the magic than the layout ever reads.
TABLE_LESS_ENTRY_COUNT = 5


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def decode(save_path: Path) -> tuple[tuple[InjuryType, ...], InjuryTypeStats]:
    """The type table as the reader builds it, from a save's own per-match entries."""
    container_index = read_index(save_path)
    return read_injury_types(
        match_file_entries(container_index),
        functools.partial(read_directory_entry, container_index),
        LAYOUT,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def healthy_stats(**overrides: int) -> InjuryTypeStats:
    """Counts as every save measured reports them, before any override."""
    fields = {
        "match_entries": 257,
        "entries_with_magic_tried": 1,
        "entries_without_magic": 0,
        "table_entries": HEALTHY_TABLE_ENTRIES,
    }
    return InjuryTypeStats(**(fields | overrides))


def table_payload(*records: bytes, leading_bytes: int = 16) -> bytes:
    """Raw records with the trailer after them, as the locator sees a payload."""
    return bytes(leading_bytes) + b"".join(records) + TYPE_TABLE_TRAILER


def test_the_injury_types_are_the_tables_own_records_in_stored_order(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        injury_types = save.injury_types()

    assert [(row.id, row.name) for row in injury_types] == [
        (type_id, name) for type_id, name, _flag, _second_id in CAREER_INJURY_TYPES
    ]
    assert injury_types[1].unknown == {"flag": 1, "second_id": 9}


def test_a_shorter_chain_and_an_entry_that_is_not_a_match_file_are_both_passed_over(
    career_path: Path,
) -> None:
    injury_types, stats = decode(career_path)

    assert [row.id for row in injury_types] == [
        type_id for type_id, _name, _flag, _second_id in CAREER_INJURY_TYPES
    ]
    assert stats == InjuryTypeStats(
        match_entries=len(CAREER_ATTACHMENTS),
        entries_with_magic_tried=1,
        entries_without_magic=1,
        table_entries=len(CAREER_INJURY_TYPES),
    )


def test_a_record_shorter_than_the_layout_allows_ends_a_chain() -> None:
    short_name_record = injury_type_entry_bytes(type_id=99, name="AB", flag=0, second_id=120)
    payload = table_payload(injury_type_entries(CAREER_INJURY_TYPES), short_name_record)

    assert [row[0] for row in locate_injury_type_table(payload, LAYOUT)] == [
        type_id for type_id, _name, _flag, _second_id in CAREER_INJURY_TYPES
    ]


def test_an_unprintable_text_byte_ends_a_chain() -> None:
    unprintable = bytearray(
        injury_type_entry_bytes(type_id=99, name="Example Ache", flag=0, second_id=120)
    )
    unprintable[7] = 0x7F
    payload = table_payload(injury_type_entries(CAREER_INJURY_TYPES), bytes(unprintable))

    assert len(locate_injury_type_table(payload, LAYOUT)) == len(CAREER_INJURY_TYPES)


def test_an_id_that_does_not_ascend_ends_a_chain() -> None:
    descending = injury_type_entry_bytes(type_id=6, name="Example Ache", flag=0, second_id=120)
    payload = table_payload(injury_type_entries(CAREER_INJURY_TYPES), descending)

    assert len(locate_injury_type_table(payload, LAYOUT)) == len(CAREER_INJURY_TYPES)


def test_a_flag_the_layout_does_not_allow_ends_a_chain() -> None:
    flagged = injury_type_entry_bytes(type_id=99, name="Example Ache", flag=2, second_id=120)
    payload = table_payload(injury_type_entries(CAREER_INJURY_TYPES), flagged)

    assert len(locate_injury_type_table(payload, LAYOUT)) == len(CAREER_INJURY_TYPES)


def test_the_trailer_after_the_table_never_parses() -> None:
    assert locate_injury_type_table(table_payload(), LAYOUT) == ()


def test_two_chains_of_the_same_length_settle_on_the_earlier_one() -> None:
    first_chain = injury_type_entries(((5, "Example Strain", 0, 6), (7, "Example Knock", 1, 9)))
    second_chain = injury_type_entries(((11, "Example Sprain", 0, 12), (12, "Example Cut", 0, 13)))
    payload = table_payload(first_chain, TYPE_TABLE_TRAILER, bytes(16), second_chain)

    assert [row[0] for row in locate_injury_type_table(payload, LAYOUT)] == [5, 7]


def test_the_next_entry_is_tried_when_the_first_holds_no_table(tmp_path: Path) -> None:
    attachments = (("1_2_2", ".apm", match_file_magic_only()), *CAREER_ATTACHMENTS)
    save_path = career_fragment(attachments=attachments).write(tmp_path / "career.bin")

    injury_types, stats = decode(save_path)

    assert len(injury_types) == len(CAREER_INJURY_TYPES)
    assert stats.entries_with_magic_tried == 2


def test_no_more_entries_are_read_than_the_layout_allows(tmp_path: Path) -> None:
    attachments = tuple(
        (f"1_2_{position}", ".apm", match_file_magic_only())
        for position in range(TABLE_LESS_ENTRY_COUNT)
    )
    save_path = career_fragment(attachments=attachments).write(tmp_path / "career.bin")

    injury_types, stats = decode(save_path)

    assert injury_types == ()
    assert stats.match_entries == TABLE_LESS_ENTRY_COUNT
    assert stats.entries_with_magic_tried == LAYOUT.maximum_entries_tried


def test_a_save_with_no_match_entry_has_no_injury_type_names(tmp_path: Path) -> None:
    save_path = career_fragment(attachments=()).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as save:
        injury_types = save.injury_types()

    _rows, stats = decode(save_path)
    assert len(injury_types) == 0
    assert stats == InjuryTypeStats(
        match_entries=0, entries_with_magic_tried=0, entries_without_magic=0, table_entries=0
    )


def test_the_columns_the_export_flattens() -> None:
    assert column_names(InjuryType) == ("id", "name", "unknown_flag", "unknown_second_id")


def test_a_row_survives_pickling_and_deep_copying(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        row = save.injury_types()[0]

    # A round trip of fmsave's own record, not data from anywhere else.
    assert pickle.loads(pickle.dumps(row)) == row
    assert copy.deepcopy(row) == row


def test_the_table_is_read_once_and_raises_after_the_save_is_closed(career_path: Path) -> None:
    with fmsave.open(career_path) as save:
        first_table = save.injury_types()
        assert save.injury_types() is first_table

    with pytest.raises(SaveClosedError):
        save.injury_types()


def test_too_few_table_entries_fail_the_gate_and_the_measured_count_passes() -> None:
    failing = evaluate_injury_types(
        healthy_stats(table_entries=FAILING_TABLE_ENTRIES), BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    passing = evaluate_injury_types(healthy_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(failing) == [INJURY_TYPE_GATE_NAME]
    assert failed_gate_names(passing) == []


def test_the_gate_does_not_apply_without_a_match_entry_or_on_a_small_game_db() -> None:
    without_entries = evaluate_injury_types(
        healthy_stats(match_entries=0, entries_with_magic_tried=0, table_entries=0),
        BOUNDS,
        FULL_SIZE_GAME_DB_BYTES,
    )
    small_game_db = evaluate_injury_types(
        healthy_stats(table_entries=0), BOUNDS, SMALL_GAME_DB_BYTES
    )

    assert [result.applied for result in without_entries] == [False]
    assert [result.applied for result in small_game_db] == [False]


@settings(max_examples=300, deadline=None)
@given(
    records=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=2**16 - 1),
            st.integers(min_value=LAYOUT.length_range[0], max_value=LAYOUT.length_range[1]),
            st.sampled_from(LAYOUT.flag_values),
            st.integers(min_value=0, max_value=2**32 - 1),
        ),
        max_size=12,
    ),
    fillers=st.lists(st.binary(max_size=24), max_size=13),
    tail=st.binary(max_size=512),
)
def test_records_among_random_bytes_never_raise_and_never_climb_backwards(
    records: list[tuple[int, int, int, int]],
    fillers: list[bytes],
    tail: bytes,
) -> None:
    """Real records, in whatever order and with whatever bytes between them, then random bytes.

    The ids are random, so chains break wherever an id does not climb, and the name lengths and
    flags cover the layout's whole range. What must hold whatever the payload is: the walk
    raises nothing, and the chain it settles on climbs.
    """
    payload = bytearray(match_file_body(()))
    for position, (type_id, name_length, flag, second_id) in enumerate(records):
        if position < len(fillers):
            payload.extend(fillers[position])
        payload.extend(
            injury_type_entry_bytes(
                type_id=type_id, name="E" * name_length, flag=flag, second_id=second_id
            )
        )
    payload.extend(tail)

    found = locate_injury_type_table(bytes(payload), LAYOUT)

    type_ids = [type_id for type_id, _name, _flag, _second_id in found]
    assert type_ids == sorted(set(type_ids))
    assert len(type_ids) != 1


@settings(max_examples=300, deadline=None)
@given(payload=st.binary(max_size=4096))
def test_random_payloads_never_raise(payload: bytes) -> None:
    assert locate_injury_type_table(match_file_body(()) + payload, LAYOUT) == ()


@pytest.mark.parametrize("missing_bytes", [1, 3, 7, 12, 20])
def test_a_payload_that_stops_inside_a_record_drops_it_and_raises_nothing(
    missing_bytes: int,
) -> None:
    """A truncated entry loses the records the bytes stop inside, and nothing else."""
    payload = match_file_body((injury_type_entries(CAREER_INJURY_TYPES),))
    kept = len(CAREER_INJURY_TYPES) - 1

    found = locate_injury_type_table(
        payload[: len(payload) - len(TYPE_TABLE_TRAILER) - missing_bytes], LAYOUT
    )

    assert [row[0] for row in found] == [
        type_id for type_id, _name, _flag, _second_id in CAREER_INJURY_TYPES[:kept]
    ]


def test_no_more_entries_are_decompressed_than_the_layout_allows(tmp_path: Path) -> None:
    """A save whose entries are none of them per-match files is still not read whole."""
    attachments = tuple(
        (f"1_3_{position}", ".apm", b"attachment")
        for position in range(LAYOUT.maximum_entries_opened + 3)
    )
    save_path = career_fragment(attachments=attachments).write(tmp_path / "career.bin")
    container_index = read_index(save_path)
    entries_read: list[str] = []

    def read_and_record(entry: DirectoryEntry) -> bytes:
        entries_read.append(entry.name)
        return read_directory_entry(container_index, entry)

    injury_types, stats = read_injury_types(
        match_file_entries(container_index), read_and_record, LAYOUT
    )

    assert len(injury_types) == 0
    assert len(entries_read) == LAYOUT.maximum_entries_opened
    assert stats.entries_without_magic == LAYOUT.maximum_entries_opened
    assert stats.entries_with_magic_tried == 0


def test_a_layout_whose_trailer_differs_is_a_programming_error() -> None:
    """The flag and the second id are read at fixed places after the text, so a layout that
    puts anything else there is refused rather than read from the wrong bytes.
    """
    other_trailer = dataclasses.replace(LAYOUT, trailer_bytes=LAYOUT.trailer_bytes + 1)
    payload = match_file_body((injury_type_entries(CAREER_INJURY_TYPES),))

    with pytest.raises(ValueError, match="injury type record trailer"):
        locate_injury_type_table(payload, other_trailer)


def test_a_layout_whose_head_offsets_differ_is_a_programming_error() -> None:
    """A head the seed pattern still matches but the record struct cannot read is refused."""
    other_head = dataclasses.replace(LAYOUT, id_offset=0, length_offset=2)
    payload = match_file_body((injury_type_entries(CAREER_INJURY_TYPES),))

    with pytest.raises(ValueError, match="injury type record head"):
        locate_injury_type_table(payload, other_head)


def test_a_layout_whose_length_range_cannot_be_a_seed_is_a_programming_error() -> None:
    too_wide = dataclasses.replace(LAYOUT, length_range=(3, 300))
    payload = match_file_body((injury_type_entries(CAREER_INJURY_TYPES),))

    with pytest.raises(ValueError, match="length range"):
        locate_injury_type_table(payload, too_wide)
