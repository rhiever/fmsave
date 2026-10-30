"""Fictional fragments exercise the explicitly bounded FM27 experiment."""

from __future__ import annotations

import struct
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._errors import UnsupportedGameError
from fmsave._layouts import GameInfoLayout, TrainingLayout, find_layout, known_builds
from fmsave.cli import main
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    length_prefixed,
    packed_date,
    section_body,
)
from tests.fixtures.nations import nation_table_bytes

BUILD = "27.0.0+2486695"


def fm27_fragment(
    tmp_path: Path,
    *,
    build: str = BUILD,
    info_schema: int = 47,
    game_db: bytes = bytes(64),
    summary_date: bytes = packed_date(190, 2032),
) -> Path:
    # Independent synthetic metadata: no save bytes, derived identities or real text.
    base = 8 + len(length_prefixed("27.0.0+0"))
    info = bytearray(section_body(".dat", info_schema, length_prefixed("27.0.0+0")))
    info.extend(bytes(base + 390 - len(info)))
    number = int(build.split("+")[1])
    struct.pack_into("<I", info, base + 38, number)
    struct.pack_into("<I", info, base + 165, 0)
    info[base + 174 : base + 178] = packed_date(1, 1900)
    struct.pack_into("<II", info, base + 382, number, 0)
    summary = length_prefixed("EXAMPLE,SETUP") + length_prefixed(build)
    summary += struct.pack("<I", 1) + length_prefixed("Example Division")
    summary += bytes(8) + length_prefixed("Alex Example") + length_prefixed("Northbridge FC")
    summary += struct.pack("<I", 5001) + summary_date
    return build_container_fragment(
        [
            SectionFrame("game_info", bytes(info)),
            SectionFrame("save_game_summary", section_body(".dat", 31, summary)),
            SectionFrame("game_db", section_body(".dat", 4000, game_db)),
        ]
    ).write(tmp_path / "example.bin")


def test_fm27_still_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedGameError):
        fmsave.open(fm27_fragment(tmp_path))


def test_fm27_exact_experiment_reads_structured_metadata(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="experimental"):
        save = fmsave.open(fm27_fragment(tmp_path), experimental_fm27=True)
    with save:
        assert save.info.game == "FM27"
        assert save.info.build == BUILD
        assert save.info.game_date == date(2032, 7, 8)
        assert save.info.db_version == "27.0.0+0"
        assert not save.info.known_build
    assert BUILD not in known_builds()


@pytest.mark.parametrize("build,schema", [("27.0.1+3000001", 47), (BUILD, 48)])
def test_fm27_unknown_build_or_metadata_schema_fails_closed(
    tmp_path: Path, build: str, schema: int
) -> None:
    with pytest.raises(UnsupportedGameError):
        fmsave.open(
            fm27_fragment(tmp_path, build=build, info_schema=schema), experimental_fm27=True
        )


def test_fm27_layouts_never_borrow_across_game_editions() -> None:
    with pytest.raises(UnsupportedGameError):
        find_layout(TrainingLayout, "training_man", 33, BUILD)
    with pytest.raises(UnsupportedGameError):
        find_layout(GameInfoLayout, "game_info", 46, BUILD)
    with pytest.raises(UnsupportedGameError):
        find_layout(GameInfoLayout, "game_info", 47, "27.9.0+1")


def test_fm27_info_cli_opt_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(fm27_fragment(tmp_path)), "--experimental-fm27", "--json"]) == 0
    captured = capsys.readouterr()
    assert '"game": "FM27"' in captured.out
    assert "Alex Example" not in captured.out
    assert "experimental" in captured.err


def test_fm27_nations_walk_whole_table_and_cache(tmp_path: Path) -> None:
    path = fm27_fragment(tmp_path, game_db=nation_table_bytes())
    with pytest.warns(UserWarning, match="experimental"):
        save = fmsave.open(path, experimental_fm27=True)
    with save:
        rows = save.nations()
        assert len(rows) == 251
        assert rows[0].nation_id == 0
        assert rows[-1].database_id == 900_250
        assert save.nations() is rows
        with pytest.raises((UnsupportedGameError, fmsave.ReaderCheckError)):
            save.players()
    assert rows[0].database_id == 900_000


@pytest.mark.parametrize(
    "data",
    [
        b"",
        nation_table_bytes()[:-1],
        nation_table_bytes() * 2,
        nation_table_bytes().replace(struct.pack("<I", 900_001), struct.pack("<I", 900_000)),
    ],
    ids=("missing", "truncated", "ambiguous", "duplicate-identity"),
)
def test_fm27_nations_fail_closed_even_without_strict(tmp_path: Path, data: bytes) -> None:
    with pytest.warns(UserWarning, match="experimental"):
        save = fmsave.open(fm27_fragment(tmp_path, game_db=data), experimental_fm27=True)
    with save, pytest.raises(fmsave.ReaderCheckError):
        save.nations()


def test_fm27_unrecognized_summary_clock_is_not_silently_accepted(tmp_path: Path) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        fmsave.open(
            fm27_fragment(tmp_path, summary_date=packed_date(0, 2032)), experimental_fm27=True
        )


def test_fm27_validation_does_not_claim_fm26_semantic_verification(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="experimental"):
        save = fmsave.open(
            fm27_fragment(tmp_path, game_db=nation_table_bytes()), experimental_fm27=True
        )
    with save:
        report = fmsave.validate_save(save)
    assert set(report.field_statuses.values()) == {"unconfirmed"}
    statuses = {reader.reader: reader.status for reader in report.readers}
    assert statuses["nations"] == "ok"
    assert statuses["players"] != "ok"


def test_fm27_opt_in_rejects_oversized_frame_before_reading_payload(tmp_path: Path) -> None:
    from fmsave._container import read_index, read_section

    index = read_index(fm27_fragment(tmp_path))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    path = build_container_fragment(
        sections,
        declared_sizes={
            "game_db.dat": (index.sections["game_db"].compressed_size, 256 * 1024**2 + 1)
        },
    ).write(tmp_path / "oversized.bin")
    with pytest.raises(fmsave.CorruptSaveError, match="per-frame cap"):
        fmsave.open(path, experimental_fm27=True)


def test_fm27_opt_in_checks_total_declared_budget_before_payloads(tmp_path: Path) -> None:
    from fmsave._container import read_index, read_section

    index = read_index(fm27_fragment(tmp_path))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    path = build_container_fragment(
        sections,
        declared_sizes={
            name + entry.extension: (entry.compressed_size, 200 * 1024**2)
            for name, entry in index.sections.items()
        },
    ).write(tmp_path / "oversized-total.bin")
    with pytest.raises(fmsave.CorruptSaveError, match="total cap"):
        fmsave.open(path, experimental_fm27=True)


def test_unknown_fm26_metadata_never_tries_an_fm27_layout(tmp_path: Path) -> None:
    path = fm27_fragment(tmp_path, build="26.9.0+1234567")
    with pytest.warns(fmsave.UnknownBuildWarning), pytest.raises(fmsave.ReaderCheckError):
        fmsave.open(path)
