"""Monthly finance snapshots and sponsor contracts, as a club record holds them.

This module must never import fmsave: a wrong offset inside fmsave has to fail tests built
here. All values are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from tests.fixtures.container import packed_date

FINANCE_ROW_BYTES = 49
FINANCE_ROW_TAG = 0x01
SPONSOR_ROW_BYTES = 25
SPONSOR_ROW_TAG = 0x02
# What the bytes between the two chains hold: the date of day 1 of 1900 where the chain ends, a
# pair of sevens, and the one byte in that stretch whose values look like a facility rating.
CHAIN_GAP_LEADING_DATE = packed_date(1, 1900)
CHAIN_GAP_SEVENS_OFFSET = 28
CHAIN_GAP_FACILITY_OFFSET = 50
CHAIN_GAP_BYTES = 140
# Padding between the second, dead sponsor run and the first one, and after the last chain.
DEAD_SPONSOR_GAP_BYTES = 30
CLUB_FINANCE_TRAILING_BYTES = 64


def finance_row_bytes(
    *,
    balance: int,
    transfer_allocated: int,
    transfer_remaining: int,
    wage_budget_weekly: int,
    wage_payroll_weekly: int,
    income_excluding_transfers: int,
    net_transfers: int,
    wage_bill: int,
    net: int,
    expenditure_excluding_transfers: int,
    total_income: int,
    total_expenditure: int,
) -> bytes:
    """One 49-byte monthly snapshot row, written forward in the order the format lays it out.

    The tag byte, three signed money words, the two weekly unsigned words, then the seven
    signed words of the month's income and expenditure.
    """
    return (
        struct.pack("<B3i", FINANCE_ROW_TAG, balance, transfer_allocated, transfer_remaining)
        + struct.pack("<2I", wage_budget_weekly, wage_payroll_weekly)
        + struct.pack(
            "<7i",
            income_excluding_transfers,
            net_transfers,
            wage_bill,
            net,
            expenditure_excluding_transfers,
            total_income,
            total_expenditure,
        )
    )


def finance_chain_bytes(rows: Sequence[bytes]) -> bytes:
    """The u32 row count, then the rows back to back."""
    return struct.pack("<I", len(rows)) + b"".join(rows)


def chain_gap_bytes(*, facility_byte: int = 17, length: int = CHAIN_GAP_BYTES) -> bytes:
    """The bytes between a club's snapshot chain and its sponsor chain.

    The date of day 1 of 1900 where the chain ends, a pair of sevens, the facility-shaped byte,
    and zeros everywhere else.
    """
    output = bytearray(length)
    output[: len(CHAIN_GAP_LEADING_DATE)] = CHAIN_GAP_LEADING_DATE
    struct.pack_into("<II", output, CHAIN_GAP_SEVENS_OFFSET, 7, 7)
    output[CHAIN_GAP_FACILITY_OFFSET] = facility_byte
    return bytes(output)


def sponsor_row_bytes(
    *,
    sponsor_type: int,
    start: bytes,
    end: bytes,
    flag10: int,
    total: int,
    u15: int,
    b17: int,
    enum18: int,
    b19: int,
    annual: int,
) -> bytes:
    """One 25-byte sponsor row, written forward in the order the format lays it out.

    The tag byte, the type code, the start and end dates, the 0/1 flag, the total value, the
    three unidentified small fields, a zero byte, and the annual value.
    """
    return (
        bytes((SPONSOR_ROW_TAG, sponsor_type))
        + start
        + end
        + bytes((flag10,))
        + struct.pack("<IHBBB", total, u15, b17, enum18, b19)
        + bytes(1)
        + struct.pack("<I", annual)
    )


def sponsor_chain_bytes(rows: Sequence[bytes]) -> bytes:
    """The u8 row count, then the rows back to back."""
    return bytes((len(rows),)) + b"".join(rows)


def club_finance_bytes(
    *,
    rows: Sequence[bytes],
    sponsors: Sequence[bytes],
    padding_bytes: int = 1_200,
    facility_byte: int = 17,
    dead_sponsors: Sequence[bytes] = (),
) -> bytes:
    """One club record's finance bytes: padding, the snapshot chain, the gap, the sponsors.

    `padding_bytes` of zeros come first, so the record is long enough for a reader that skips
    short records to search it at all. `dead_sponsors` writes a second, dead sponsor run after
    the first one, which is what a handful of clubs hold and what a reader taking the longest
    run rather than the first one would read instead.
    """
    output = bytearray(padding_bytes)
    output.extend(finance_chain_bytes(rows))
    output.extend(chain_gap_bytes(facility_byte=facility_byte))
    output.extend(sponsor_chain_bytes(sponsors))
    if dead_sponsors:
        output.extend(bytes(DEAD_SPONSOR_GAP_BYTES))
        output.extend(sponsor_chain_bytes(dead_sponsors))
    output.extend(bytes(CLUB_FINANCE_TRAILING_BYTES))
    return bytes(output)
