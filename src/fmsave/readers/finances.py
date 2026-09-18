"""A club's monthly finance snapshots and its sponsor contracts, inside its own club record.

Both structures sit inside the club record the club scan already found, so this reader works
span by span rather than searching all of `game_db`. In each record it looks for the chain of
monthly snapshots first: a tagged row count followed by that many fixed-size rows, all of whose
balances and weekly wage figures are inside the bounds the layout carries. The sponsor
contracts follow the chain, as a counted run of their own, and the **first** such run is the
club's list: a few clubs keep a second, dead run behind it.

Only the clubs of the one or two league nations a save tracks keep a series at all, so most
clubs yield no row, which is ordinary rather than a fault.
"""

from __future__ import annotations

import functools
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from fmsave._frozen import FrozenMapping
from fmsave._layouts import FinanceChainLayout, SponsorChainLayout, find_layout
from fmsave._reader_stats import FinanceStats
from fmsave._scan import decode_date, read_u16
from fmsave.models.common import CodedValue
from fmsave.models.finances import FinanceMonth, Sponsorship, SponsorType
from fmsave.readers._common import GAME_DB_SECTION, build_gap_padded_struct
from fmsave.readers.clubs import ClubIndex, ClubRecordSpan

_MONTHS_PER_YEAR = 12
_ROW_COUNT_STRUCT = struct.Struct("<I")

_FINANCE_ROW_FIELDS = (
    "balance",
    "transfer_allocated",
    "transfer_remaining",
    "wage_budget",
    "wage_payroll",
    "income_excluding_transfers",
    "net_transfers",
    "wage_bill",
    "net",
    "expenditure_excluding_transfers",
    "total_income",
    "total_expenditure",
)


@dataclass(frozen=True, slots=True)
class FinanceLayouts:
    """The layouts the finance reader uses."""

    chains: FinanceChainLayout
    sponsors: SponsorChainLayout


def find_finance_layouts(game_db_schema: int | None, build: str) -> FinanceLayouts:
    """Look up the finance layouts for a `game_db` schema, falling back to the build."""
    return FinanceLayouts(
        chains=find_layout(FinanceChainLayout, GAME_DB_SECTION, game_db_schema, build).layout,
        sponsors=find_layout(SponsorChainLayout, GAME_DB_SECTION, game_db_schema, build).layout,
    )


@dataclass(frozen=True, slots=True)
class _FinanceRowReader:
    """One layout's row struct and the positions of the fields in what it unpacks.

    `row_struct` unpacks a whole row from its start; `index_by_name` gives each field's place in
    the result, and `tag_index`, `balance_index`, `wage_budget_index` and `wage_payroll_index`
    are the four the locator judges a candidate row by.
    """

    row_struct: struct.Struct
    index_by_name: Mapping[str, int]
    tag_index: int
    balance_index: int
    wage_budget_index: int
    wage_payroll_index: int


@functools.cache
def _finance_row_reader(layout: FinanceChainLayout) -> _FinanceRowReader:
    """The layout's row struct, built on first use for each layout.

    Raises:
        ValueError: Two row fields overlap, or a field starts before the row's tag byte.
    """
    row_struct, _start_offset, index_by_name = build_gap_padded_struct(
        [
            (0, "B", "tag"),
            (layout.balance_offset, "i", "balance"),
            (layout.transfer_allocated_offset, "i", "transfer_allocated"),
            (layout.transfer_remaining_offset, "i", "transfer_remaining"),
            (layout.wage_budget_offset, "I", "wage_budget"),
            (layout.wage_payroll_offset, "I", "wage_payroll"),
            (layout.income_excluding_transfers_offset, "i", "income_excluding_transfers"),
            (layout.net_transfers_offset, "i", "net_transfers"),
            (layout.wage_bill_offset, "i", "wage_bill"),
            (layout.net_offset, "i", "net"),
            (
                layout.expenditure_excluding_transfers_offset,
                "i",
                "expenditure_excluding_transfers",
            ),
            (layout.total_income_offset, "i", "total_income"),
            (layout.total_expenditure_offset, "i", "total_expenditure"),
        ],
        start_offset=0,
    )
    return _FinanceRowReader(
        row_struct=row_struct,
        index_by_name=FrozenMapping(index_by_name),
        tag_index=index_by_name["tag"],
        balance_index=index_by_name["balance"],
        wage_budget_index=index_by_name["wage_budget"],
        wage_payroll_index=index_by_name["wage_payroll"],
    )


@functools.cache
def _sponsor_row_struct(layout: SponsorChainLayout) -> tuple[struct.Struct, Mapping[str, int]]:
    """The layout's sponsor row struct and the position of each field in what it unpacks.

    The two dates stay in the struct only so the build-time overlap check covers their bytes;
    their values are read by `decode_date`, never from the unpacked tuple.

    Raises:
        ValueError: Two row fields overlap, or a field starts before the row's tag byte.
    """
    row_struct, _start_offset, index_by_name = build_gap_padded_struct(
        [
            (0, "B", "tag"),
            (layout.type_offset, "B", "type"),
            (layout.start_offset, "I", "start"),
            (layout.end_offset, "I", "end"),
            (layout.flag10_offset, "B", "flag10"),
            (layout.total_offset, "I", "total"),
            (layout.u15_offset, "H", "u15"),
            (layout.b17_offset, "B", "b17"),
            (layout.enum18_offset, "B", "enum18"),
            (layout.b19_offset, "B", "b19"),
            (layout.annual_offset, "I", "annual"),
        ],
        start_offset=0,
    )
    return row_struct, FrozenMapping(index_by_name)


def searched_record(span: ClubRecordSpan, layout: FinanceChainLayout) -> bool:
    """Whether a club record is long enough to be searched for a finance chain.

    Every record holding a chain on the saves measured is at least 2,347 bytes, so this filter
    costs no club its series and skips most records. It is the one place the size is judged: the
    locator and the pass that counts searched records both ask here.
    """
    return span.record_end - span.record_start >= layout.minimum_record_bytes


def locate_finance_chain(
    game_db: bytes, span: ClubRecordSpan, layout: FinanceChainLayout
) -> tuple[int, int, int] | None:
    """(first row offset, row count, chains found) for a club record, or None for no chain.

    A record shorter than the layout's minimum is not searched at all, which costs no club a
    series and skips most records. A chain is accepted only when its stored count is inside the
    layout's range, the whole chain fits inside the record, and every row carries the tag, a
    balance inside the layout's range and weekly wage figures no larger than its ceiling. The
    search resumes past an accepted chain, so a row inside it can never open a chain of its
    own, and the count says whether a second chain follows the one that is returned.
    """
    if not searched_record(span, layout):
        return None
    record_start = span.record_start
    record_end = span.record_end
    reader = _finance_row_reader(layout)
    unpack_row = reader.row_struct.unpack_from
    row_bytes = layout.row_bytes
    tag = layout.tag
    tag_byte = bytes((tag,))
    tag_index = reader.tag_index
    balance_index = reader.balance_index
    wage_budget_index = reader.wage_budget_index
    wage_payroll_index = reader.wage_payroll_index
    lowest_count, highest_count = layout.count_range
    lowest_balance, highest_balance = layout.balance_range
    weekly_maximum = layout.weekly_maximum
    unpack_row_count = _ROW_COUNT_STRUCT.unpack_from
    find_tag = game_db.find
    # The row count sits in front of the first row, so a head cannot start before there is room
    # for it inside the record.
    position = record_start - min(layout.count_offset, 0)
    first_chain: tuple[int, int] | None = None
    chains_found = 0
    head = find_tag(tag_byte, position, record_end)
    while head >= 0:
        row_count: int = unpack_row_count(game_db, head + layout.count_offset)[0]
        chain_end = head + row_bytes * row_count
        if lowest_count <= row_count <= highest_count and chain_end <= record_end:
            accepted = True
            for row_offset in range(head, chain_end, row_bytes):
                row = unpack_row(game_db, row_offset)
                if (
                    row[tag_index] != tag
                    or not lowest_balance <= row[balance_index] <= highest_balance
                    or row[wage_budget_index] > weekly_maximum
                    or row[wage_payroll_index] > weekly_maximum
                ):
                    accepted = False
                    break
            if accepted:
                chains_found += 1
                if first_chain is None:
                    first_chain = (head, row_count)
                head = find_tag(tag_byte, chain_end, record_end)
                continue
        head = find_tag(tag_byte, head + 1, record_end)
    if first_chain is None:
        return None
    return first_chain[0], first_chain[1], chains_found


def locate_sponsor_chain(
    game_db: bytes, search_start: int, record_end: int, layout: SponsorChainLayout
) -> tuple[int, int] | None:
    """(first row offset, row count) of the first sponsor run after `search_start`, or None.

    A run is accepted when its count byte is at least one, the whole run fits before
    `record_end`, and every row carries the tag, a flag no larger than the layout's maximum, a
    start and an end date inside the layout's year range with the end after the start, and an
    annual value no greater than a total value inside the layout's ceiling.
    """
    row_struct, index_by_name = _sponsor_row_struct(layout)
    unpack_row = row_struct.unpack_from
    row_bytes = layout.row_bytes
    tag = layout.tag
    tag_byte = bytes((tag,))
    tag_index = index_by_name["tag"]
    flag10_index = index_by_name["flag10"]
    total_index = index_by_name["total"]
    annual_index = index_by_name["annual"]
    flag10_maximum = layout.flag10_maximum
    value_maximum = layout.value_maximum
    start_offset = layout.start_offset
    end_offset = layout.end_offset
    earliest_year, latest_year = layout.year_range
    find_tag = game_db.find
    # The count byte sits in front of the first row, so the earliest run starts one byte past
    # the offset the search begins at.
    first_row = find_tag(tag_byte, search_start - min(layout.count_offset, 0), record_end)
    while first_row >= 0:
        row_count = game_db[first_row + layout.count_offset]
        run_end = first_row + row_bytes * row_count
        if row_count >= 1 and run_end <= record_end:
            accepted = True
            for row_offset in range(first_row, run_end, row_bytes):
                row = unpack_row(game_db, row_offset)
                total_value: int = row[total_index]
                if (
                    row[tag_index] != tag
                    or row[flag10_index] > flag10_maximum
                    or total_value > value_maximum
                    or row[annual_index] > total_value
                ):
                    accepted = False
                    break
                start = _sponsor_date(
                    game_db, row_offset + start_offset, earliest_year, latest_year
                )
                end = _sponsor_date(game_db, row_offset + end_offset, earliest_year, latest_year)
                if start is None or end is None or end <= start:
                    accepted = False
                    break
            if accepted:
                return first_row, row_count
        first_row = find_tag(tag_byte, first_row + 1, record_end)
    return None


def _sponsor_date(game_db: bytes, offset: int, earliest_year: int, latest_year: int) -> date | None:
    """A sponsor row's date, or None when it does not decode inside the layout's year range."""
    if not earliest_year <= read_u16(game_db, offset + 2) <= latest_year:
        return None
    return decode_date(game_db, offset)


def month_labels(clock: date, row_count: int, month_lag: int) -> tuple[date, ...]:
    """The first day of the month each row of a series covers, oldest first.

    The last row is `month_lag` months before the month the save's clock falls in, so with a
    lag of one it is the month before it.
    """
    last_month_number = clock.year * _MONTHS_PER_YEAR + clock.month - 1 - month_lag
    return tuple(
        date(month_number // _MONTHS_PER_YEAR, month_number % _MONTHS_PER_YEAR + 1, 1)
        for month_number in range(last_month_number - row_count + 1, last_month_number + 1)
    )


def read_club_finances(
    game_db: bytes,
    club_index: ClubIndex,
    clock: date,
    layouts: FinanceLayouts,
    managed_club_exists: bool,
) -> tuple[tuple[FinanceMonth, ...], tuple[Sponsorship, ...], FinanceStats]:
    """Every club's monthly finance rows and sponsor contracts, with what the pass counted.

    Clubs come in club index order and each club's months oldest first; its sponsors keep the
    order the save stores them in. A club whose record holds no chain yields no row at all,
    which is what most clubs of a save look like, and a save whose clubs hold none yields an
    empty table. Nothing here is a structural error, so this takes no file name: every value it
    reads lies inside a record the club scan has already accepted, and a record that holds no
    chain is a fact about the save rather than a layout that has moved.
    """
    chain_layout = layouts.chains
    reader = _finance_row_reader(chain_layout)
    unpack_row = reader.row_struct.unpack_from
    index_by_name = reader.index_by_name
    field_indexes = tuple(index_by_name[field_name] for field_name in _FINANCE_ROW_FIELDS)
    row_bytes = chain_layout.row_bytes
    month_lag = chain_layout.month_lag
    sponsor_layout = layouts.sponsors
    span_by_club_uid = {span.club_uid: span for span in club_index.record_spans}

    months: list[FinanceMonth] = []
    sponsorships: list[Sponsorship] = []
    records_searched = 0
    clubs_with_series = 0
    clubs_with_two_chains = 0
    net_identity_rows = 0
    balance_steps = 0
    balance_continuous_steps = 0
    expenditure_split_rows = 0
    clubs_with_sponsors = 0
    for club in club_index.clubs:
        span = span_by_club_uid.get(club.uid)
        if span is None or not searched_record(span, chain_layout):
            continue
        records_searched += 1
        located_chain = locate_finance_chain(game_db, span, chain_layout)
        if located_chain is None:
            continue
        head, row_count, chains_found = located_chain
        clubs_with_series += 1
        if chains_found > 1:
            clubs_with_two_chains += 1
        previous_balance: int | None = None
        for month, row_offset in zip(
            month_labels(clock, row_count, month_lag),
            range(head, head + row_bytes * row_count, row_bytes),
            strict=True,
        ):
            row = unpack_row(game_db, row_offset)
            (
                balance,
                transfer_allocated,
                transfer_remaining,
                wage_budget,
                wage_payroll,
                income_excluding_transfers,
                net_transfers,
                wage_bill,
                net,
                expenditure_excluding_transfers,
                total_income,
                total_expenditure,
            ) = (row[field_index] for field_index in field_indexes)
            months.append(
                FinanceMonth(
                    club_uid=club.uid,
                    club_name=club.name,
                    month=month,
                    balance=balance,
                    transfer_budget_allocated=transfer_allocated,
                    transfer_budget_remaining=transfer_remaining,
                    wage_budget_weekly=wage_budget,
                    wage_payroll_weekly=wage_payroll,
                    income_excluding_transfers=income_excluding_transfers,
                    net_transfers=net_transfers,
                    wage_bill=wage_bill,
                    net=net,
                    expenditure_excluding_transfers=expenditure_excluding_transfers,
                    total_income=total_income,
                    total_expenditure=total_expenditure,
                )
            )
            if net == total_income - total_expenditure:
                net_identity_rows += 1
            if 0 <= expenditure_excluding_transfers <= total_expenditure:
                expenditure_split_rows += 1
            if previous_balance is not None:
                balance_steps += 1
                if balance == previous_balance + net:
                    balance_continuous_steps += 1
            previous_balance = balance
        located_run = locate_sponsor_chain(
            game_db, head + row_bytes * row_count, span.record_end, sponsor_layout
        )
        if located_run is None:
            continue
        clubs_with_sponsors += 1
        sponsorships.extend(
            _club_sponsorships(game_db, club.uid, club.name, located_run, sponsor_layout)
        )
    return (
        tuple(months),
        tuple(sponsorships),
        FinanceStats(
            records_searched=records_searched,
            clubs_with_series=clubs_with_series,
            clubs_with_two_chains=clubs_with_two_chains,
            rows=len(months),
            net_identity_rows=net_identity_rows,
            balance_steps=balance_steps,
            balance_continuous_steps=balance_continuous_steps,
            expenditure_split_rows=expenditure_split_rows,
            clubs_with_sponsors=clubs_with_sponsors,
            sponsor_rows=len(sponsorships),
            managed_club_exists=managed_club_exists,
        ),
    )


def _club_sponsorships(
    game_db: bytes,
    club_uid: int,
    club_name: str,
    located_run: tuple[int, int],
    layout: SponsorChainLayout,
) -> list[Sponsorship]:
    """One club's sponsor rows, in the order the save stores them."""
    row_struct, index_by_name = _sponsor_row_struct(layout)
    unpack_row = row_struct.unpack_from
    first_row, row_count = located_run
    rows: list[Sponsorship] = []
    for row_offset in range(first_row, first_row + layout.row_bytes * row_count, layout.row_bytes):
        row = unpack_row(game_db, row_offset)
        rows.append(
            Sponsorship(
                club_uid=club_uid,
                club_name=club_name,
                kind=CodedValue.from_raw(SponsorType, row[index_by_name["type"]]),
                start=decode_date(game_db, row_offset + layout.start_offset),
                end=decode_date(game_db, row_offset + layout.end_offset),
                total_value=row[index_by_name["total"]],
                annual_value=row[index_by_name["annual"]],
                unknown=FrozenMapping(
                    {
                        "flag10": row[index_by_name["flag10"]],
                        "u15": row[index_by_name["u15"]],
                        "b17": row[index_by_name["b17"]],
                        "enum18": row[index_by_name["enum18"]],
                        "b19": row[index_by_name["b19"]],
                    }
                ),
            )
        )
    return rows
