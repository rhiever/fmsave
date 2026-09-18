from __future__ import annotations

import copy
import dataclasses
import pickle
import struct
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
import fmsave._save as save_module
from fmsave import FinanceMonth, Sponsorship, SponsorType, export
from fmsave._layouts import FULL_SAVE_MINIMUM_GAME_DB_BYTES, GateBounds, find_layout
from fmsave._reader_stats import FinanceStats
from fmsave._save import FINANCES_TABLE_CACHE_KEY, SPONSORSHIPS_TABLE_CACHE_KEY
from fmsave.checks import (
    FINANCES_READER,
    SPONSORSHIPS_READER,
    evaluate_finances,
    evaluate_sponsorships,
)
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.clubs import ClubRecordSpan, find_club_layouts, read_club_index
from fmsave.readers.finances import (
    find_finance_layouts,
    locate_finance_chain,
    locate_sponsor_chain,
    month_labels,
    read_club_finances,
)
from tests.fixtures.career import (
    ATHLETIC_UID,
    BUILD_STRING,
    FINANCE_MONTH_VALUES,
    GAME_DB_SCHEMA,
    NORTHBRIDGE_UID,
    SPONSOR_A,
    SPONSOR_C,
    career_finance_rows,
)
from tests.fixtures.finances import (
    club_finance_bytes,
    finance_chain_bytes,
    finance_row_bytes,
    sponsor_chain_bytes,
    sponsor_row_bytes,
)
from tests.fixtures.game_db import club_record_bytes, game_db_body

FILE_NAME = "career example.fm"
CLOCK = date(2031, 3, 1)
BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, BUILD_STRING).layout
LAYOUTS = find_finance_layouts(GAME_DB_SCHEMA, BUILD_STRING)
FULL_SIZE_GAME_DB_BYTES = 100 * 1024 * 1024
FRAGMENT_GAME_DB_BYTES = 1024 * 1024
# Enough zero bytes in front of a chain that the record holding it passes the size filter.
CHAIN_PADDING_BYTES = 1_600
EXAMPLE_CLUB_UID = 4001


def test_finances_lists_every_club_with_a_series_in_club_index_order(
    career_save_path: Path,
) -> None:
    with fmsave.open(career_save_path) as career_save:
        months = tuple(career_save.finances())
    assert [month.club_uid for month in months] == [NORTHBRIDGE_UID] * 3 + [ATHLETIC_UID] * 3
    assert [month.month for month in months[:3]] == [
        date(2030, 12, 1),
        date(2031, 1, 1),
        date(2031, 2, 1),
    ]


def test_a_month_row_carries_the_money_the_save_stores(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        months = tuple(career_save.finances())
    latest = months[2]
    assert latest == FinanceMonth(
        club_uid=NORTHBRIDGE_UID,
        club_name="Northbridge FC",
        month=date(2031, 2, 1),
        balance=950_000,
        transfer_budget_allocated=450_000,
        transfer_budget_remaining=300_000,
        wage_budget_weekly=30_000,
        wage_payroll_weekly=26_000,
        income_excluding_transfers=150_000,
        net_transfers=40_000,
        wage_bill=95_000,
        net=-50_000,
        expenditure_excluding_transfers=160_000,
        total_income=150_000,
        total_expenditure=200_000,
    )
    assert months[1].net_transfers == -30_000


def test_the_finance_stats_count_the_rows_and_their_arithmetic(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        stats = career_finance_stats(career_save)
    assert stats.balance_steps == 4
    assert stats.balance_continuous_steps == 4
    assert stats.net_identity_rows == 6
    assert stats.expenditure_split_rows == 6
    assert stats.rows == 6
    assert stats.clubs_with_series == 2
    assert stats.clubs_with_two_chains == 0
    assert stats.clubs_with_sponsors == 2
    assert stats.sponsor_rows == 3
    assert stats.managed_club_exists is True


def career_finance_stats(career_save: fmsave.Save) -> FinanceStats:
    """What one finance decode over an open save counted."""
    context = career_save._context
    with context.section(GAME_DB_SECTION) as game_db:
        club_index = context.club_index()
        _months, _sponsors, stats = read_club_finances(game_db, club_index, CLOCK, LAYOUTS, True)
    return stats


def test_sponsorships_lists_the_first_run_of_each_club(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        sponsors = tuple(career_save.sponsorships())
    assert [sponsor.club_uid for sponsor in sponsors] == [
        NORTHBRIDGE_UID,
        NORTHBRIDGE_UID,
        ATHLETIC_UID,
    ]
    assert [sponsor.total_value for sponsor in sponsors] == [3_000_000, 400_000, 500_000]


def test_a_sponsor_row_carries_its_dates_values_and_unknown_bytes(
    career_save_path: Path,
) -> None:
    with fmsave.open(career_save_path) as career_save:
        sponsors = tuple(career_save.sponsorships())
    first, second, third = sponsors
    assert first.type.label is SponsorType.UNKNOWN
    assert first.type.raw == SPONSOR_A["sponsor_type"]
    assert first.start == date(2030, 7, 1)
    assert first.end == date(2033, 6, 30)
    assert first.total_value == 3_000_000
    assert first.annual_value == 1_000_000
    assert dict(first.unknown) == {"flag10": 1, "u15": 77, "b17": 0, "enum18": 2, "b19": 5}
    assert second.end == date(2028, 12, 31)
    assert second.annual_value == 0
    assert third.type.raw == SPONSOR_C["sponsor_type"]
    assert third.club_name == "Example Athletic"


def test_month_labels_run_oldest_first_from_the_month_before_the_clock() -> None:
    assert month_labels(date(2031, 3, 1), 3, 1) == (
        date(2030, 12, 1),
        date(2031, 1, 1),
        date(2031, 2, 1),
    )
    assert month_labels(date(2031, 1, 15), 2, 1) == (date(2030, 11, 1), date(2030, 12, 1))


def record_with_chain_bytes(
    chain: bytes, *, padding_bytes: int = CHAIN_PADDING_BYTES, trailer: bytes = b""
) -> tuple[bytes, int]:
    """Zero padding, one chain, then a trailer, and the offset of the chain's first row."""
    return bytes(padding_bytes) + chain + trailer, padding_bytes + struct.calcsize("<I")


def example_span(record: bytes, *, record_end: int | None = None) -> ClubRecordSpan:
    return ClubRecordSpan(
        club_uid=EXAMPLE_CLUB_UID,
        record_start=0,
        record_end=len(record) if record_end is None else record_end,
        team_list_end=None,
    )


def test_a_chain_is_found_only_where_its_count_and_its_rows_check_out() -> None:
    rows = career_finance_rows()
    record, head = record_with_chain_bytes(finance_chain_bytes(rows))
    assert locate_finance_chain(record, example_span(record), LAYOUTS.chains) == (head, 3, 1)

    two_rows, _head = record_with_chain_bytes(finance_chain_bytes(rows[:2]))
    assert locate_finance_chain(two_rows, example_span(two_rows), LAYOUTS.chains) is None

    over_the_weekly_maximum = finance_row_bytes(
        **{**FINANCE_MONTH_VALUES[0], "wage_budget_weekly": 20_000_001}  # pyright: ignore[reportArgumentType]
    )
    broken_rows = (over_the_weekly_maximum, *rows[1:])
    broken, _head = record_with_chain_bytes(finance_chain_bytes(broken_rows))
    assert locate_finance_chain(broken, example_span(broken), LAYOUTS.chains) is None

    truncated_end = len(record) - 1
    assert (
        locate_finance_chain(record, example_span(record, record_end=truncated_end), LAYOUTS.chains)
        is None
    )

    short_record = record[: LAYOUTS.chains.minimum_record_bytes - 1]
    assert locate_finance_chain(short_record, example_span(short_record), LAYOUTS.chains) is None


def test_a_second_chain_is_counted_and_the_first_one_is_used() -> None:
    rows = career_finance_rows()
    chain = finance_chain_bytes(rows)
    record, head = record_with_chain_bytes(chain, trailer=bytes(64) + chain + bytes(64))
    assert locate_finance_chain(record, example_span(record), LAYOUTS.chains) == (head, 3, 2)


def test_a_row_inside_a_chain_never_opens_a_chain_of_its_own() -> None:
    # The four bytes in front of a row are the row before it, so a total expenditure inside the
    # count range makes the rest of the chain look like a chain of its own: five rows each
    # spending four, and the second row is a head whose stored count is the four rows after it.
    # A search resuming one byte past an accepted head would report two chains here.
    rows = tuple(
        finance_row_bytes(**{**FINANCE_MONTH_VALUES[0], "total_expenditure": 4})  # pyright: ignore[reportArgumentType]
        for _row_number in range(5)
    )
    record, head = record_with_chain_bytes(finance_chain_bytes(rows))
    assert locate_finance_chain(record, example_span(record), LAYOUTS.chains) == (head, 5, 1)


def sponsor_run_record(rows: Sequence[bytes]) -> bytes:
    return bytes(8) + sponsor_chain_bytes(rows) + bytes(8)


def test_a_sponsor_run_is_rejected_by_any_row_that_does_not_check_out() -> None:
    sound_row = sponsor_row_bytes(**SPONSOR_A)  # pyright: ignore[reportArgumentType]
    record = sponsor_run_record((sound_row,))
    assert locate_sponsor_chain(record, 0, len(record), LAYOUTS.sponsors) == (9, 1)
    for broken_values in (
        {"flag10": 2},
        {"end": SPONSOR_A["start"]},
        {"annual": 4_000_000},
        {"start": struct.pack("<HH", 1, 1990)},
    ):
        broken = sponsor_run_record(
            (sponsor_row_bytes(**{**SPONSOR_A, **broken_values}),)  # pyright: ignore[reportArgumentType]
        )
        assert locate_sponsor_chain(broken, 0, len(broken), LAYOUTS.sponsors) is None


def one_club_game_db(trailing_bytes: bytes) -> bytes:
    record = club_record_bytes(
        club_index=1,
        uid=EXAMPLE_CLUB_UID,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Northbridge FC",
        short_name="Northbridge",
        team_ids=(70001,),
        trailing_bytes=trailing_bytes,
    )
    return game_db_body([record], [], gap_bytes=256)


def test_a_club_with_no_sponsor_run_still_yields_its_months() -> None:
    game_db = one_club_game_db(
        club_finance_bytes(rows=career_finance_rows(), sponsors=(), facility_byte=17)
    )
    club_index = read_club_index(
        game_db, find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING), FILE_NAME
    )
    months, sponsors, stats = read_club_finances(game_db, club_index, CLOCK, LAYOUTS, True)
    assert len(months) == 3
    assert sponsors == ()
    assert stats.clubs_with_series == 1
    assert stats.clubs_with_sponsors == 0


def test_both_records_export_their_columns() -> None:
    assert export.column_names(FinanceMonth) == (
        "club_uid",
        "club_name",
        "month",
        "balance",
        "transfer_budget_allocated",
        "transfer_budget_remaining",
        "wage_budget_weekly",
        "wage_payroll_weekly",
        "income_excluding_transfers",
        "net_transfers",
        "wage_bill",
        "net",
        "expenditure_excluding_transfers",
        "total_income",
        "total_expenditure",
    )
    assert export.column_names(Sponsorship) == (
        "club_uid",
        "club_name",
        "type",
        "type_code",
        "start",
        "end",
        "total_value",
        "annual_value",
        "unknown_flag10",
        "unknown_u15",
        "unknown_b17",
        "unknown_enum18",
        "unknown_b19",
    )


def test_both_tables_survive_pickle_and_deepcopy(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        months = career_save.finances()
        sponsors = career_save.sponsorships()
    for table in (months, sponsors):
        assert pickle.loads(pickle.dumps(table)) == table
        assert copy.deepcopy(table) == table
    for record in (months[0], sponsors[0]):
        assert pickle.loads(pickle.dumps(record)) == record
        assert copy.deepcopy(record) == record


def test_one_decode_builds_both_tables_and_a_closed_save_raises(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decodes: list[int] = []
    decode_finances = save_module.read_club_finances

    def counting_read_club_finances(*arguments: object, **keyword_arguments: object) -> object:
        decodes.append(1)
        return decode_finances(*arguments, **keyword_arguments)  # pyright: ignore[reportCallIssue, reportArgumentType]

    monkeypatch.setattr(save_module, "read_club_finances", counting_read_club_finances)
    career_save = fmsave.open(career_save_path)
    try:
        assert len(career_save.finances()) == 6
        assert len(career_save.sponsorships()) == 3
        assert len(decodes) == 1
    finally:
        career_save.close()
    for read_table in (career_save.finances, career_save.sponsorships):
        with pytest.raises(fmsave.SaveClosedError):
            read_table()


# A club, row and step population invented here, so that no count in this file comes from a
# real save. The three numbers are each other's arithmetic -- a thousand clubs of ten months
# give ten thousand rows, and one step fewer per club gives nine thousand steps -- and each is
# round, so every share below is an exact count.
CLUBS_WITH_A_SERIES = 1_000
FINANCE_ROWS = 10_000
FINANCE_BALANCE_STEPS = FINANCE_ROWS - CLUBS_WITH_A_SERIES
# The floors these counts are judged against, named here so each case straddles one of them by
# a single row, step or club rather than by a figure written out by hand.
ROW_SHARE_FLOOR = 0.99
BALANCE_CONTINUITY_FLOOR = 0.80
SPONSOR_SHARE_FLOOR = 0.95
# What a sound decode scores: every row holds together, and the balance steps that do not are
# the transfer-window months, which is well clear of their floor.
HEALTHY_BALANCE_CONTINUOUS_SHARE = 0.94


def rows_at_share(share: float) -> int:
    return round(share * FINANCE_ROWS)


def steps_at_share(share: float) -> int:
    return round(share * FINANCE_BALANCE_STEPS)


def clubs_at_share(share: float) -> int:
    return round(share * CLUBS_WITH_A_SERIES)


def passing_finance_stats() -> FinanceStats:
    """An invented save the shape a sound decode gives, inside every bound."""
    return FinanceStats(
        records_searched=FINANCE_ROWS,
        clubs_with_series=CLUBS_WITH_A_SERIES,
        clubs_with_two_chains=0,
        rows=FINANCE_ROWS,
        net_identity_rows=FINANCE_ROWS,
        balance_steps=FINANCE_BALANCE_STEPS,
        balance_continuous_steps=steps_at_share(HEALTHY_BALANCE_CONTINUOUS_SHARE),
        expenditure_split_rows=FINANCE_ROWS,
        clubs_with_sponsors=CLUBS_WITH_A_SERIES,
        sponsor_rows=2 * CLUBS_WITH_A_SERIES,
        managed_club_exists=True,
    )


def failed_gate_names(stats: FinanceStats) -> list[str]:
    gates = evaluate_finances(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES) + evaluate_sponsorships(
        stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    return [gate.name for gate in gates if gate.applied and not gate.passed]


def test_a_sound_finance_shape_passes_every_finance_gate() -> None:
    assert failed_gate_names(passing_finance_stats()) == []


# Each share floor, with the population that meets it exactly and the one a single row, step or
# club short of it. A bound that moved would leave one of these two cases on the wrong side.
SHARE_FLOORS = (
    ("finance_net_identity", "net_identity_rows", rows_at_share(ROW_SHARE_FLOOR)),
    ("finance_expenditure_split", "expenditure_split_rows", rows_at_share(ROW_SHARE_FLOOR)),
    (
        "finance_balance_continuity",
        "balance_continuous_steps",
        steps_at_share(BALANCE_CONTINUITY_FLOOR),
    ),
    ("finance_clubs_with_sponsors", "clubs_with_sponsors", clubs_at_share(SPONSOR_SHARE_FLOOR)),
)


@pytest.mark.parametrize(
    ("gate_name", "field_name", "on_the_floor"),
    SHARE_FLOORS,
    ids=[gate_name for gate_name, _field, _count in SHARE_FLOORS],
)
def test_each_finance_share_passes_on_its_floor_and_fails_one_unit_below_it(
    gate_name: str, field_name: str, on_the_floor: int
) -> None:
    passes = dataclasses.replace(passing_finance_stats(), **{field_name: on_the_floor})
    fails = dataclasses.replace(passing_finance_stats(), **{field_name: on_the_floor - 1})

    assert gate_name not in failed_gate_names(passes)
    assert failed_gate_names(fails) == [gate_name]


@pytest.mark.parametrize(
    ("replacements", "expected_failure"),
    [
        ({"clubs_with_two_chains": 1}, "finance_clubs_with_two_chains"),
        ({"clubs_with_series": 0, "clubs_with_sponsors": 0}, "finance_series_minimum"),
    ],
)
def test_each_finance_count_fails_on_its_own_misalignment(
    replacements: dict[str, int], expected_failure: str
) -> None:
    stats = dataclasses.replace(passing_finance_stats(), **replacements)
    assert expected_failure in failed_gate_names(stats)


# The three shares each shift of the money fields scores in the layout's own record of them:
# read one byte late, four bytes late and one byte early. A share is a property of the format
# rather than a count from any one save, so these are what the floors have to fail whatever
# save they run on. Reading one byte early is the case the balance-continuity floor does
# **not** catch, because a shift of one field leaves the balance steps almost intact; the net
# identity is what catches it, which is why that case expects two failures rather than three.
SHIFTED_SHARES = (
    ("one byte late", 0.003, 0.009, 0.003),
    ("four bytes late", 0.0, 0.55, 0.0),
    ("one byte early", 0.89, 0.51, 0.83),
)
SHIFTED_SHARE_CASES = tuple(
    (
        shift,
        {
            "net_identity_rows": rows_at_share(net_identity_share),
            "expenditure_split_rows": rows_at_share(split_share),
            "balance_continuous_steps": steps_at_share(continuity_share),
        },
        [
            "finance_net_identity",
            *(
                ["finance_balance_continuity"]
                if continuity_share < BALANCE_CONTINUITY_FLOOR
                else []
            ),
            "finance_expenditure_split",
        ],
    )
    for shift, net_identity_share, split_share, continuity_share in SHIFTED_SHARES
)


@pytest.mark.parametrize(
    ("shift", "replacements", "expected_failures"),
    SHIFTED_SHARE_CASES,
    ids=[shift for shift, _replacements, _failures in SHIFTED_SHARE_CASES],
)
def test_a_shifted_field_read_fails_the_shares_it_is_measured_to_break(
    shift: str, replacements: dict[str, int], expected_failures: list[str]
) -> None:
    stats = dataclasses.replace(passing_finance_stats(), **replacements)
    assert failed_gate_names(stats) == expected_failures


def no_series_stats(*, managed_club_exists: bool) -> FinanceStats:
    """What a save whose clubs keep no finance series at all counts."""
    return FinanceStats(
        records_searched=FINANCE_ROWS,
        clubs_with_series=0,
        clubs_with_two_chains=0,
        rows=0,
        net_identity_rows=0,
        balance_steps=0,
        balance_continuous_steps=0,
        expenditure_split_rows=0,
        clubs_with_sponsors=0,
        sponsor_rows=0,
        managed_club_exists=managed_club_exists,
    )


def test_no_series_on_a_managed_save_fails_the_series_floor_alone() -> None:
    stats = no_series_stats(managed_club_exists=True)
    assert failed_gate_names(stats) == ["finance_series_minimum"]
    applied_gates = [
        gate.name
        for gate in evaluate_finances(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
        + evaluate_sponsorships(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
        if gate.applied
    ]
    # The three shares and the sponsor share have no denominator, so only the two counts apply.
    assert applied_gates == ["finance_clubs_with_two_chains", "finance_series_minimum"]


def test_no_series_and_no_managed_club_fails_nothing() -> None:
    stats = no_series_stats(managed_club_exists=False)
    gates = evaluate_finances(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES) + evaluate_sponsorships(
        stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES
    )
    assert failed_gate_names(stats) == []
    # The one count that still applies is the ceiling on second chains, which no club can break
    # when no club has a chain at all: this is the hole the reader's docstring names.
    assert [gate.name for gate in gates if gate.applied] == ["finance_clubs_with_two_chains"]


def test_no_finance_gate_applies_to_a_fragment() -> None:
    stats = dataclasses.replace(passing_finance_stats(), clubs_with_series=0, rows=0)
    gates = evaluate_finances(stats, BOUNDS, FRAGMENT_GAME_DB_BYTES) + evaluate_sponsorships(
        stats, BOUNDS, FRAGMENT_GAME_DB_BYTES
    )
    assert gates
    assert not any(gate.applied for gate in gates)
    assert BOUNDS.minimum_applies_from_bytes == FULL_SAVE_MINIMUM_GAME_DB_BYTES


def test_a_failed_finance_check_stops_both_tables(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fmsave import checks

    def failing_evaluate_finances(
        stats: FinanceStats, bounds: GateBounds, game_db_bytes: int
    ) -> tuple[fmsave.GateResult, ...]:
        return (
            fmsave.GateResult("finance_net_identity", 0.0, 0.99, None, passed=False, applied=True),
        )

    monkeypatch.setattr(checks, "evaluate_finances", failing_evaluate_finances)
    with fmsave.open(career_save_path) as career_save:
        for read_table in (career_save.finances, career_save.sponsorships):
            with pytest.raises(fmsave.ReaderCheckError, match="^finances failed checks: "):
                read_table()
            for cache_key in (FINANCES_TABLE_CACHE_KEY, SPONSORSHIPS_TABLE_CACHE_KEY):
                assert cache_key not in career_save._context._cache


def test_the_sponsorship_check_names_its_own_reader(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        career_save.sponsorships()
        finance_check = career_save._reader_check(FINANCES_READER)
        sponsorship_check = career_save._reader_check(SPONSORSHIPS_READER)
    assert finance_check is not None
    assert sponsorship_check is not None
    assert finance_check.record_count == 6
    assert sponsorship_check.record_count == 3
    assert dict(sponsorship_check.anomalies) == {"clubs_without_sponsors": 0}
    assert dict(finance_check.anomalies) == {"clubs_with_series": 2, "balance_breaks": 0}


def test_athletic_keeps_its_first_sponsor_run_only(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        sponsors = [
            sponsor for sponsor in career_save.sponsorships() if sponsor.club_uid == ATHLETIC_UID
        ]
    assert len(sponsors) == 1
    assert sponsors[0].annual_value == 250_000


def test_a_club_without_finance_bytes_yields_no_rows_and_is_not_an_error() -> None:
    game_db = one_club_game_db(b"")
    club_index = read_club_index(
        game_db, find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING), FILE_NAME
    )
    months, sponsors, stats = read_club_finances(game_db, club_index, CLOCK, LAYOUTS, False)
    assert months == ()
    assert sponsors == ()
    assert stats.clubs_with_series == 0
    assert stats.managed_club_exists is False
    # Those counts would not fail a check on a full-size save either: a save whose clubs keep
    # no series is a save with nothing to judge.
    assert failed_gate_names(stats) == []
