from __future__ import annotations

from pathlib import Path

import pytest

import fmsave
import fmsave._context as context_module
from fmsave._container import ContainerIndex
from fmsave._context import SaveContext
from tests.fixtures.container import build_container_fragment, default_sections

HUMANS_BODY = next(section.body for section in default_sections() if section.name == "humans")


@pytest.fixture
def fragment_path(tmp_path: Path) -> Path:
    return build_container_fragment().write(tmp_path / "Private Folder" / "career fragment.bin")


@pytest.fixture
def section_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the name of every section the context decompresses."""
    recorded_names: list[str] = []
    original_read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        recorded_names.append(name)
        return original_read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)
    return recorded_names


def test_save_owns_a_context(fragment_path: Path) -> None:
    with fmsave.open(fragment_path) as career_save:
        assert isinstance(career_save._context, SaveContext)
        assert career_save._context.info is career_save.info
        assert not career_save._context.closed


def test_save_closed_state_comes_from_its_context(fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    career_save._context.close()
    assert career_save.closed
    assert "closed" in repr(career_save)
    with pytest.raises(fmsave.SaveClosedError):
        career_save._read_section("humans")
    career_save.close()
    assert career_save.closed


def test_nested_section_entries_share_one_read(
    fragment_path: Path, section_reads: list[str]
) -> None:
    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        with context.section("humans") as outer:
            with context.section("humans") as inner:
                assert inner is outer
                assert inner == HUMANS_BODY
            assert section_reads == ["humans"]
        with context.section("humans") as reread:
            assert reread == HUMANS_BODY
    assert section_reads == ["humans", "humans"]


def test_different_sections_are_read_separately(
    fragment_path: Path, section_reads: list[str]
) -> None:
    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        with context.section("humans") as humans, context.section("game_db") as game_db:
            assert humans == HUMANS_BODY
            assert game_db != humans
    assert section_reads == ["humans", "game_db"]


def test_section_bytes_are_released_when_the_body_raises(
    fragment_path: Path, section_reads: list[str]
) -> None:
    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        with pytest.raises(LookupError, match="fictional failure"), context.section("humans"):
            raise LookupError("fictional failure")
        with context.section("humans"):
            pass
    assert section_reads == ["humans", "humans"]


def test_failed_section_read_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, fragment_path: Path, section_reads: list[str]
) -> None:
    counting_read_section = context_module.read_section
    remaining_failures = ["humans"]

    def read_section_failing_once(container_index: ContainerIndex, name: str) -> bytes:
        section_bytes = counting_read_section(container_index, name)
        if name in remaining_failures:
            remaining_failures.remove(name)
            raise fmsave.CorruptSaveError("fictional damage")
        return section_bytes

    monkeypatch.setattr(context_module, "read_section", read_section_failing_once)
    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        with (
            pytest.raises(fmsave.CorruptSaveError, match="fictional damage"),
            context.section("humans"),
        ):
            pytest.fail("the body must not run when the section read fails")
        for _ in range(2):
            with context.section("humans") as humans:
                assert humans == HUMANS_BODY
        assert context._loan_counts == {}
        assert context._loaned_sections == {}
    assert section_reads == ["humans", "humans", "humans"]


def test_cached_builds_once_and_returns_the_same_object(fragment_path: Path) -> None:
    builder_calls: list[int] = []

    def build_table() -> fmsave.Table[fmsave.SectionInfo]:
        builder_calls.append(1)
        return fmsave.Table(career_save.info.sections, fmsave.SectionInfo)

    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        first_value = context.cached("key", build_table)
        second_value = context.cached("key", build_table)
    assert first_value is second_value
    assert builder_calls == [1]


def test_cached_does_not_store_a_failed_build(fragment_path: Path) -> None:
    def failing_build() -> str:
        raise LookupError("fictional failure")

    with fmsave.open(fragment_path) as career_save:
        context = career_save._context
        with pytest.raises(LookupError):
            context.cached("key", failing_build)
        assert context.cached("key", lambda: "Northbridge FC") == "Northbridge FC"


def test_build_that_closes_the_save_is_returned_but_not_kept(fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    context = career_save._context

    def closing_build() -> str:
        career_save.close()
        return "Northbridge FC"

    assert context.cached("key", closing_build) == "Northbridge FC"
    assert "0 cached" in repr(context)


def test_close_releases_the_context(fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    context = career_save._context
    kept_table = context.cached(
        "table:sections", lambda: fmsave.Table(career_save.info.sections, fmsave.SectionInfo)
    )
    career_save.close()
    assert context.closed
    assert career_save.closed
    with pytest.raises(fmsave.SaveClosedError):
        context.cached("table:sections", lambda: None)
    with pytest.raises(fmsave.SaveClosedError):
        context.section("humans")
    with pytest.raises(fmsave.SaveClosedError):
        career_save._read_section("humans")
    assert len(kept_table) == len(default_sections())
    assert kept_table.find(name="humans")[0].compressed_size > 0
    context.close()
    assert context.closed


def test_close_inside_a_section_entry(fragment_path: Path, section_reads: list[str]) -> None:
    career_save = fmsave.open(fragment_path)
    context = career_save._context
    with context.section("humans") as humans:
        career_save.close()
        assert humans == HUMANS_BODY
        with pytest.raises(fmsave.SaveClosedError):
            context.section("humans")
    assert context.closed
    assert section_reads == ["humans"]


def test_repr_shows_nothing_sensitive(tmp_path: Path, fragment_path: Path) -> None:
    career_save = fmsave.open(fragment_path)
    context = career_save._context
    context.cached("key", lambda: "Northbridge FC")
    for description in (repr(context), str(context)):
        assert "Example Career" not in description
        assert "career fragment" not in description
        assert "Private Folder" not in description
        assert str(tmp_path) not in description
        assert "Northbridge" not in description
    career_save.close()
    assert "closed" in repr(context)
