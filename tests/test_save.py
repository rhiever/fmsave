from __future__ import annotations

import os
import warnings
from pathlib import Path

import pytest

import fmsave
from fmsave._save import open_save
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    save_summary_body,
)


@pytest.fixture
def fragment_path(tmp_path: Path) -> Path:
    return build_container_fragment().write(tmp_path / "Ünïcode folder" / "career fragment.bin")


def test_open_as_context_manager(fragment_path: Path) -> None:
    with fmsave.open(fragment_path) as career_save:
        assert not career_save.closed
        assert career_save.info.game == "FM26"
    assert career_save.closed
    assert career_save.info.save_name == "Example Career"


def test_open_accepts_str(fragment_path: Path) -> None:
    with fmsave.open(str(fragment_path)) as career_save:
        assert career_save.info.file_name == "career fragment.bin"


def test_read_section_while_open(fragment_path: Path) -> None:
    humans_body = next(section.body for section in default_sections() if section.name == "humans")
    with fmsave.open(fragment_path) as career_save:
        assert career_save._read_section("humans") == humans_body


def test_readers_after_close_raise(fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    career_save.close()
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save._read_section("humans")


def test_repr_hides_save_name_and_path(tmp_path: Path, fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    description = repr(career_save)
    assert "FM26" in description and "open" in description
    assert "Example Career" not in description
    assert "career fragment" not in description
    assert str(tmp_path) not in description
    career_save.close()
    assert "closed" in repr(career_save)


def test_file_is_not_held_open(tmp_path: Path, fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    career_save._read_section("humans")
    replacement_path = build_container_fragment(save_name="Replacement").write(
        tmp_path / "replacement.bin"
    )
    os.replace(replacement_path, fragment_path)
    with pytest.raises(fmsave.SaveChangedError):
        career_save._read_section("humans")
    os.remove(fragment_path)
    career_save.close()


def test_errors_name_the_file_but_not_its_folder(tmp_path: Path) -> None:
    file_path = tmp_path / "Private Folder Name" / "notes.txt"
    file_path.parent.mkdir()
    file_path.write_text("not a save", encoding="utf-8")
    with pytest.raises(fmsave.NotAFmSaveError) as error_info:
        fmsave.open(file_path)
    assert "notes.txt" in str(error_info.value)
    assert "Private Folder Name" not in str(error_info.value)


def test_unknown_build_warning_points_at_the_caller(tmp_path: Path) -> None:
    sections = [
        SectionFrame(
            section.name,
            {
                "save_game_summary": save_summary_body(version="26.4.0+2400000"),
                "game_info": game_info_body(build_numbers=(2400000, 2400000, 2400000)),
            }.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    fragment_path = build_container_fragment(sections).write(tmp_path / "fragment.bin")
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        career_save = fmsave.open(fragment_path)
    assert [caught.category for caught in caught_warnings] == [fmsave.UnknownBuildWarning]
    assert caught_warnings[0].filename == __file__
    assert not career_save.info.known_build


def test_open_is_the_public_alias() -> None:
    assert fmsave.open is open_save
