"""Normal opening and CLI use for the registered FM27 build."""

from pathlib import Path

import pytest

import fmsave
from fmsave.cli import main
from tests.test_fm27_experimental import BUILD, fm27_fragment


def test_registered_fm27_opens_without_an_opt_in(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning, match="FM27"):
        save = fmsave.open(fm27_fragment(tmp_path))
    with save:
        assert save.info.game == "FM27"
        assert save.info.build == BUILD
        assert save._strict


def test_cli_reads_registered_fm27_without_a_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["info", str(fm27_fragment(tmp_path)), "--json"]) == 0
    assert '"game": "FM27"' in capsys.readouterr().out


def test_fm26_keeps_its_existing_larger_decompression_budget(tmp_path: Path) -> None:
    from tests.fixtures.container import build_container_fragment, default_sections, zstd

    sections = default_sections()
    database = next(section for section in sections if section.name == "game_db")
    path = build_container_fragment(
        sections,
        declared_sizes={"game_db.dat": (len(zstd.compress(database.body)), 600 * 1024**2)},
    ).write(tmp_path / "larger-fm26.bin")
    # Opening reads bounded metadata, not the deliberately oversized fictional database.
    with fmsave.open(path) as save:
        assert save.info.game == "FM26"
        assert save._container_index.limits.total_decompressed_cap == 4 * 1024**3
