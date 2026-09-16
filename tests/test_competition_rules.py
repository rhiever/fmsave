from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave import Table
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import RulesStats
from fmsave._save import COMPETITION_RULES_TABLE_CACHE_KEY
from fmsave._status import field_status
from fmsave.checks import (
    GateResult,
    check_competition_rules,
    enforce,
    evaluate_competition_rules,
)
from fmsave.export import column_names
from fmsave.models.rules import CompetitionRules, RulesBlockKind, RulesRound
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.rules import build_competition_rules
from tests.fixtures.career import (
    RULES_PLAYOFF_PLACES,
    RULES_PRIZE_MONEY,
    RULES_PROMOTION_BYTE2,
    RULES_PROMOTION_PLACES,
    RULES_RELEGATION_PLACES,
    RULES_ROUND_MATCH_COUNTS,
    RULES_TIE_BREAKS,
)

FILE_NAME = "career example.fm"
MEBIBYTE = 1024 * 1024
FULL_SIZE_SPAN_BYTES = 120 * MEBIBYTE
SMALL_SPAN_BYTES = 1 * MEBIBYTE
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, 4000, "").layout

GATE_NAMES = ("rules_markers_minimum", "rules_fully_parsed")
EXAMPLE_BLOCK_COUNT = 2
# The three rounds the example blocks carry, a week apart from 20 February 2031.
EXAMPLE_ROUND_DATES = (date(2031, 2, 20), date(2031, 2, 27), date(2031, 3, 6))
# Counts from the larger of the two saves measured: 672 blocks, of which 567 parse in the
# strict sense the check counts and 633 carry a doubled promotion quad.
CORPUS_MARKERS = 672
CORPUS_FULLY_PARSED = 567
CORPUS_QUAD_DOUBLED = 633
# 0.80 of 672 is 537.6, so these two counts sit either side of the floor by one block.
JUST_ABOVE_THE_PARSED_FLOOR = 538
JUST_BELOW_THE_PARSED_FLOOR = 537
THREE_QUARTERS_PARSED = 504


def healthy_stats() -> RulesStats:
    """Counts as the larger corpus save reports them, comfortably inside every bound."""
    return RulesStats(
        markers=CORPUS_MARKERS,
        blocks=CORPUS_MARKERS,
        fully_parsed=CORPUS_FULLY_PARSED,
        quad_doubled=CORPUS_QUAD_DOUBLED,
        rows=CORPUS_MARKERS,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def rules_of(career_save: fmsave.Save) -> Table[CompetitionRules]:
    return career_save.competition_rules()


def built_from(career_save: fmsave.Save) -> tuple[tuple[CompetitionRules, ...], RulesStats]:
    """The rows and their counts, built straight from the save's own shared span pass."""
    context = career_save._context  # pyright: ignore[reportPrivateUsage]
    return build_competition_rules(context.span_records())


def test_every_block_becomes_one_preamble_row_in_span_order(career_save_path: Path) -> None:
    """The span holds two blocks, and both are returned in the order the span stores them."""
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)

    assert len(rules) == EXAMPLE_BLOCK_COUNT
    assert [row.kind for row in rules] == [RulesBlockKind.PREAMBLE] * EXAMPLE_BLOCK_COUNT
    assert all(row.kind is RulesBlockKind.PREAMBLE for row in rules)


def test_a_doubled_quad_gives_the_promotion_playoff_and_relegation_places(
    career_save_path: Path,
) -> None:
    with fmsave.open(career_save_path) as career_save:
        first_row = rules_of(career_save)[0]

    assert first_row.promotion_places == RULES_PROMOTION_PLACES
    assert first_row.playoff_places == RULES_PLAYOFF_PLACES
    assert first_row.relegation_places == RULES_RELEGATION_PLACES
    # The quad's third byte has no known meaning, so it ships as a raw number.
    assert first_row.unknown["promotion_byte2"] == RULES_PROMOTION_BYTE2
    # Nothing here has been checked against the game: no block names a competition, so no block
    # can be tied to the one division whose Rules screen these meanings come from.
    assert field_status(CompetitionRules, "promotion_places") == "unconfirmed"
    assert field_status(CompetitionRules, "unknown") == "unconfirmed"


def test_the_prize_list_and_the_matches_per_club_come_from_the_block(
    career_save_path: Path,
) -> None:
    """Matches per club is the number of rounds the block holds, not a stored count."""
    with fmsave.open(career_save_path) as career_save:
        first_row = rules_of(career_save)[0]

    assert first_row.prize_money == RULES_PRIZE_MONEY
    assert first_row.fixtures_per_club == len(EXAMPLE_ROUND_DATES)


def test_each_round_carries_its_number_date_and_match_count(career_save_path: Path) -> None:
    """A round's number counts from one, so the first round of a block reads 1, not 0."""
    with fmsave.open(career_save_path) as career_save:
        rounds = rules_of(career_save)[0].rounds

    assert [round_record.number for round_record in rounds] == [1, 2, 3]
    assert [round_record.date for round_record in rounds] == list(EXAMPLE_ROUND_DATES)
    assert [round_record.match_count for round_record in rounds] == list(RULES_ROUND_MATCH_COUNTS)
    assert rounds[0].unknown["kind"] == 0
    assert rounds[0].unknown["b5"] == 0
    assert field_status(RulesRound, "date") == "unconfirmed"
    assert field_status(RulesRound, "unknown") == "unconfirmed"


def test_the_tie_break_codes_ship_as_raw_numbers_and_stop_where_the_list_does(
    career_save_path: Path,
) -> None:
    """No displayed label names a tie-break code, so each ships as the number the block holds.

    A block lists as many codes as it lists; the keys past the end of that list are absent
    rather than filled with a value the block does not carry.
    """
    with fmsave.open(career_save_path) as career_save:
        first_row = rules_of(career_save)[0]

    assert first_row.unknown["tie_break_00"] == RULES_TIE_BREAKS[0]
    assert first_row.unknown["tie_break_01"] == RULES_TIE_BREAKS[1]
    assert first_row.unknown["tie_break_02"] == RULES_TIE_BREAKS[2]
    assert "tie_break_03" not in first_row.unknown
    assert "tie_break_15" not in first_row.unknown
    assert len(CompetitionRules.UNKNOWN_KEYS) == 17


def test_a_block_whose_quad_is_not_doubled_keeps_its_prizes_and_its_rounds(
    career_save_path: Path,
) -> None:
    """The four quad fields go empty together, and nothing else about the block is lost."""
    with fmsave.open(career_save_path) as career_save:
        second_row = rules_of(career_save)[1]

    assert second_row.promotion_places is None
    assert second_row.playoff_places is None
    assert second_row.relegation_places is None
    assert "promotion_byte2" not in second_row.unknown
    assert second_row.prize_money == RULES_PRIZE_MONEY
    assert [round_record.number for round_record in second_row.rounds] == [1, 2, 3]
    assert second_row.fixtures_per_club == len(EXAMPLE_ROUND_DATES)


def test_no_row_names_a_competition(career_save_path: Path) -> None:
    """The save stores no link from a rules block to a competition, and none is guessed.

    A hunt for one was run over 200 blocks on each of two corpus saves, testing every u32 in
    the 256 bytes before the marker and the 256 bytes after the block's end against the
    competition ids the stage table holds. No offset named a known competition on even 90% of
    blocks while varying from block to block, so every row ships without one.
    """
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)

    assert all(row.competition_id is None for row in rules)
    assert all(row.competition_name is None for row in rules)
    assert field_status(CompetitionRules, "competition_id") == "unconfirmed"


def test_the_club_count_and_the_administration_deduction_are_empty(
    career_save_path: Path,
) -> None:
    """No fixed position in the block carries either on the corpus, so neither is guessed."""
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)

    assert all(row.club_count is None for row in rules)
    assert all(row.administration_points_deduction is None for row in rules)


def test_the_group_kind_is_declared_and_unused(career_save_path: Path) -> None:
    """The tagged rules groups are not read yet, so no row carries the GROUP kind.

    It is declared now so that reading them later adds rows rather than changing what `kind`
    can be.
    """
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)

    assert RulesBlockKind.GROUP.value == "group"
    assert not [row for row in rules if row.kind is RulesBlockKind.GROUP]


def test_the_columns_are_the_field_names_with_the_unknown_map_expanded() -> None:
    assert column_names(CompetitionRules) == (
        "kind",
        "competition_id",
        "competition_name",
        "club_count",
        "fixtures_per_club",
        "promotion_places",
        "playoff_places",
        "relegation_places",
        "administration_points_deduction",
        "prize_money",
        "rounds",
        "unknown_promotion_byte2",
        *(f"unknown_tie_break_{index:02d}" for index in range(16)),
    )
    assert column_names(RulesRound) == (
        "number",
        "date",
        "match_count",
        "unknown_kind",
        "unknown_b5",
    )


def test_records_survive_pickle_and_deepcopy(career_save_path: Path) -> None:
    """The pickled bytes are this test's own records, built moments earlier in this process."""
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)

    for example in (rules[0], rules[0].rounds[0], rules):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_the_table_is_cached_and_closing_stops_it(career_save_path: Path) -> None:
    career_save = fmsave.open(career_save_path)
    rules = career_save.competition_rules()

    assert isinstance(rules, Table)
    assert rules.record_type is CompetitionRules
    assert career_save.competition_rules() is rules
    assert COMPETITION_RULES_TABLE_CACHE_KEY == "table:competition_rules"

    rows_before_close = list(rules)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.competition_rules()
    assert list(rules) == rows_before_close


def test_the_build_counts_exactly_what_the_checks_read(career_save_path: Path) -> None:
    """Every competition-rules gate and anomaly judges these counts, and only the build makes them."""
    with fmsave.open(career_save_path) as career_save:
        rows, stats = built_from(career_save)

    assert len(rows) == EXAMPLE_BLOCK_COUNT
    assert stats == RulesStats(
        markers=EXAMPLE_BLOCK_COUNT,
        blocks=EXAMPLE_BLOCK_COUNT,
        fully_parsed=1,
        quad_doubled=1,
        rows=EXAMPLE_BLOCK_COUNT,
    )
    reader_check = check_competition_rules(stats, BOUNDS, SMALL_SPAN_BYTES)
    assert reader_check.reader == "competition_rules"
    assert reader_check.record_count == EXAMPLE_BLOCK_COUNT
    assert dict(reader_check.anomalies) == {
        "blocks_not_fully_parsed": 1,
        "blocks_without_a_doubled_quad": 1,
    }


def test_healthy_counts_pass_every_gate_and_a_small_span_applies_none() -> None:
    """The corpus counts must pass, so no gate here is rigged to fail whatever it is given."""
    results = evaluate_competition_rules(healthy_stats(), BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert tuple(result.name for result in results) == GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    enforce("competition_rules", results)

    small_results = evaluate_competition_rules(healthy_stats(), BOUNDS, SMALL_SPAN_BYTES)
    assert all(not result.applied and result.passed for result in small_results)


@pytest.mark.parametrize(
    ("stats", "expected_failures"),
    [
        pytest.param(
            dataclasses.replace(healthy_stats(), markers=20),
            [],
            id="exactly-on-the-marker-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), markers=19),
            ["rules_markers_minimum"],
            id="one-marker-below-the-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), fully_parsed=JUST_ABOVE_THE_PARSED_FLOOR),
            [],
            id="one-block-above-the-parsed-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), fully_parsed=JUST_BELOW_THE_PARSED_FLOOR),
            ["rules_fully_parsed"],
            id="one-block-below-the-parsed-floor",
        ),
        pytest.param(
            dataclasses.replace(healthy_stats(), fully_parsed=THREE_QUARTERS_PARSED),
            ["rules_fully_parsed"],
            id="three-quarters-of-blocks-parsed",
        ),
        pytest.param(
            RulesStats(markers=0, blocks=0, fully_parsed=0, quad_doubled=0, rows=0),
            list(GATE_NAMES),
            id="a-span-pass-that-found-nothing",
        ),
    ],
)
def test_the_rules_gates_fail_one_at_a_time(
    stats: RulesStats, expected_failures: Sequence[str]
) -> None:
    """Each way the decode can break fails the gate that watches it, and no other.

    A pass that found nothing fails both rather than reporting a career with no competitions:
    the marker count misses its floor and the parsed share is left with no denominator at all,
    which is exactly what a marker that has moved looks like from the counts.
    """
    results = evaluate_competition_rules(stats, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == list(expected_failures)
    if not expected_failures:
        enforce("competition_rules", results)
        return
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("competition_rules", results)
    message = str(error_info.value)
    assert expected_failures[0] in message
    for fictional_text in ("Alex", "Northbridge", "Example", FILE_NAME):
        assert fictional_text not in message


def test_a_full_size_span_applies_the_gates_and_a_broken_decode_raises(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader really raises: the example span holds two blocks, far below the floor.

    Lowering the span threshold is what makes the gates apply to a fragment, and then the
    fragment's own counts fail them, so this proves the gate reaches the caller rather than
    only the evaluator.
    """
    monkeypatch.setattr(
        fmsave.Save,
        "_gate_bounds",
        lambda career_save: dataclasses.replace(BOUNDS, span_minimum_applies_from_bytes=0),
    )

    with (
        fmsave.open(career_save_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.competition_rules()

    assert "rules_markers_minimum" in str(error_info.value)
