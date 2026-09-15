"""Run the atheris harness's per-input function without atheris."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

import fmsave
import fmsave._container
from fuzz.fuzz_container import run_one_input, seed_inputs
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
    assert called == ["managed_clubs"]


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
