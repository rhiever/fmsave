"""What a cold call to each public reader decompresses, counted section by section.

A section is decompressed where its borrow starts, so counting the reads counts the
decompressions. Two readers shipped a cold call that decompressed the several-hundred-megabyte
game database twice, both times because a lookup that reads it too was called just outside the
borrow instead of just inside it; both were caught by eye rather than by a test. This file pins
the whole picture for every reader fmsave has, so the next one cannot pass unnoticed: a reader
that opens a second borrow of a section it already holds, or reaches for a section it has no
business in, changes a number here.

The counts are per cold call: one freshly opened save, one reader, nothing cached. They are
not performance targets; they are the shape of the call, and a change to one is a change that
has to be made deliberately.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

import fmsave
from fmsave import _context as context_module
from fmsave._container import ContainerIndex, DirectoryEntry
from fmsave._context import SaveContext
from tests.fixtures.career import career_fragment

GAME_DB = "game_db"
HUMANS = "humans"
SAVE_SUMMARY = "save_game_summary"
SPAN = "region:unlisted_after_non_pl_hist_ls"
FEEDER = "feeder_man"
JOB_CENTRE = "job_centre"
INJURY_MANAGER = "injury_manager"
TRAINING = "training_man"
TACTICS = "tactics_man"

# Every public reader, with what one cold call decompresses and how many per-match entries it
# reads. A reader absent from a section's entry never touches that section.
READER_SECTION_READS: dict[str, tuple[dict[str, int], int]] = {
    "clubs": ({GAME_DB: 1}, 0),
    "players": ({GAME_DB: 1}, 0),
    "contracts": ({GAME_DB: 1}, 0),
    "suspensions": ({GAME_DB: 1}, 0),
    "managed_clubs": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1}, 0),
    "stages": ({GAME_DB: 1}, 0),
    "competitions": ({GAME_DB: 1}, 0),
    "fixtures": ({GAME_DB: 1, SPAN: 1}, 0),
    "league_tables": ({GAME_DB: 1, SPAN: 1}, 0),
    "transfer_windows": ({GAME_DB: 1}, 0),
    "competition_rules": ({GAME_DB: 1, SPAN: 1}, 0),
    "player_match_stats": ({GAME_DB: 1}, 0),
    "stadiums": ({GAME_DB: 1, SPAN: 1}, 0),
    "finances": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1}, 0),
    "sponsorships": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1}, 0),
    "affiliates": ({GAME_DB: 1, FEEDER: 1}, 0),
    "job_vacancies": ({GAME_DB: 1, JOB_CENTRE: 1}, 0),
    "staff": ({GAME_DB: 1, HUMANS: 1}, 0),
    "staff_lists": ({GAME_DB: 1, HUMANS: 1}, 0),
    # The injury type names live in the per-match entries and nowhere else, so this is the one
    # reader that decompresses no section at all.
    "injury_types": ({}, 2),
    "injuries": ({GAME_DB: 1, INJURY_MANAGER: 1}, 2),
    "training": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1, TRAINING: 1}, 0),
    "mentoring": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1, TRAINING: 1}, 0),
    "tactics": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1, TACTICS: 1}, 0),
    "set_pieces": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1, TACTICS: 1}, 0),
    "facilities": ({GAME_DB: 1, HUMANS: 1, SAVE_SUMMARY: 1}, 0),
}


@pytest.fixture(scope="module")
def career_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One career fragment for the whole module; every test here only reads it."""
    return career_fragment().write(tmp_path_factory.mktemp("section reads") / "career.bin")


class ReadCounter:
    """Counts what a call decompresses, by section name and by per-match entry."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sections_read: list[str] = []
        self.match_entries_read: list[str] = []
        read_section = context_module.read_section
        read_region_frames = context_module.read_region_frames
        read_directory_entry = context_module.read_directory_entry

        def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
            self.sections_read.append(name)
            return read_section(container_index, name)

        def counting_read_region_frames(
            container_index: ContainerIndex, region_name: str
        ) -> Iterator[bytes]:
            self.sections_read.append(f"region:{region_name}")
            return read_region_frames(container_index, region_name)

        def counting_read_directory_entry(
            container_index: ContainerIndex, entry: DirectoryEntry
        ) -> bytes:
            self.match_entries_read.append(f"{entry.name}{entry.extension}")
            return read_directory_entry(container_index, entry)

        monkeypatch.setattr(context_module, "read_section", counting_read_section)
        monkeypatch.setattr(context_module, "read_region_frames", counting_read_region_frames)
        monkeypatch.setattr(context_module, "read_directory_entry", counting_read_directory_entry)

    def section_counts(self) -> dict[str, int]:
        return dict(Counter(self.sections_read))


@pytest.mark.parametrize("reader_name", sorted(READER_SECTION_READS))
def test_a_cold_reader_call_decompresses_each_section_the_pinned_number_of_times(
    career_path: Path, monkeypatch: pytest.MonkeyPatch, reader_name: str
) -> None:
    expected_sections, expected_match_entries = READER_SECTION_READS[reader_name]
    counter = ReadCounter(monkeypatch)

    with fmsave.open(career_path) as career_save:
        rows = getattr(career_save, reader_name)()
        assert len(rows) > 0, reader_name

    assert counter.section_counts() == expected_sections
    assert len(counter.match_entries_read) == expected_match_entries


def test_every_reader_validate_runs_has_a_pinned_read_count(career_path: Path) -> None:
    """The pinned readers are exactly the ones `validate` runs, so a new one cannot skip this.

    A reader added to `validate_save` without a line above would otherwise never have its cold
    call counted, which is how the two doubled decompressions went unnoticed in the first
    place.
    """
    with fmsave.open(career_path) as career_save:
        report = fmsave.validate_save(career_save)

    assert sorted(reader.reader for reader in report.readers) == sorted(READER_SECTION_READS)


def test_a_failing_pass_is_decoded_once_however_many_readers_want_it(
    career_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pass that fails costs what it costs once, not once per reader that asked for it.

    Six of the readers `validate` runs share the player pass. While a failed build stored
    nothing, each of them paid to decode it again and fail again, so the slowest run of all
    was the one over a save fmsave cannot read.
    """
    builder_calls: list[int] = []

    def failing_build(self: object) -> object:
        builder_calls.append(1)
        raise fmsave.CorruptSaveError("fictional failure")

    monkeypatch.setattr(SaveContext, "_build_player_records", failing_build)

    with fmsave.open(career_path) as career_save:
        report = fmsave.validate_save(career_save)

    assert builder_calls == [1]
    failed_readers = [reader.reader for reader in report.readers if reader.status != "ok"]
    assert len(failed_readers) > 1, failed_readers


def test_a_warm_second_call_decompresses_nothing(
    career_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tables are cached, so calling every reader twice reads no section a second time."""
    counter = ReadCounter(monkeypatch)

    with fmsave.open(career_path) as career_save:
        for reader_name in READER_SECTION_READS:
            getattr(career_save, reader_name)()
        first_pass_counts = counter.section_counts()
        first_pass_entries = len(counter.match_entries_read)
        for reader_name in READER_SECTION_READS:
            getattr(career_save, reader_name)()

    assert counter.section_counts() == first_pass_counts
    assert len(counter.match_entries_read) == first_pass_entries
