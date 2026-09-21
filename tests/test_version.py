from __future__ import annotations

import copy
import pickle
import struct
import warnings
from datetime import date, timedelta
from pathlib import Path

import pytest

import fmsave._version as version_module
from fmsave._container import RETRY_HINT, ContainerIndex, read_index
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
    length_prefixed,
    packed_date,
    save_summary_body,
    section_body,
)

OVERLONG_DB_VERSION = "2" * 65


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


def unknown_build_warnings(
    caught_warnings: list[warnings.WarningMessage],
) -> list[warnings.WarningMessage]:
    return [
        caught_warning
        for caught_warning in caught_warnings
        if issubclass(caught_warning.category, UnknownBuildWarning)
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


def structured_summary_body(
    *,
    divisions: tuple[str, ...] = ("Example Division",),
    club_name: str = "",
    summary_date: bytes = packed_date(188, 2025),
) -> bytes:
    """Invented schema-29 fields, with variable strings before its structured clock."""
    payload = length_prefixed("EXAMPLE,SETUP") + length_prefixed("26.3.2+2329565")
    payload += struct.pack("<I", len(divisions))
    payload += b"".join(length_prefixed(division) for division in divisions)
    payload += bytes(8) + length_prefixed("Alex Example") + length_prefixed(club_name)
    payload += struct.pack("<I", 5001 if club_name else 0xFFFFFFFF) + summary_date
    return section_body(".dat", 29, payload)


@pytest.mark.parametrize("divisions", [(), ("Example Division", "Liga Fictícia")])
@pytest.mark.parametrize("club_name", ["", "Northbridge FC"])
def test_null_clock_uses_the_structured_summary_date(
    tmp_path: Path, divisions: tuple[str, ...], club_name: str
) -> None:
    sections = sections_with(
        game_info=game_info_body(game_day_of_year=1, game_year=1900, time_slot=0),
        save_game_summary=structured_summary_body(divisions=divisions, club_name=club_name),
    )
    save_info = read_save_info(build_index(tmp_path, sections))
    assert save_info.game_date == date(2025, 7, 7)
    assert save_info.time_slot == 0


def test_normal_clock_takes_precedence_over_the_summary_date(tmp_path: Path) -> None:
    sections = sections_with(save_game_summary=structured_summary_body())
    assert read_save_info(build_index(tmp_path, sections)).game_date == date(2031, 3, 1)


@pytest.mark.parametrize(
    "summary",
    [
        save_summary_body() + packed_date(188, 2025),
        structured_summary_body()[:-1],
        structured_summary_body(summary_date=packed_date(0, 2025)),
        structured_summary_body(summary_date=packed_date(366, 2025)),
        section_body(
            ".dat",
            29,
            length_prefixed("EXAMPLE")
            + length_prefixed("26.3.2+2329565")
            + struct.pack("<I", 0xFFFFFFFF)
            + packed_date(188, 2025),
        ),
    ],
    ids=["date-outside-structure", "truncated", "null-date", "invalid-date", "absurd-count"],
)
def test_unreadable_structured_summary_leaves_a_null_clock_unset(
    tmp_path: Path, summary: bytes
) -> None:
    sections = sections_with(
        game_info=game_info_body(game_day_of_year=1, game_year=1900, time_slot=0),
        save_game_summary=summary,
    )
    assert read_save_info(build_index(tmp_path, sections)).game_date is None


@pytest.mark.parametrize("trailing_length", [14, 47, 48, 57, 58, 304])
def test_version_is_found_whatever_length_the_next_string_has(
    tmp_path: Path, trailing_length: int
) -> None:
    body = save_summary_body(version="26.3.2+2329565", trailing_strings=("x" * trailing_length,))
    save_info = read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))
    assert save_info.build == "26.3.2+2329565"
    assert save_info.build_number == 2329565


def test_future_game_is_unsupported(tmp_path: Path) -> None:
    body = save_summary_body(version="27.0.1+3000001")
    with pytest.raises(UnsupportedGameError) as error_info:
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))
    assert "FM27" in str(error_info.value)
    assert ISSUES_URL in str(error_info.value)


def test_future_game_is_unsupported_even_when_other_section_signatures_differ(
    tmp_path: Path,
) -> None:
    sections = sections_with(
        save_game_summary=save_summary_body(version="27.0.1+3000001"), memory_pools=bytes(16)
    )
    with pytest.raises(UnsupportedGameError, match="FM27"):
        read_save_info(build_index(tmp_path, sections))


def test_missing_version_is_unsupported(tmp_path: Path) -> None:
    body = save_summary_body(version="not a version")
    with pytest.raises(UnsupportedGameError):
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))


def test_version_without_length_prefix_is_ignored(tmp_path: Path) -> None:
    body = section_body(".dat", 29, b"xxxx26.3.2+2329565")
    with pytest.raises(UnsupportedGameError):
        read_save_info(build_index(tmp_path, sections_with(save_game_summary=body)))


def test_unknown_fm26_build_warns_once_and_uses_fallback(tmp_path: Path) -> None:
    sections = sections_with(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(build_numbers=(2400000, 2400000, 2400000)),
    )
    index = build_index(tmp_path, sections)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        save_info = read_save_info(index)
    build_warnings = unknown_build_warnings(caught_warnings)
    assert len(build_warnings) == 1
    assert "26.4.0" in str(build_warnings[0].message)
    assert not save_info.known_build
    assert save_info.build_number == 2400000
    assert save_info.game_date == date(2031, 3, 1)


def test_known_build_does_not_warn(tmp_path: Path) -> None:
    index = build_index(tmp_path)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        save_info = read_save_info(index)
    assert unknown_build_warnings(caught_warnings) == []
    assert save_info.known_build


def test_mismatched_build_numbers_fail_checks(tmp_path: Path) -> None:
    body = game_info_body(build_numbers=(2329565, 2329565, 1))
    with pytest.raises(ReaderCheckError):
        read_save_info(build_index(tmp_path, sections_with(game_info=body)))


def test_game_info_decode_failure_on_unknown_build_fails_checks(tmp_path: Path) -> None:
    sections = sections_with(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(
            db_version=OVERLONG_DB_VERSION, build_numbers=(2400000, 2400000, 2400000)
        ),
    )
    index = build_index(tmp_path, sections)
    with pytest.warns(UnknownBuildWarning), pytest.raises(ReaderCheckError) as error_info:
        read_save_info(index)
    assert ISSUES_URL in str(error_info.value)


def test_game_info_decode_failure_with_inexact_layout_fails_checks(tmp_path: Path) -> None:
    body = game_info_body(db_version=OVERLONG_DB_VERSION, schema=47)
    with pytest.raises(ReaderCheckError) as error_info:
        read_save_info(build_index(tmp_path, sections_with(game_info=body)))
    assert ISSUES_URL in str(error_info.value)


def test_game_info_decode_failure_on_known_build_and_exact_layout_is_corrupt(
    tmp_path: Path,
) -> None:
    body = game_info_body(db_version=OVERLONG_DB_VERSION)
    with pytest.raises(CorruptSaveError) as error_info:
        read_save_info(build_index(tmp_path, sections_with(game_info=body)))
    message = str(error_info.value)
    assert message.startswith(
        "fragment.bin: game_info is damaged or was being written "
        "(string at offset 8 claims 65 bytes, more than the 64 allowed)"
    )
    assert message.endswith(RETRY_HINT)
    assert isinstance(error_info.value.__cause__, CorruptSaveError)


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


def test_unknown_build_warning_from_a_direct_call_points_at_the_caller(tmp_path: Path) -> None:
    sections = sections_with(
        save_game_summary=save_summary_body(version="26.4.0+2400000"),
        game_info=game_info_body(build_numbers=(2400000, 2400000, 2400000)),
    )
    index = build_index(tmp_path, sections)
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        read_save_info(index)
    build_warnings = unknown_build_warnings(caught_warnings)
    assert len(build_warnings) == 1
    assert build_warnings[0].filename == __file__


def test_save_info_survives_pickle_and_deepcopy(tmp_path: Path) -> None:
    save_info = read_save_info(build_index(tmp_path))
    for copied_info in (pickle.loads(pickle.dumps(save_info)), copy.deepcopy(save_info)):
        assert copied_info == save_info
        assert copied_info.section_schemas == dict(save_info.section_schemas)
        assert copied_info.sections[0].unknown == {"tail0": 0, "tail1": 0}


def test_save_info_holds_the_summary_strings_in_file_order(tmp_path: Path) -> None:
    save_info = read_save_info(build_index(tmp_path))
    assert save_info.summary_strings == (
        "Alex Example",
        "Example League",
        "26.3.2+2329565",
        "Northbridge FC",
    )
    copied_info = pickle.loads(pickle.dumps(save_info))
    assert copied_info.summary_strings == save_info.summary_strings


def test_summary_is_read_once_for_the_version_and_the_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = build_index(tmp_path)
    section_reads: list[str] = []
    original_read_section = version_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        section_reads.append(name)
        return original_read_section(container_index, name)

    monkeypatch.setattr(version_module, "read_section", counting_read_section)
    save_info = read_save_info(index)
    assert section_reads.count("save_game_summary") == 1
    assert "Northbridge FC" in save_info.summary_strings


def test_save_info_repr_hides_folder_save_name_and_sections(tmp_path: Path) -> None:
    fragment_path = build_container_fragment(save_name="Example Career").write(
        tmp_path / "privatefolder" / "fragment.bin"
    )
    description = repr(read_save_info(read_index(fragment_path)))
    assert "privatefolder" not in description
    assert "Example Career" not in description
    assert "SectionInfo" not in description


def test_save_info_is_immutable(tmp_path: Path) -> None:
    save_info = read_save_info(build_index(tmp_path))
    with pytest.raises(AttributeError):
        save_info.game = "FM99"  # type: ignore[misc]
    with pytest.raises(TypeError):
        save_info.section_schemas["game_info"] = 1  # type: ignore[index]
