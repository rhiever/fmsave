"""Tests for the corpus collection hook and corpus loading, using fictional files only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

import tests.conftest as corpus_conftest

CORPUS_TIER_MARKERS = ("corpus", "corpus_fast", "corpus_full")
FICTIONAL_SAVE_NAME = "example-career.fm"
PLACEHOLDER_DIGEST = "0" * 64


class StandInItem:
    """Provides the two item methods the collection hook uses."""

    def __init__(self, marker_names: tuple[str, ...]) -> None:
        self.marker_names = marker_names
        self.added_marker_names: list[str] = []

    def get_closest_marker(self, name: str) -> str | None:
        return name if name in self.marker_names else None

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.added_marker_names.append(marker.name)


def write_manifest(corpus_folder: Path, manifest: dict[str, str]) -> None:
    (corpus_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def assert_quiet_failure(failure: pytest.ExceptionInfo[Any], message: str) -> None:
    assert failure.value.msg == message
    assert failure.value.pytrace is False
    assert failure.value.__suppress_context__ or failure.value.__context__ is None


@pytest.mark.parametrize("marker_name", CORPUS_TIER_MARKERS)
def test_collection_hook_skips_every_corpus_tier_without_a_corpus(
    marker_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pytestconfig: pytest.Config,
) -> None:
    monkeypatch.setenv(corpus_conftest.CORPUS_ENVIRONMENT_VARIABLE, str(tmp_path))
    tier_item = StandInItem((marker_name,))
    unmarked_item = StandInItem(())

    corpus_conftest.pytest_collection_modifyitems(
        pytestconfig, cast("list[pytest.Item]", [tier_item, unmarked_item])
    )

    assert tier_item.added_marker_names == ["skip"]
    assert unmarked_item.added_marker_names == []


def test_manifest_paths_are_returned_when_digests_match(tmp_path: Path) -> None:
    save_bytes = b"fictional save bytes"
    (tmp_path / FICTIONAL_SAVE_NAME).write_bytes(save_bytes)
    write_manifest(tmp_path, {FICTIONAL_SAVE_NAME: hashlib.sha256(save_bytes).hexdigest()})

    save_paths = corpus_conftest.verified_corpus_save_paths(tmp_path)

    assert save_paths == {FICTIONAL_SAVE_NAME: tmp_path / FICTIONAL_SAVE_NAME}


def test_empty_manifest_fails(tmp_path: Path) -> None:
    write_manifest(tmp_path, {})

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.verified_corpus_save_paths(tmp_path)

    assert_quiet_failure(failure, "corpus manifest lists no saves")


def test_unreadable_save_fails_with_file_name_only(tmp_path: Path) -> None:
    write_manifest(tmp_path, {f"missing-folder/{FICTIONAL_SAVE_NAME}": PLACEHOLDER_DIGEST})

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.verified_corpus_save_paths(tmp_path)

    assert_quiet_failure(failure, f"corpus file unreadable: {FICTIONAL_SAVE_NAME}")


def test_unreadable_manifest_fails_with_file_name_only(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").mkdir()

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.verified_corpus_save_paths(tmp_path)

    assert_quiet_failure(failure, "corpus file unreadable: manifest.json")


@pytest.mark.parametrize("manifest_text", ["{not json", "[]"])
def test_invalid_manifest_fails_with_file_name_only(tmp_path: Path, manifest_text: str) -> None:
    (tmp_path / "manifest.json").write_text(manifest_text, encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.verified_corpus_save_paths(tmp_path)

    assert_quiet_failure(failure, "corpus file is not a valid JSON object: manifest.json")


def test_missing_golden_values_file_fails(tmp_path: Path) -> None:
    write_manifest(tmp_path, {FICTIONAL_SAVE_NAME: PLACEHOLDER_DIGEST})

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.load_golden_values(tmp_path)

    assert_quiet_failure(failure, "golden values file is missing")


def test_invalid_golden_values_file_fails_with_file_name_only(tmp_path: Path) -> None:
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "values.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.load_golden_values(tmp_path)

    assert_quiet_failure(failure, "corpus file is not a valid JSON object: values.json")


def test_save_that_cannot_open_fails_with_file_name_only(tmp_path: Path) -> None:
    save_path = tmp_path / FICTIONAL_SAVE_NAME
    save_path.write_bytes(b"not a save file")

    with pytest.raises(pytest.fail.Exception) as failure:
        corpus_conftest.open_corpus_saves({FICTIONAL_SAVE_NAME: save_path})

    failure_message = failure.value.msg or ""
    assert failure_message.startswith(f"corpus file could not be opened: {FICTIONAL_SAVE_NAME} (")
    assert str(tmp_path) not in failure_message
    assert failure.value.pytrace is False
    assert failure.value.__suppress_context__
