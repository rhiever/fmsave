from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave import Table, checks
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
from fmsave.readers import rules as rules_reader
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.rules import build_competition_rules
from tests.fixtures.career import (
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    FIXTURE_STAGE_ID,
    NORTHBRIDGE_TEAM_A,
    RULES_PLAYOFF_PLACES,
    RULES_PRIZE_MONEY,
    RULES_PROMOTION_BYTE2,
    RULES_PROMOTION_PLACES,
    RULES_RELEGATION_PLACES,
    RULES_ROUND_MATCH_COUNTS,
    RULES_TIE_BREAKS,
    SOUTHPORT_TEAM,
    TABLE_VOTE_FIXTURES,
    ExampleResult,
    career_fragment,
    twin_table_blocks,
)

FILE_NAME = "career example.fm"
MEBIBYTE = 1024 * 1024
FULL_SIZE_SPAN_BYTES = 120 * MEBIBYTE
SMALL_SPAN_BYTES = 1 * MEBIBYTE
BOUNDS: GateBounds = find_layout(GateBounds, GAME_DB_SECTION, 4000, "").layout

GATE_NAMES = (
    "rules_markers_minimum",
    "rules_fully_parsed",
    "rules_linked_blocks_minimum",
    "rules_link_round_dates",
)
# An empty decode leaves the two link checks without the populations they judge: the round-date
# share has no denominator, and the linked-block count applies only above a run population an
# empty span does not reach. The two marker checks are what fail on an empty span.
GATE_NAMES_AN_EMPTY_DECODE_FAILS = GATE_NAMES[:2]
EXAMPLE_BLOCK_COUNT = 2
# The three rounds the example blocks carry, a week apart from 20 February 2031.
EXAMPLE_ROUND_DATES = (date(2031, 2, 20), date(2031, 2, 27), date(2031, 3, 6))
# Counts from the largest save measured: 672 blocks, of which 567 parse in the
# strict sense the check counts and 633 carry a doubled promotion quad.
CORPUS_MARKERS = 672
CORPUS_FULLY_PARSED = 567
CORPUS_QUAD_DOUBLED = 633
# 0.80 of 672 is 537.6, so these two counts sit either side of the floor by one block.
JUST_ABOVE_THE_PARSED_FLOOR = 538
JUST_BELOW_THE_PARSED_FLOOR = 537
THREE_QUARTERS_PARSED = 504
# The same save's positional link: 471 blocks are followed by a run of table blocks, 419 of
# those runs are exactly one table's set of clubs and 418 of those tables carry a voted
# competition. Of the 4,910 dated rounds those blocks hold, 3,678 fall on a date the
# competition plays a fixture on; taking the run before each block instead leaves 0.58.
CORPUS_BLOCKS_WITH_RUN = 471
CORPUS_BLOCKS_LINKED = 419
CORPUS_BLOCKS_LINKED_WITH_COMPETITION = 418
CORPUS_LINKED_ROUNDS = 4_910
CORPUS_LINKED_ROUNDS_IN_CALENDAR = 3_678
CORPUS_LINKED_ROUND_SHAPE = 312
# 0.65 of 4,910 is 3,191.5, so these two counts sit either side of the floor by one round, and
# the misaligned share of 0.58 is 2,848 rounds.
JUST_ABOVE_THE_ROUND_DATE_FLOOR = 3_192
JUST_BELOW_THE_ROUND_DATE_FLOOR = 3_191
MISALIGNED_ROUNDS_IN_CALENDAR = 2_848
# The linked-block floor is 90 and applies from 200 blocks with a run.
JUST_ABOVE_THE_LINKED_BLOCK_FLOOR = 90
JUST_BELOW_THE_LINKED_BLOCK_FLOOR = 89
RUNS_BELOW_THE_LINK_THRESHOLD = 199
# Scores for the two league matches the example calendar holds between the same two clubs, so
# a save written with them gives the result checks a population to judge.
EXAMPLE_SCORES = (
    ExampleResult(FIXTURE_STAGE_ID, NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM, 51, 3, 1),
    ExampleResult(FIXTURE_STAGE_ID, SOUTHPORT_TEAM, NORTHBRIDGE_TEAM_A, 58, 1, 2),
)


def healthy_stats() -> RulesStats:
    """Counts as the larger corpus save reports them, comfortably inside every bound."""
    return RulesStats(
        markers=CORPUS_MARKERS,
        blocks=CORPUS_MARKERS,
        fully_parsed=CORPUS_FULLY_PARSED,
        quad_doubled=CORPUS_QUAD_DOUBLED,
        rows=CORPUS_MARKERS,
        blocks_with_run=CORPUS_BLOCKS_WITH_RUN,
        blocks_linked=CORPUS_BLOCKS_LINKED,
        blocks_linked_with_competition=CORPUS_BLOCKS_LINKED_WITH_COMPETITION,
        linked_rounds=CORPUS_LINKED_ROUNDS,
        linked_rounds_in_calendar=CORPUS_LINKED_ROUNDS_IN_CALENDAR,
        linked_round_shape=CORPUS_LINKED_ROUND_SHAPE,
    )


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def gate_named(results: tuple[GateResult, ...], name: str) -> GateResult:
    return next(result for result in results if result.name == name)


def rules_of(career_save: fmsave.Save) -> Table[CompetitionRules]:
    return career_save.competition_rules()


def built_from(career_save: fmsave.Save) -> tuple[tuple[CompetitionRules, ...], RulesStats]:
    """The rows and their counts, built straight from the save's own shared readers."""
    context = career_save._context  # pyright: ignore[reportPrivateUsage]
    return build_competition_rules(
        context.span_records(),
        career_save.league_tables(),
        career_save.fixtures(),
        context.competition_index(),
    )


def write_interleaved_career(
    tmp_path: Path, *, extra_table_groups: Sequence[Sequence[bytes]] = ()
) -> Path:
    """A career laid out as a save is: each of the two rules blocks in front of its table."""
    return career_fragment(
        extra_fixtures=TABLE_VOTE_FIXTURES,
        interleave_rules=True,
        extra_table_groups=extra_table_groups,
    ).write(tmp_path / "Private Folder" / FILE_NAME)


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
    # Nothing here has been read back off a screen. The positional link does reach the one
    # division whose Rules screen these meanings come from, and that block's values match it,
    # but matching a screen's shape is corroboration rather than a field read back.
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


def test_a_block_with_no_table_run_after_it_names_no_competition(career_save_path: Path) -> None:
    """A block the save does not follow with a table has nothing to take a competition from.

    The competition is not a stored field: it comes from the run of table blocks stored right
    after the block. This fragment holds both preambles after every table, so neither has a
    run, and neither is given a competition rather than being given the nearest one.
    """
    with fmsave.open(career_save_path) as career_save:
        rules = rules_of(career_save)
        _rows, stats = built_from(career_save)

    assert all(row.competition_id is None for row in rules)
    assert all(row.competition_name is None for row in rules)
    assert stats.blocks_with_run == 0
    assert stats.blocks_linked == 0
    assert field_status(CompetitionRules, "competition_id") == "unconfirmed"


def test_the_run_of_tables_after_a_block_gives_it_its_competition(tmp_path: Path) -> None:
    """One table's worth of blocks follows each preamble, which is how a save lays them out.

    The first run is the three-club table the calendar votes a competition onto, so the first
    row carries that competition. The second run is the reserve table, which the vote leaves
    unnamed: the link resolves and still hands over nothing, which is what an unconfirmed vote
    passed through a second reader looks like.
    """
    career_path = write_interleaved_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        rules = rules_of(career_save)
        _rows, stats = built_from(career_save)

    assert rules[0].competition_id == FIRST_COMPETITION_ID
    assert rules[1].competition_id is None
    assert stats.blocks_with_run == EXAMPLE_BLOCK_COUNT
    assert stats.blocks_linked == EXAMPLE_BLOCK_COUNT
    assert stats.blocks_linked_with_competition == 1


def test_a_linked_round_falls_on_a_date_the_competition_plays(tmp_path: Path) -> None:
    """The corroboration that says the link is the right way round.

    Two of the block's three rounds fall on days the linked competition holds a fixture on;
    the third falls on a cup date, which belongs to another competition. On the corpus this
    share is 0.74 to 0.78 for the run after the block and 0.55 to 0.58 for the run before it,
    which is why it is a gate and the round-count shape is only a count.
    """
    career_path = write_interleaved_career(tmp_path)

    with fmsave.open(career_path) as career_save:
        _rows, stats = built_from(career_save)

    assert stats.linked_rounds == len(EXAMPLE_ROUND_DATES)
    assert stats.linked_rounds_in_calendar == 2
    # Three rounds for a three-club table is neither three clubs playing each other twice
    # (four) nor once (two), so the shape does not hold and is reported as the count it is.
    assert stats.linked_round_shape == 0


def test_a_competition_name_reaches_a_linked_row_through_the_supplied_map(
    tmp_path: Path,
) -> None:
    """No save stores a competition name, so a name arrives through the database id or not at all."""
    career_path = write_interleaved_career(tmp_path)

    with fmsave.open(career_path) as unnamed_save:
        without_map = [row.competition_name for row in rules_of(unnamed_save)]
    with fmsave.open(
        career_path, competition_names={FIRST_COMPETITION_DATABASE_ID: "Example League"}
    ) as named_save:
        with_map = [row.competition_name for row in rules_of(named_save)]

    assert without_map == [None, None]
    assert with_map == ["Example League", None]


def test_a_run_matching_two_tables_links_to_neither(tmp_path: Path) -> None:
    """The link demands exactly one table, because two tables of one set name nothing.

    A second table of the same three clubs makes the first run ambiguous, and the second run
    then swallows both the reserve table and that second table, so its set matches no table at
    all. Neither block is linked and neither is given a competition.
    """
    career_path = write_interleaved_career(tmp_path, extra_table_groups=(twin_table_blocks(),))

    with fmsave.open(career_path) as career_save:
        rules = rules_of(career_save)
        _rows, stats = built_from(career_save)

    assert stats.blocks_with_run == EXAMPLE_BLOCK_COUNT
    assert stats.blocks_linked == 0
    assert stats.blocks_linked_with_competition == 0
    assert all(row.competition_id is None for row in rules)


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


def test_no_docstring_still_says_a_row_never_names_a_competition() -> None:
    """A row can now carry a competition, so the sentences that denied it must be gone.

    Pinning the withdrawn wording is what stops a docstring surviving the behaviour it
    described: the three places that said so are the reader module, the reader method and the
    record itself.
    """
    withdrawn = (
        "competition_id is None on every row",
        "None on every row in this release",
        "no rules block names a competition",
        "No block names a competition",
    )
    documentation = "\n".join(
        text or ""
        for text in (
            rules_reader.__doc__,
            fmsave.Save.competition_rules.__doc__,
            CompetitionRules.__doc__,
            RulesBlockKind.__doc__,
        )
    )

    for sentence in withdrawn:
        assert sentence not in documentation, sentence


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
        blocks_with_run=0,
        blocks_linked=0,
        blocks_linked_with_competition=0,
        linked_rounds=0,
        linked_rounds_in_calendar=0,
        linked_round_shape=0,
    )
    reader_check = check_competition_rules(stats, BOUNDS, SMALL_SPAN_BYTES)
    assert reader_check.reader == "competition_rules"
    assert reader_check.record_count == EXAMPLE_BLOCK_COUNT
    assert dict(reader_check.anomalies) == {
        "blocks_not_fully_parsed": 1,
        "blocks_without_a_doubled_quad": 1,
        "blocks_without_a_run": EXAMPLE_BLOCK_COUNT,
        "blocks_with_an_ambiguous_run": 0,
        "linked_blocks_without_a_competition": 0,
        "linked_round_shape": 0,
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
            dataclasses.replace(
                healthy_stats(), linked_rounds_in_calendar=JUST_ABOVE_THE_ROUND_DATE_FLOOR
            ),
            [],
            id="one-round-above-the-round-date-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), linked_rounds_in_calendar=JUST_BELOW_THE_ROUND_DATE_FLOOR
            ),
            ["rules_link_round_dates"],
            id="one-round-below-the-round-date-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), linked_rounds_in_calendar=MISALIGNED_ROUNDS_IN_CALENDAR
            ),
            ["rules_link_round_dates"],
            id="the-run-before-the-block-instead-of-the-run-after-it",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), blocks_linked_with_competition=JUST_ABOVE_THE_LINKED_BLOCK_FLOOR
            ),
            [],
            id="exactly-on-the-linked-block-floor",
        ),
        pytest.param(
            dataclasses.replace(
                healthy_stats(), blocks_linked_with_competition=JUST_BELOW_THE_LINKED_BLOCK_FLOOR
            ),
            ["rules_linked_blocks_minimum"],
            id="one-block-below-the-linked-block-floor",
        ),
        pytest.param(
            RulesStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            list(GATE_NAMES_AN_EMPTY_DECODE_FAILS),
            id="a-span-pass-that-found-nothing",
        ),
    ],
)
def test_the_rules_gates_fail_one_at_a_time(
    stats: RulesStats, expected_failures: Sequence[str]
) -> None:
    """Each way the decode can break fails the gate that watches it, and no other.

    A pass that found nothing fails the marker count on its floor and leaves the parsed share
    without a denominator, which fails too; that is what a marker that has moved looks like
    from the counts. The round-date share is the one check with no population of its own to
    fall back on, so an empty link is reported rather than failed, and the league-table checks
    this reader now runs are what fail when the tables the link needs are not there.
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader really raises: the example span holds two blocks, far below the floor.

    Lowering the span threshold is what makes the gates apply to a fragment, and then the
    fragment's own counts fail them, so this proves the gate reaches the caller rather than
    only the evaluator. This reader now builds the league tables and the calendar, whose own
    gates judge the same span and would raise first on a fragment this size, so their floors
    are relaxed to what a fragment can meet and the save is written with the two score records
    the result checks need a population from. Every bound this reader is judged by is left
    exactly as registered.
    """
    monkeypatch.setattr(
        fmsave.Save,
        "_gate_bounds",
        lambda career_save: dataclasses.replace(
            BOUNDS,
            span_minimum_applies_from_bytes=0,
            fixtures_minimum=(1, None),
            fixture_cluster_share=(0.5, None),
            fixture_strays_minimum=(1, None),
            fixture_stage_resolved=(0.5, None),
            result_records_minimum=(1, None),
            results_joined=(0.5, None),
            table_blocks_minimum=(1, None),
            table_block_duplicates_minimum=(0, None),
            table_groups_resolved=(0.0, None),
            double_round_robin_divisions=(0, None),
        ),
    )
    career_path = career_fragment(span_results=EXAMPLE_SCORES).write(
        tmp_path / "Private Folder" / FILE_NAME
    )

    with (
        fmsave.open(career_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.competition_rules()

    assert "rules_markers_minimum" in str(error_info.value)


def test_a_link_that_stops_linking_fails_the_count_no_share_could_catch() -> None:
    """The count floor is the only check a link that quietly stops linking falls on.

    Every share of this link is invariant under its own misalignment, because taking the run
    before each block instead of the run after it permutes the same runs among the same blocks;
    the share of blocks that link is 0.55 to 0.68 whichever run is taken. So a link that
    returns nothing leaves the round-date share without a denominator, which an empty
    population has reported as not applied rather than failed, and the count is what says the
    link has gone.
    """
    stopped_linking = dataclasses.replace(
        healthy_stats(),
        blocks_linked=0,
        blocks_linked_with_competition=0,
        linked_rounds=0,
        linked_rounds_in_calendar=0,
        linked_round_shape=0,
    )

    results = evaluate_competition_rules(stopped_linking, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert failed_gate_names(results) == ["rules_linked_blocks_minimum"]
    assert not gate_named(results, "rules_link_round_dates").applied
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        enforce("competition_rules", results)
    assert "rules_linked_blocks_minimum" in str(error_info.value)


def test_a_save_with_too_few_runs_to_judge_is_not_held_to_the_count() -> None:
    """The count is measured on saves holding many divisions, so it applies only above a run
    population those saves clear by a wide margin.

    A save with fewer runs than that legitimately links fewer blocks, and the round-date share
    still judges the alignment of the ones it does link.
    """
    few_runs = dataclasses.replace(
        healthy_stats(),
        blocks_with_run=RUNS_BELOW_THE_LINK_THRESHOLD,
        blocks_linked=0,
        blocks_linked_with_competition=0,
    )

    results = evaluate_competition_rules(few_runs, BOUNDS, FULL_SIZE_SPAN_BYTES)

    assert not gate_named(results, "rules_linked_blocks_minimum").applied
    assert failed_gate_names(results) == []
    enforce("competition_rules", results)


def test_a_failed_league_table_check_stops_the_rules_being_built(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The link may only read tables whose own checks passed.

    A table decode that had shattered, or run two tables together, would otherwise hand this
    reader team sets that match nothing and leave every row unlinked without raising at all.
    """

    def failing_league_table_gates(
        stats: object, bounds: GateBounds, span_bytes: int
    ) -> tuple[GateResult, ...]:
        return (GateResult("a_failed_gate", 0.5, 0.9, None, False, True),)

    monkeypatch.setattr(checks, "evaluate_league_tables", failing_league_table_gates)

    with (
        fmsave.open(career_save_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.competition_rules()

    assert str(error_info.value).startswith("league_tables failed checks: ")
