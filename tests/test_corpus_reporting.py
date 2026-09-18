"""Tests for the corpus mismatch reporter, using fictional labels and values only."""

from __future__ import annotations

import pytest

from tests.corpus.reporting import CorpusMismatches


def test_fail_if_any_joins_every_recorded_message() -> None:
    mismatches = CorpusMismatches()
    mismatches.check("a.fm", "build", False)
    mismatches.check("a.fm", "game", True)
    mismatches.note("b.fm: no recorded values")

    with pytest.raises(pytest.fail.Exception) as failure:
        mismatches.fail_if_any()

    assert failure.value.msg == "a.fm: build differs; b.fm: no recorded values"
    assert failure.value.pytrace is False


def test_fail_if_any_passes_when_nothing_is_recorded() -> None:
    mismatches = CorpusMismatches()
    mismatches.check("a.fm", "build", True)

    mismatches.fail_if_any()


def test_failure_message_never_contains_compared_values() -> None:
    observed_build = "26.1.0"
    expected_build = "26.9.9"
    mismatches = CorpusMismatches()
    mismatches.check("a.fm", "build", observed_build == expected_build)

    with pytest.raises(pytest.fail.Exception) as failure:
        mismatches.fail_if_any()

    failure_message = failure.value.msg or ""
    assert failure_message == "a.fm: build differs"
    assert observed_build not in failure_message
    assert expected_build not in failure_message
