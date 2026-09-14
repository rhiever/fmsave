"""Shared test configuration, including the maintainer's local corpus (never present in CI)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import fmsave

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ENVIRONMENT_VARIABLE = "FMSAVE_CORPUS"
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
        if item.get_closest_marker("corpus") is not None:
            item.add_marker(skip_marker)


def file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        while chunk := file_handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="session")
def corpus_save_paths() -> dict[str, Path]:
    root = corpus_root()
    manifest: dict[str, str] = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    save_paths: dict[str, Path] = {}
    for relative_name, expected_digest in manifest.items():
        save_path = root / relative_name
        if file_sha256(save_path) != expected_digest:
            pytest.fail(f"corpus file changed since the manifest was written: {save_path.name}")
        save_paths[relative_name] = save_path
    return save_paths


@pytest.fixture(scope="session")
def corpus_saves(corpus_save_paths: dict[str, Path]) -> Iterator[dict[str, fmsave.Save]]:
    opened_saves = {
        relative_name: fmsave.open(save_path)
        for relative_name, save_path in corpus_save_paths.items()
    }
    yield opened_saves
    for career_save in opened_saves.values():
        career_save.close()


@pytest.fixture(scope="session")
def golden_values() -> dict[str, Any]:
    golden_path = corpus_root() / "golden" / "values.json"
    if not golden_path.is_file():
        pytest.skip("golden values have not been recorded")
    loaded: dict[str, Any] = json.loads(golden_path.read_text(encoding="utf-8"))
    return loaded
