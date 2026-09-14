"""Tests that failure reports from corpus tests hide details that could carry save content.

Each case runs a small generated project whose conftest is a copy of the real
tests/conftest.py, with a fictional corpus manifest so corpus tests are not skipped.
Every path is fictional.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tests.conftest as corpus_conftest

pytest_plugins = ["pytester"]

PRIVATE_FOLDER = "privatefolder"
HIDDEN_DETAILS_NOTE = "details hidden to keep save content out of test output"
MARKERS_INI = """
[pytest]
markers =
    corpus: fictional corpus marker
    corpus_fast: fictional corpus tier
    corpus_full: fictional corpus tier
"""
TEARDOWN_FIXTURE_SOURCE = """


@pytest.fixture(scope="session")
def fictional_corpus_resource(request):
    record_corpus_fixture_use(request)
    yield "fictional resource"
    crash_path = "/examples/privatefolder/career/x.fm"
    raise RuntimeError(crash_path)
"""


def real_conftest_source() -> str:
    return Path(corpus_conftest.__file__).read_text(encoding="utf-8")


@pytest.fixture
def corpus_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    pytester.makeconftest(real_conftest_source())
    pytester.makeini(MARKERS_INI)
    corpus_folder = pytester.mkdir("fictional-corpus")
    (corpus_folder / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(corpus_conftest.CORPUS_ENVIRONMENT_VARIABLE, str(corpus_folder))
    return pytester


def run_verbose_with_locals(project: pytest.Pytester) -> tuple[pytest.RunResult, str]:
    run_result = project.runpytest("-vv", "-l")
    return run_result, run_result.stdout.str() + run_result.stderr.str()


def test_unexpected_error_in_corpus_test_is_redacted(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.fixture
        def fictional_save_paths():
            return {"career/x.fm": "/examples/privatefolder/career/x.fm"}

        @pytest.mark.corpus
        def test_reader_crashes(fictional_save_paths):
            crash_path = fictional_save_paths["career/x.fm"]
            raise RuntimeError(crash_path)
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert "test_reader_crashes (call) raised RuntimeError" in output
    assert HIDDEN_DETAILS_NOTE in output
    assert PRIVATE_FOLDER not in output


def test_reported_mismatches_are_not_redacted(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        from tests.corpus.reporting import CorpusMismatches

        @pytest.mark.corpus_fast
        def test_reports_a_mismatch():
            mismatches = CorpusMismatches()
            mismatches.check("a.fm", "build", False)
            mismatches.fail_if_any()
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert "a.fm: build differs" in output
    assert HIDDEN_DETAILS_NOTE not in output


def test_failure_in_non_corpus_test_is_not_redacted(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        def test_plain_crash():
            crash_path = "/examples/privatefolder/career/x.fm"
            raise RuntimeError(crash_path)
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert PRIVATE_FOLDER in output
    assert HIDDEN_DETAILS_NOTE not in output


def test_corpus_fixture_teardown_error_under_later_test_is_redacted(
    corpus_project: pytest.Pytester,
) -> None:
    corpus_project.makeconftest(real_conftest_source() + TEARDOWN_FIXTURE_SOURCE)
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.mark.corpus_full
        def test_first_uses_corpus_resource(fictional_corpus_resource):
            assert fictional_corpus_resource == "fictional resource"

        def test_second_is_plain():
            pass
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(passed=2, errors=1)
    assert "test_second_is_plain (teardown) raised RuntimeError" in output
    assert PRIVATE_FOLDER not in output
