from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from fmsave._container import ContainerIndex, read_index
from fmsave._errors import (
    ISSUES_URL,
    CorruptSaveError,
    ReaderCheckError,
    UnknownBuildWarning,
    UnsupportedGameError,
)
from fmsave._version import read_save_info
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    save_summary_body,
    section_body,
)


def build_index(
    tmp_path: Path, sections: list[SectionFrame] | None = None, save_name: str = "Example Career"
) -> ContainerIndex:
    fragment = build_container_fragment(sections, save_name=save_name)
    return read_index(fragment.write(tmp_path / "fragment.bin"))


def sections_with(**replacement_bodies: bytes) -> list[SectionFrame]:
    return [
        SectionFrame(
            section.name,
            replacement_bodies.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]


def test_default_fragment_info(tmp_path: Path) -> None:
    save_info = read_save_info(build_index(tmp_path))
    assert save_info.game == "FM26"
    assert save_info.build == "26.3.2+2329565"
    assert save_info.build_number == 2329565
    assert save_info.known_build
    assert save_info.db_version == "26.2.0+0"
    assert save_info.game_date == date(2031, 3, 1)
    assert save_info.time_slot == 66
    assert save_info.save_name == "Example Career"
    assert save_info.file_name == "fragment.bin"
    assert [section.name for section in save_info.sections] == [
        "game_info",
        "memory_pools",
        "save_game_summary",
        "game_db",
        "non_pl_hist_ls",
        "humans",
        "tc_history_dt",
    ]
    first_section = save_info.sections[0]
    assert (first_section.extension, first_section.schema, first_section.file_offset) == (
        ".dat",
        46,
        26,
    )
    assert first_section.compressed_size > 0
    assert first_section.decompressed_size == len(game_info_body())
    assert dict(first_section.unknown) == {"tail0": 0, "tail1": 0}
    assert save_info.sections[-1].extension == ".cmt"
    assert dict(save_info.section_schemas) == {
        "game_info": 46,
        "memory_pools": 3,
        "save_game_summary": 29,
        "game_db": 4000,
        "non_pl_hist_ls": 5,
        "humans": 21,
        "tc_history_dt": 7,
    }


def test_longer_database_version_shifts_later_fields(tmp_path: Path) -> None:
    body = game_info_body(
        db_version="26.10.12+345", game_day_of_year=200, game_year=2045, time_slot=3
    )
    save_info = read_save_info(build_index(tmp_path, sections_with(game_info=body)))
    assert save_info.db_version == "26.10.12+345"
    assert save_info.game_date == date(2045, 1, 1) + timedelta(days=199)
    assert save_info.time_slot == 3


def test_future_game_is_unsupported(tmp_path: Path) -> None:
    body = save_summary_body(version="27.0.1+3000001")
    with pytest.raises(UnsupportedGameError) as error_info:
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))
    assert "FM27" in str(error_info.value)
    assert ISSUES_URL in str(error_info.value)


def test_missing_version_is_unsupported(tmp_path: Path) -> None:
    body = save_summary_body(version="not a version")
    with pytest.raises(UnsupportedGameError):
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))


def test_version_without_length_prefix_is_ignored(tmp_path: Path) -> None:
    body = section_body(".dat", 29, b"xxxx26.3.2+2329565")
    with pytest.raises(UnsupportedGameError):
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))


def test_unknown_fm26_build_warns_and_uses_fallback(tmp_path: Path) -> None:
    sections = sections_with(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(build_numbers=(2400000, 2400000, 2400000)),
    )
    index = build_index(tmp_path, sections)
    with pytest.warns(UnknownBuildWarning, match="26.4.0"):
        save_info = read_save_info(index)
    assert not save_info.known_build
    assert save_info.build_number == 2400000
    assert save_info.game_date == date(2031, 3, 1)


def test_mismatched_build_numbers_fail_checks(tmp_path: Path) -> None:
    body = game_info_body(build_numbers=(2329565, 2329565, 1))
    with pytest.raises(ReaderCheckError):
        read_save_info(build_index(tmp_path, sections_with(game_info=body)))


def test_bad_section_signature_is_corrupt(tmp_path: Path) -> None:
    sections = default_sections() + [SectionFrame("broken_example", bytes(16))]
    with pytest.raises(CorruptSaveError):
        read_save_info(build_index(tmp_path, sections))


def test_unknown_game_info_schema_uses_fallback_layout(tmp_path: Path) -> None:
    save_info = read_save_info(
        build_index(tmp_path, sections_with(game_info=game_info_body(schema=47)))
    )
    assert save_info.section_schemas["game_info"] == 47
    assert save_info.game_date == date(2031, 3, 1)


def test_save_info_is_immutable(tmp_path: Path) -> None:
    save_info = read_save_info(build_index(tmp_path))
    with pytest.raises(AttributeError):
        save_info.game = "FM99"  # type: ignore[misc]
    with pytest.raises(TypeError):
        save_info.section_schemas["game_info"] = 1  # type: ignore[index]
