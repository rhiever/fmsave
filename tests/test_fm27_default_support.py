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


def test_cli_info_calls_the_registered_fm27_build_partial_not_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["info", str(fm27_fragment(tmp_path))]) == 0
    output = capsys.readouterr().out
    assert f"{BUILD} (partial coverage)" in output
    assert "unknown build" not in output


def test_the_registered_fm27_build_is_known_and_still_partial_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A known FM27 build keeps its coverage warning and its partial-coverage label."""
    with pytest.warns(fmsave.UnknownBuildWarning, match="FM27 coverage"):
        save = fmsave.open(fm27_fragment(tmp_path))
    with save:
        assert save.info.known_build
    assert main(["info", str(fm27_fragment(tmp_path))]) == 0
    captured = capsys.readouterr()
    assert f"{BUILD} (partial coverage)" in captured.out
    assert "FM27 coverage" in captured.err
    assert main(["info", str(fm27_fragment(tmp_path)), "--json"]) == 0
    assert '"known_build": true' in capsys.readouterr().out


def test_fm26_opens_a_large_part_under_the_same_file_relative_bounds(tmp_path: Path) -> None:
    from fmsave._container import ContainerLimits
    from tests.fixtures.container import build_container_fragment, default_sections, zstd

    sections = default_sections()
    database = next(section for section in sections if section.name == "game_db")
    padding = 8 * 1024**2
    path = build_container_fragment(
        sections,
        declared_sizes={
            "game_db.dat": (len(zstd.compress(database.body)) + padding, 200 * 1024**2)
        },
        padding_after={"game_db.dat": padding},
    ).write(tmp_path / "larger-fm26.bin")
    # Opening reads bounded metadata, not the deliberately oversized fictional database.
    with fmsave.open(path) as save:
        assert save.info.game == "FM26"
        assert save._container_index.limits == ContainerLimits()
