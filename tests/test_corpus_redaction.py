"""Tests that failure reports from corpus tests hide details that could carry save content.

Each case runs a small generated project whose conftest is a copy of the real
tests/conftest.py, with a fictional corpus manifest so corpus tests are not skipped.
Every path is fictional.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import tests.conftest as corpus_conftest

pytest_plugins = ["pytester"]

PRIVATE_FOLDER = "privatefolder"
HIDDEN_DETAILS_NOTE = "details hidden to keep save content out of test output"
FICTIONAL_CORPUS_FOLDER = "fictional-corpus"
REAL_CORPUS_FIXTURES = ("corpus_save_paths", "corpus_saves", "golden_values")
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
FLAG_PROBE_FIXTURE_SOURCE = """


@pytest.fixture
def corpus_fixture_use_recorded(request):
    return request.session.stash.get(CORPUS_FIXTURES_USED, False)
"""
STAND_IN_SAVE_PATHS_SOURCE = """

@pytest.fixture(scope="session")
def corpus_save_paths():
    return {}
"""


def real_conftest_source() -> str:
    return Path(corpus_conftest.__file__).read_text(encoding="utf-8")


@pytest.fixture
def corpus_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    pytester.makeconftest(real_conftest_source())
    pytester.makeini(MARKERS_INI)
    corpus_folder = pytester.mkdir(FICTIONAL_CORPUS_FOLDER)
    (corpus_folder / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(corpus_conftest.CORPUS_ENVIRONMENT_VARIABLE, str(corpus_folder))
    return pytester


def run_verbose_with_locals(
    project: pytest.Pytester, *extra_arguments: str
) -> tuple[pytest.RunResult, str]:
    run_result = project.runpytest("-vv", "-l", *extra_arguments)
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


def test_mismatch_failure_inside_except_hides_the_chained_error(
    corpus_project: pytest.Pytester,
) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        from tests.corpus.reporting import CorpusMismatches

        @pytest.mark.corpus
        def test_reports_after_an_os_error():
            mismatches = CorpusMismatches()
            try:
                raise OSError("/examples/privatefolder/career/x.fm")
            except OSError:
                mismatches.note("x.fm: unreadable")
                mismatches.fail_if_any()
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert "x.fm: unreadable" in output
    assert PRIVATE_FOLDER not in output


def test_quiet_failure_with_visible_chained_error_is_redacted(
    corpus_project: pytest.Pytester,
) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.mark.corpus
        def test_fails_quietly_inside_except():
            try:
                raise OSError("/examples/privatefolder/career/x.fm")
            except OSError:
                pytest.fail("safe", pytrace=False)
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert "test_fails_quietly_inside_except (call) raised Failed" in output
    assert PRIVATE_FOLDER not in output


def test_quiet_failure_under_full_trace_is_redacted(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.mark.corpus
        def test_fails_quietly_beside_a_private_local():
            crash_path = "/examples/privatefolder/career/x.fm"
            pytest.fail("x.fm: unreadable", pytrace=False)
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project, "--full-trace")

    run_result.assert_outcomes(failed=1)
    assert "test_fails_quietly_beside_a_private_local (call) raised Failed" in output
    assert PRIVATE_FOLDER not in output


def test_unmarked_test_using_a_corpus_fixture_is_redacted(
    corpus_project: pytest.Pytester,
) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.fixture
        def corpus_saves():
            return {"career/x.fm": "/examples/privatefolder/career/x.fm"}

        def test_reads_a_stand_in_save(corpus_saves):
            raise RuntimeError(corpus_saves["career/x.fm"])
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(failed=1)
    assert "test_reads_a_stand_in_save (call) raised RuntimeError" in output
    assert PRIVATE_FOLDER not in output


def test_redacted_report_drops_captured_output_and_logs(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import logging
        import sys

        import pytest

        @pytest.mark.corpus
        def test_prints_then_crashes():
            print("/examples/privatefolder/career/printed.fm")
            print("/examples/privatefolder/career/stderr.fm", file=sys.stderr)
            logging.getLogger("fictional").warning("/examples/privatefolder/career/logged.fm")
            raise RuntimeError("crash")
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project, "-rA")

    run_result.assert_outcomes(failed=1)
    assert "test_prints_then_crashes (call) raised RuntimeError" in output
    assert PRIVATE_FOLDER not in output


def test_plain_teardown_error_without_corpus_fixtures_is_not_redacted(
    corpus_project: pytest.Pytester,
) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.fixture
        def plain_resource():
            yield "resource"
            crash_path = "/examples/privatefolder/career/x.fm"
            raise RuntimeError(crash_path)

        def test_uses_plain_resource(plain_resource):
            pass
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(passed=1, errors=1)
    assert PRIVATE_FOLDER in output
    assert HIDDEN_DETAILS_NOTE not in output


def test_setup_error_in_corpus_test_is_redacted(corpus_project: pytest.Pytester) -> None:
    corpus_project.makepyfile(
        test_generated="""
        import pytest

        @pytest.fixture
        def crashing_resource():
            crash_path = "/examples/privatefolder/career/x.fm"
            raise RuntimeError(crash_path)

        @pytest.mark.corpus
        def test_needs_crashing_resource(crashing_resource):
            pass
        """
    )

    run_result, output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(errors=1)
    assert "test_needs_crashing_resource (setup) raised RuntimeError" in output
    assert PRIVATE_FOLDER not in output


@pytest.mark.parametrize("fixture_name", REAL_CORPUS_FIXTURES)
def test_each_real_corpus_fixture_records_its_use(
    corpus_project: pytest.Pytester, fixture_name: str
) -> None:
    corpus_folder = corpus_project.path / FICTIONAL_CORPUS_FOLDER
    save_bytes = b"fictional save bytes"
    (corpus_folder / "career").mkdir()
    (corpus_folder / "career" / "example-career.fm").write_bytes(save_bytes)
    manifest = {"career/example-career.fm": hashlib.sha256(save_bytes).hexdigest()}
    (corpus_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (corpus_folder / "golden").mkdir()
    (corpus_folder / "golden" / "values.json").write_text("{}", encoding="utf-8")
    corpus_project.makeconftest(real_conftest_source() + FLAG_PROBE_FIXTURE_SOURCE)
    # corpus_saves alone must record its use, so its path fixture becomes a silent stand-in.
    stand_in_source = STAND_IN_SAVE_PATHS_SOURCE if fixture_name == "corpus_saves" else ""
    corpus_project.makepyfile(
        test_generated=f"""
import pytest
{stand_in_source}

def test_first_requests_the_fixture({fixture_name}):
    pass


def test_second_reads_the_flag(corpus_fixture_use_recorded):
    assert corpus_fixture_use_recorded is True
"""
    )

    run_result, _output = run_verbose_with_locals(corpus_project)

    run_result.assert_outcomes(passed=2)
