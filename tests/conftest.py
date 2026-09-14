"""Shared test configuration, including the maintainer's local corpus (never present in CI)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

import fmsave

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ENVIRONMENT_VARIABLE = "FMSAVE_CORPUS"
CORPUS_MARKER_NAMES = ("corpus", "corpus_fast", "corpus_full")
HASH_CHUNK_BYTES = 8 * 1024 * 1024


def corpus_root() -> Path:
    configured_root = os.environ.get(CORPUS_ENVIRONMENT_VARIABLE)
    return Path(configured_root) if configured_root else REPOSITORY_ROOT / ".local" / "corpus"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if (corpus_root() / "manifest.json").is_file():
        return
    skip_marker = pytest.mark.skip(
        reason=f"local corpus not found (set {CORPUS_ENVIRONMENT_VARIABLE})"
    )
    for item in items:
        if any(item.get_closest_marker(marker_name) for marker_name in CORPUS_MARKER_NAMES):
            item.add_marker(skip_marker)


def fail_quietly(message: str) -> NoReturn:
    """Fail with only `message`: no traceback, no function arguments, no chained exception.

    Corpus failures go through here so that paths and save contents never reach the output.
    """
    raise pytest.fail.Exception(message, pytrace=False) from None


def file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        while chunk := file_handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_object(json_path: Path) -> dict[str, Any]:
    try:
        loaded: Any = json.loads(json_path.read_text(encoding="utf-8"))
    except OSError:
        fail_quietly(f"corpus file unreadable: {json_path.name}")
    except ValueError:
        fail_quietly(f"corpus file is not a valid JSON object: {json_path.name}")
    if not isinstance(loaded, dict):
        fail_quietly(f"corpus file is not a valid JSON object: {json_path.name}")
    return loaded


def verified_corpus_save_paths(root: Path) -> dict[str, Path]:
    manifest = load_json_object(root / "manifest.json")
    if not manifest:
        fail_quietly("corpus manifest lists no saves")
    save_paths: dict[str, Path] = {}
    for relative_name, expected_digest in manifest.items():
        save_path = root / relative_name
        try:
            observed_digest = file_sha256(save_path)
        except OSError:
            fail_quietly(f"corpus file unreadable: {save_path.name}")
        if observed_digest != expected_digest:
            fail_quietly(f"corpus file changed since the manifest was written: {save_path.name}")
        save_paths[relative_name] = save_path
    return save_paths


def close_corpus_saves(opened_saves: dict[str, fmsave.Save]) -> None:
    for career_save in opened_saves.values():
        career_save.close()


def open_corpus_saves(save_paths: dict[str, Path]) -> dict[str, fmsave.Save]:
    opened_saves: dict[str, fmsave.Save] = {}
    for relative_name, save_path in save_paths.items():
        try:
            opened_saves[relative_name] = fmsave.open(save_path)
        except (fmsave.FmsaveError, OSError) as open_error:
            close_corpus_saves(opened_saves)
            error_kind = type(open_error).__name__
            fail_quietly(f"corpus file could not be opened: {save_path.name} ({error_kind})")
    return opened_saves


def load_golden_values(root: Path) -> dict[str, Any]:
    golden_path = root / "golden" / "values.json"
    if not golden_path.is_file():
        fail_quietly("golden values file is missing")
    return load_json_object(golden_path)


@pytest.fixture(scope="session")
def corpus_save_paths() -> dict[str, Path]:
    return verified_corpus_save_paths(corpus_root())


@pytest.fixture(scope="session")
def corpus_saves(corpus_save_paths: dict[str, Path]) -> Iterator[dict[str, fmsave.Save]]:
    opened_saves = open_corpus_saves(corpus_save_paths)
    yield opened_saves
    close_corpus_saves(opened_saves)


@pytest.fixture(scope="session")
def golden_values() -> dict[str, Any]:
    return load_golden_values(corpus_root())
