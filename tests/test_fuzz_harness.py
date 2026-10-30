"""Run the atheris harness's per-input function without atheris."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import fmsave
import fmsave._container
from fmsave.readers.fm27_span import Fm27Span
from fuzz.fuzz_container import READER_NAMES, run_one_input, seed_inputs
from tests.fixtures.container import FILE_MAGIC

pytestmark = pytest.mark.filterwarnings("error")

RANDOM_SEED = 20260915
RANDOM_INPUTS = 60
MUTATED_INPUTS = 80
TRUNCATED_INPUTS = 40
SEEDS = seed_inputs()


def random_bytes(generator: random.Random, max_size: int) -> bytes:
    return generator.randbytes(generator.randint(0, max_size))


def test_seeds_run_every_reader() -> None:
    assert len(SEEDS) >= 2
    for seed in SEEDS:
        run_one_input(seed)


def test_the_harness_runs_every_public_reader() -> None:
    public_readers = {
        name
        for name, member in vars(fmsave.Save).items()
        if not name.startswith("_") and callable(member) and name != "close"
    }
    assert len(READER_NAMES) == len(set(READER_NAMES))
    assert set(READER_NAMES) == public_readers


def test_random_bytes() -> None:
    generator = random.Random(RANDOM_SEED)
    for _ in range(RANDOM_INPUTS):
        run_one_input(random_bytes(generator, 512))
        run_one_input(FILE_MAGIC + random_bytes(generator, 512))


def test_mutated_and_truncated_seeds() -> None:
    generator = random.Random(RANDOM_SEED + 1)
    for _ in range(MUTATED_INPUTS):
        mutated = bytearray(generator.choice(SEEDS))
        for _ in range(generator.randint(1, 4)):
            mutated[generator.randrange(len(mutated))] = generator.randrange(256)
        run_one_input(bytes(mutated))
    for _ in range(TRUNCATED_INPUTS):
        seed = generator.choice(SEEDS)
        run_one_input(seed[: generator.randrange(len(seed))])


def raise_error(error: Exception) -> Callable[..., object]:
    def raising(*_arguments: object, **_keywords: object) -> object:
        raise error

    return raising


def test_fmsave_errors_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fmsave._container, "read_index", raise_error(fmsave.CorruptSaveError("damaged"))
    )
    run_one_input(SEEDS[0])


def test_reader_fmsave_errors_do_not_stop_later_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    original_managed_clubs = fmsave.Save.managed_clubs

    def recording_managed_clubs(career_save: fmsave.Save) -> object:
        called.append("managed_clubs")
        return original_managed_clubs(career_save)

    monkeypatch.setattr(fmsave.Save, "clubs", raise_error(fmsave.ReaderCheckError("no clubs")))
    monkeypatch.setattr(fmsave.Save, "managed_clubs", recording_managed_clubs)
    run_one_input(SEEDS[1])
    assert "managed_clubs" in called


@pytest.mark.parametrize("error", [ValueError("boom"), IndexError("boom"), RuntimeError("boom")])
def test_other_exceptions_escape_from_open(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(fmsave._container, "read_index", raise_error(error))
    with pytest.raises(type(error)):
        run_one_input(SEEDS[0])


def test_other_exceptions_escape_from_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fmsave.Save, "players", raise_error(KeyError("boom")))
    with pytest.raises(KeyError):
        run_one_input(SEEDS[1])


def test_fm27_span_parser_is_reached_in_normal_fuzzing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fmsave._save
    from tests.test_fm27_span_integration import span_fragment

    parsed: list[Fm27Span] = []
    original = fmsave._save.read_fm27_span

    def recording_parser(*args: Any, **kwargs: Any) -> Fm27Span:
        result = original(*args, **kwargs)
        parsed.append(result)
        return result

    monkeypatch.setattr(fmsave._save, "read_fm27_span", recording_parser)
    run_one_input(span_fragment(tmp_path).read_bytes())
    assert len(parsed) == 1
    assert len(parsed[0].fixtures) == 2
    assert parsed[0].fixtures[1].home_goals == 2
    assert len(parsed[0].rules) == 1


@pytest.mark.parametrize("cap", ["TOTAL_DECOMPRESSED_CAP", "FRAME_DECOMPRESSED_CAP"])
def test_fm27_retains_fuzz_decompression_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    import fmsave._save
    import fuzz.fuzz_container as harness
    from tests.test_fm27_span_integration import span_fragment

    monkeypatch.setattr(harness, cap, 32)
    monkeypatch.setattr(
        fmsave._save, "read_fm27_span", raise_error(AssertionError("parser must not be reached"))
    )
    run_one_input(span_fragment(tmp_path).read_bytes())


def test_fm27_parser_unexpected_errors_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fmsave._save
    from tests.test_fm27_span_integration import span_fragment

    monkeypatch.setattr(fmsave._save, "read_fm27_span", raise_error(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        run_one_input(span_fragment(tmp_path).read_bytes())


def test_fuzz_cli_supplies_a_reachable_fm27_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import sys
    from contextlib import nullcontext
    from types import SimpleNamespace

    import fmsave._save
    import fuzz.fuzz_container as harness

    parsed: list[Fm27Span] = []
    original = fmsave._save.read_fm27_span

    def recording_parser(*args: Any, **kwargs: Any) -> Fm27Span:
        result = original(*args, **kwargs)
        parsed.append(result)
        return result

    def setup(arguments: list[str], callback: Callable[[bytes], None]) -> None:
        assert "--experimental-fm27" not in arguments
        seed_folder = Path(arguments[-1])
        try:
            seeds = sorted(seed_folder.iterdir())
            assert len(seeds) == len(SEEDS)
            for seed in seeds:
                callback(seed.read_bytes())
        finally:
            shutil.rmtree(seed_folder)

    monkeypatch.setattr(fmsave._save, "read_fm27_span", recording_parser)
    monkeypatch.setitem(
        sys.modules,
        "atheris",
        SimpleNamespace(instrument_imports=nullcontext, Setup=setup, Fuzz=lambda: None),
    )
    arguments = ["fuzz_container.py", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", arguments)
    harness.main()
    assert len(parsed) == 1
    assert len(parsed[0].fixtures) == 2
    assert len(parsed[0].rules) == 1
