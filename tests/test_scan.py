from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fmsave._errors import CorruptSaveError
from fmsave._scan import (
    decode_date,
    decode_time_slot,
    find_marker,
    iter_markers,
    read_i16,
    read_i32,
    read_length_prefixed_string,
    read_u8,
    read_u16,
    read_u32,
    read_u64,
)


def test_integer_reads_are_little_endian() -> None:
    sample_bytes = bytes.fromhex("ff 34 12 78 56 34 12 fe ff ff ff 01 00 00 00 00 00 00 80")
    assert read_u8(sample_bytes, 0) == 0xFF
    assert read_u16(sample_bytes, 1) == 0x1234
    assert read_u32(sample_bytes, 3) == 0x12345678
    assert read_i32(sample_bytes, 7) == -2
    assert read_i16(bytes.fromhex("feff"), 0) == -2
    assert read_u64(sample_bytes, 11) == 0x8000000000000001


@pytest.mark.parametrize("buffer_type", [bytes, bytearray, memoryview])
def test_reads_accept_every_buffer_type(buffer_type: type) -> None:
    assert read_u32(buffer_type(bytes.fromhex("0a000000")), 0) == 10


@pytest.mark.parametrize("offset", [-1, 3, 100])
def test_out_of_bounds_reads_raise_corrupt_save_error(offset: int) -> None:
    with pytest.raises(CorruptSaveError):
        read_u16(bytes(4), offset)


def test_length_prefixed_string() -> None:
    encoded = bytes.fromhex("05000000") + b"Hello" + b"tail"
    assert read_length_prefixed_string(encoded, 0, 64) == ("Hello", 9)


def test_length_prefixed_string_non_ascii() -> None:
    text = "Łukasz Exämple"
    encoded = len(text.encode()).to_bytes(4, "little") + text.encode()
    assert read_length_prefixed_string(encoded, 0, 64) == (text, len(encoded))


@pytest.mark.parametrize(
    "encoded",
    [
        bytes.fromhex("41000000") + b"A" * 65,  # longer than max_length 64
        bytes.fromhex("05000000") + b"Hi",  # truncated
        bytes.fromhex("02000000") + b"\xff\xfe",  # invalid UTF-8
        bytes.fromhex("0500"),  # truncated length
    ],
)
def test_bad_length_prefixed_strings_raise(encoded: bytes) -> None:
    with pytest.raises(CorruptSaveError):
        read_length_prefixed_string(encoded, 0, 64)


def test_decode_first_day_of_year() -> None:
    assert decode_date(bytes.fromhex("0100 ee07"), 0) == date(2030, 1, 1)


def test_decode_date_with_time_slot() -> None:
    # day 60, slot 66 -> 60 | 66 << 9 = 0x843c ; year 2031 = 0x07ef ; 2031 is not a leap year
    packed = bytes.fromhex("3c84 ef07")
    assert decode_date(packed, 0) == date(2031, 3, 1)
    assert decode_time_slot(packed, 0) == 66


@pytest.mark.parametrize(
    ("hex_bytes", "expected"),
    [
        ("0000 6c07", None),  # day 0, year 1900: the null date
        ("0100 6c07", None),  # year 1900 is not a real game year
        ("6f01 ef07", None),  # day 367
        ("6e01 ef07", None),  # day 366 in 2031 (not a leap year)
        ("6e01 f007", date(2032, 12, 31)),  # day 366 in 2032
        ("0100 9908", None),  # year 2201
    ],
)
def test_decode_date_edge_cases(hex_bytes: str, expected: date | None) -> None:
    assert decode_date(bytes.fromhex(hex_bytes), 0) == expected


def test_decode_date_out_of_bounds_raises() -> None:
    with pytest.raises(CorruptSaveError):
        decode_date(bytes(3), 0)


@given(
    day_of_year=st.integers(min_value=1, max_value=365),
    year=st.integers(min_value=1901, max_value=2200),
    time_slot=st.integers(min_value=0, max_value=127),
)
def test_decode_date_round_trip(day_of_year: int, year: int, time_slot: int) -> None:
    packed = (day_of_year | time_slot << 9).to_bytes(2, "little") + year.to_bytes(2, "little")
    assert decode_date(packed, 0) == date(year, 1, 1) + timedelta(days=day_of_year - 1)
    assert decode_time_slot(packed, 0) == time_slot


def test_find_marker_is_bounded() -> None:
    haystack = b"..ABC..ABC"
    assert find_marker(haystack, b"ABC", 0, len(haystack)) == 2
    assert find_marker(haystack, b"ABC", 3, len(haystack)) == 7
    assert find_marker(haystack, b"ABC", 0, 4) == -1  # marker would cross the end bound


def test_iter_markers_yields_overlapping_matches() -> None:
    assert list(iter_markers(b"aaaa", b"aa", 0, 4)) == [0, 1, 2]


@pytest.mark.parametrize(("start", "end"), [(-1, 2), (0, 11), (5, 4)])
def test_search_bounds_are_validated(start: int, end: int) -> None:
    with pytest.raises(CorruptSaveError):
        find_marker(bytes(10), b"x", start, end)


def test_empty_marker_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        find_marker(bytes(10), b"", 0, 10)


@settings(max_examples=300)
@given(buffer=st.binary(max_size=32), offset=st.integers(min_value=-40, max_value=40))
def test_reads_only_raise_corrupt_save_error(buffer: bytes, offset: int) -> None:
    for reader in (
        read_u8,
        read_u16,
        read_i16,
        read_u32,
        read_i32,
        read_u64,
        decode_date,
        decode_time_slot,
    ):
        try:
            reader(buffer, offset)
        except CorruptSaveError:
            pass
    try:
        read_length_prefixed_string(buffer, offset, 16)
    except CorruptSaveError:
        pass
