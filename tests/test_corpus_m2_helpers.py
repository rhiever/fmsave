"""The corpus checks' own tests: every bound in them can fail, and fails on the right side.

A check that cannot fail is worse than no check at all, so each of these takes the shape the
corpus check judges, feeds it a sound value and a broken one, and requires the two to be told
apart. The values are invented here; no corpus file is read and none of these tests needs one.
"""

from __future__ import annotations

import datetime

from tests.corpus import test_m2_corpus as corpus_checks


def test_ascending_share_counts_only_the_steps_that_rise() -> None:
    assert corpus_checks.ascending_share([1, 2, 3, 4]) == 1.0
    assert corpus_checks.ascending_share([1, 2, 2, 3]) == 2 / 3
    assert corpus_checks.ascending_share([4, 3, 2, 1]) == 0.0


def test_ascending_share_has_no_value_without_a_step() -> None:
    assert corpus_checks.ascending_share([]) is None
    assert corpus_checks.ascending_share([7]) is None


def test_an_ascending_walk_passes_its_bound_and_a_shuffled_one_fails() -> None:
    ascending_ids = list(range(100))
    shuffled_ids = ascending_ids[:50] + list(reversed(ascending_ids[50:]))
    assert corpus_checks.meets(
        corpus_checks.ascending_share(ascending_ids), corpus_checks.STAGE_ASCENDING_MINIMUM
    )
    assert not corpus_checks.meets(
        corpus_checks.ascending_share(shuffled_ids), corpus_checks.STAGE_ASCENDING_MINIMUM
    )


def test_a_share_that_cannot_be_measured_fails_rather_than_passing() -> None:
    """A reader that returned nothing must not clear a rate check for want of a denominator."""
    assert corpus_checks.share(0, 0) is None
    assert not corpus_checks.meets(corpus_checks.share(0, 0), 0.0)
    assert corpus_checks.meets(corpus_checks.share(9, 10), 0.9)
    assert not corpus_checks.meets(corpus_checks.share(8, 10), 0.9)


def test_sorted_keys_pass_and_one_swapped_pair_fails() -> None:
    first = (datetime.date(2031, 3, 1), datetime.time(15, 0))
    second = (datetime.date(2031, 3, 8), datetime.time(12, 30))
    third = (datetime.date(2031, 3, 8), datetime.time(15, 0))
    assert corpus_checks.is_sorted([first, second, third])
    assert not corpus_checks.is_sorted([first, third, second])


def test_a_row_that_adds_up_passes_and_each_broken_sum_fails() -> None:
    sound = {
        "played": 10,
        "won": 6,
        "drawn": 2,
        "lost": 2,
        "home_played": 5,
        "away_played": 5,
        "first_half_played": 4,
        "second_half_played": 6,
    }
    assert corpus_checks.splits_add_up(**sound)
    assert not corpus_checks.splits_add_up(**{**sound, "won": 7})
    assert not corpus_checks.splits_add_up(**{**sound, "home_played": 4})
    assert not corpus_checks.splits_add_up(**{**sound, "second_half_played": 5})


def test_a_division_shape_is_told_from_a_cup_group() -> None:
    assert corpus_checks.is_double_round_robin(20, 19)
    assert corpus_checks.is_double_round_robin(18, 17)
    # A group of four playing everyone twice is not a division, however well it adds up.
    assert not corpus_checks.is_double_round_robin(4, 3)
    # A division-sized group whose rounds do not match its membership is not one either.
    assert not corpus_checks.is_double_round_robin(20, 9)


def test_years_ahead_separates_this_career_from_a_template_block() -> None:
    clock = datetime.date(2036, 6, 14)
    next_season = datetime.date(2037, 5, 30)
    far_future = datetime.date(2045, 1, 1)
    assert (
        corpus_checks.years_ahead_of(next_season, clock) <= corpus_checks.FIXTURE_YEARS_AHEAD_LIMIT
    )
    assert corpus_checks.years_ahead_of(far_future, clock) > corpus_checks.FIXTURE_YEARS_AHEAD_LIMIT
    # A date before the clock is behind it, never ahead of it.
    assert corpus_checks.years_ahead_of(datetime.date(2030, 1, 1), clock) < 0
