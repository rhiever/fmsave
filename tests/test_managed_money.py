"""The managed club's current balance and scouting budget, read where a build places them."""

from __future__ import annotations

import struct

import pytest

from fmsave._layouts import HumansLayout, find_layout
from fmsave._status import field_status
from fmsave.models.managed import ManagedClub
from fmsave.readers.clubs import ClubRecordSpan
from fmsave.readers.finances import find_finance_layouts, read_current_balance
from fmsave.readers.managed import scouting_budget
from tests.fixtures.career import career_finance_rows
from tests.fixtures.container import packed_date
from tests.fixtures.finances import (
    CLUB_FINANCE_TRAILING_BYTES,
    chain_gap_bytes,
    finance_chain_bytes,
    sponsor_chain_bytes,
)

FM26_BUILD = "26.3.2+2329565"
FM27_BUILD = "27.0.0+2486695"
GAME_DB_SCHEMA = 4000
HUMANS_SCHEMA = 24
FM27_FINANCES = find_finance_layouts(GAME_DB_SCHEMA, FM27_BUILD)
FM26_FINANCES = find_finance_layouts(GAME_DB_SCHEMA, FM26_BUILD)
FM27_HUMANS = find_layout(HumansLayout, "humans", HUMANS_SCHEMA, FM27_BUILD).layout
FM26_HUMANS = find_layout(HumansLayout, "humans", HUMANS_SCHEMA, FM26_BUILD).layout

CHAIN_PADDING_BYTES = 1_600
EXAMPLE_BALANCE = 1_234_567
# Two null dates, then eight fixed bytes, between the week date and the budget pair.
SCOUTING_MARKER = bytes.fromhex("01006c07 01006c07 40000002 0f2d0764")
WEEK_DATE = packed_date(200, 2031)


def club_record(
    *,
    balance: int = EXAMPLE_BALANCE,
    prefix_entries: tuple[bytes, ...] = (),
    with_chain: bool = True,
) -> bytes:
    """Zero padding, a monthly chain, its sponsor prefix carrying `balance`, no sponsors."""
    chain = finance_chain_bytes(career_finance_rows()) if with_chain else b""
    return (
        bytes(CHAIN_PADDING_BYTES)
        + chain
        + chain_gap_bytes(prefix_entries=prefix_entries, balance=balance)
        + sponsor_chain_bytes(())
        + bytes(CLUB_FINANCE_TRAILING_BYTES)
    )


def span_of(record: bytes) -> ClubRecordSpan:
    return ClubRecordSpan(club_uid=4001, record_start=0, record_end=len(record), team_list_end=None)


def scouting_block(budget: int, remaining: int, *, date: bytes = WEEK_DATE) -> bytes:
    return bytes(2) + date + SCOUTING_MARKER + struct.pack("<II", budget, remaining) + bytes(12)


def humans_bytes(*blocks: bytes) -> bytes:
    return bytes(40) + b"".join(block + bytes(24) for block in blocks)


@pytest.mark.parametrize("balance", [EXAMPLE_BALANCE, 0, -250_000])
def test_the_current_balance_is_the_word_behind_the_chains_sponsor_prefix(balance: int) -> None:
    record = club_record(balance=balance)
    assert read_current_balance(record, span_of(record), FM27_FINANCES) == balance


def test_the_balance_moves_with_the_counted_prefix_entries() -> None:
    record = club_record(prefix_entries=(bytes(19), bytes(19)))
    assert read_current_balance(record, span_of(record), FM27_FINANCES) == EXAMPLE_BALANCE


def test_a_record_of_the_other_shape_without_a_chain_gives_no_balance() -> None:
    # The same prefix and balance bytes, but no monthly chain in front of them: the record
    # shape a club with the smaller finance record has, which must never yield a balance.
    record = club_record(with_chain=False)
    assert read_current_balance(record, span_of(record), FM27_FINANCES) is None


def test_a_prefix_that_fails_its_checks_gives_no_balance() -> None:
    record = bytearray(club_record())
    suffix_marker_at = record.index(b"\xff\x00" + struct.pack("<i", EXAMPLE_BALANCE))
    record[suffix_marker_at] = 0x00
    assert read_current_balance(bytes(record), span_of(bytes(record)), FM27_FINANCES) is None


def test_a_balance_outside_the_chain_layouts_range_is_refused() -> None:
    lowest, _highest = FM27_FINANCES.chains.balance_range
    record = club_record(balance=lowest - 1)
    assert read_current_balance(record, span_of(record), FM27_FINANCES) is None


def test_fm26_has_no_balance_layout() -> None:
    assert FM26_FINANCES.sponsors.balance_offset is None
    record = club_record()
    assert read_current_balance(record, span_of(record), FM26_FINANCES) is None


def test_the_scouting_pair_with_money_is_the_budget_and_what_is_left() -> None:
    humans = humans_bytes(scouting_block(80_000, 72_500), scouting_block(0, 0))
    assert scouting_budget(humans, FM27_HUMANS) == (80_000, 72_500)


def test_a_zero_pair_before_the_budget_does_not_count() -> None:
    humans = humans_bytes(scouting_block(0, 0), scouting_block(80_000, 80_000))
    assert scouting_budget(humans, FM27_HUMANS) == (80_000, 80_000)


@pytest.mark.parametrize(
    "humans",
    [
        humans_bytes(),
        humans_bytes(scouting_block(0, 0), scouting_block(0, 0)),
        humans_bytes(scouting_block(80_000, 80_000), scouting_block(60_000, 60_000)),
        humans_bytes(scouting_block(80_000, 80_001)),
        humans_bytes(scouting_block(100_000_001, 0)),
        humans_bytes(scouting_block(80_000, 80_000, date=bytes(4))),
    ],
    ids=[
        "no-marker",
        "no-money",
        "two-pairs-with-money",
        "more-left-than-budgeted",
        "above-the-maximum",
        "no-date-in-front",
    ],
)
def test_an_ambiguous_or_implausible_scouting_pair_gives_none(humans: bytes) -> None:
    assert scouting_budget(humans, FM27_HUMANS) is None


def test_a_marker_at_either_edge_of_the_section_never_raises() -> None:
    assert scouting_budget(SCOUTING_MARKER + bytes(8), FM27_HUMANS) is None
    assert scouting_budget(WEEK_DATE + SCOUTING_MARKER + bytes(4), FM27_HUMANS) is None


def test_fm26_has_no_scouting_layout() -> None:
    assert FM26_HUMANS.scouting_budget_marker == b""
    humans = humans_bytes(scouting_block(80_000, 80_000))
    assert scouting_budget(humans, FM26_HUMANS) is None


def test_the_new_fields_default_to_none_and_carry_their_statuses() -> None:
    row = ManagedClub(4001, "Northbridge FC", "Northbridge", None, None)
    assert (row.balance, row.scouting_budget, row.scouting_budget_remaining) == (None, None, None)
    assert field_status(ManagedClub, "balance") == "verified"
    assert field_status(ManagedClub, "scouting_budget") == "unconfirmed"
    assert field_status(ManagedClub, "scouting_budget_remaining") == "unconfirmed"
