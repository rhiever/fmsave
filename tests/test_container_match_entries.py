from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from fmsave._container import match_file_entries, read_directory_entry, read_index
from fmsave._errors import CorruptSaveError, SaveChangedError
from tests.fixtures.career import CAREER_ATTACHMENTS, career_fragment

SHORT_BY_ONE_BYTE = 1


@pytest.fixture
def career_path(tmp_path: Path) -> Path:
    return career_fragment().write(tmp_path / "career.bin")


def test_match_file_entries_are_the_per_match_entries_in_directory_order(
    career_path: Path,
) -> None:
    container_index = read_index(career_path)

    entries = match_file_entries(container_index)

    assert [(entry.name, entry.extension) for entry in entries] == [
        (name, extension) for name, extension, _payload in CAREER_ATTACHMENTS
    ]
    assert not any(entry.is_section for entry in entries)


def test_read_directory_entry_returns_each_payload_byte_for_byte(career_path: Path) -> None:
    container_index = read_index(career_path)

    entries = match_file_entries(container_index)

    assert [read_directory_entry(container_index, entry) for entry in entries] == [
        payload for _name, _extension, payload in CAREER_ATTACHMENTS
    ]


def test_a_declared_size_one_byte_short_is_corrupt_and_names_the_entry(career_path: Path) -> None:
    container_index = read_index(career_path)
    entry = match_file_entries(container_index)[1]
    damaged_entry = dataclasses.replace(
        entry, decompressed_size=entry.decompressed_size - SHORT_BY_ONE_BYTE
    )

    with pytest.raises(CorruptSaveError, match=f"{entry.name}{entry.extension}"):
        read_directory_entry(container_index, damaged_entry)


def test_a_file_changed_after_it_was_indexed_is_reported(tmp_path: Path) -> None:
    save_path = career_fragment().write(tmp_path / "career.bin")
    container_index = read_index(save_path)
    entry = match_file_entries(container_index)[0]
    content = bytearray(save_path.read_bytes())
    content.extend(b"appended")
    save_path.write_bytes(bytes(content))
    os.utime(save_path, ns=(0, 0))

    with pytest.raises(SaveChangedError):
        read_directory_entry(container_index, entry)


def test_a_save_with_no_per_match_entry_lists_none(tmp_path: Path) -> None:
    save_path = career_fragment(attachments=()).write(tmp_path / "career.bin")

    assert match_file_entries(read_index(save_path)) == ()
