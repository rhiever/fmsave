"""Fuzz fmsave's container, metadata and record readers with atheris.

Each input is written to a temporary file, which is opened and then read by every Save
reader. fmsave's own errors are expected on damaged input; any other exception is a crash.
`run_one_input` and `seed_inputs` work without atheris, so tests can call them. See
fuzz/README.md for how to run the fuzzer.
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOTAL_DECOMPRESSED_CAP = 16 * 1024 * 1024
FRAME_DECOMPRESSED_CAP = 4 * 1024 * 1024


def seed_inputs() -> list[bytes]:
    """Starting inputs, built only by the test fixture builders."""
    from tests.fixtures.career import career_fragment
    from tests.fixtures.container import build_container_fragment

    return [
        build_container_fragment().content,
        career_fragment().content,
        career_fragment(duplicate_club_name=True).content,
        career_fragment(manager_between_jobs=True).content,
    ]


def run_one_input(data: bytes) -> None:
    """Read `data` as a save with every reader; only fmsave.FmsaveError is swallowed.

    fmsave is imported here, not at module level, so the fuzzer can instrument it first.
    """
    import fmsave
    from fmsave._container import ContainerLimits, read_index
    from fmsave._version import read_save_info

    limits = ContainerLimits(
        total_decompressed_cap=TOTAL_DECOMPRESSED_CAP, frame_decompressed_cap=FRAME_DECOMPRESSED_CAP
    )
    with tempfile.TemporaryDirectory() as temporary_folder:
        input_path = Path(temporary_folder) / "input.bin"
        input_path.write_bytes(data)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", fmsave.UnknownBuildWarning)
            try:
                container_index = read_index(input_path, limits)
                save_info = read_save_info(container_index)
            except fmsave.FmsaveError:
                return
            with fmsave.Save(container_index, save_info) as career_save:
                repr(career_save.info)
                for reader in (
                    career_save.clubs,
                    career_save.players,
                    career_save.contracts,
                    career_save.suspensions,
                    career_save.managed_clubs,
                ):
                    try:
                        len(reader())
                    except fmsave.FmsaveError:
                        pass


def main() -> None:
    import atheris  # pyright: ignore[reportMissingImports]

    sys.path.insert(0, str(REPOSITORY_ROOT))
    with atheris.instrument_imports():  # pyright: ignore[reportUnknownMemberType]
        import fmsave  # noqa: F401  # pyright: ignore[reportUnusedImport]

    arguments = list(sys.argv)
    inputs = [argument for argument in arguments[1:] if not argument.startswith("-")]
    if all(Path(argument).is_dir() for argument in inputs):
        # libFuzzer writes new inputs to the first folder given, so the seeds go last.
        # Individual input files (such as a crash to replay) run on their own.
        seed_folder = Path(tempfile.mkdtemp(prefix="fmsave-fuzz-seeds-"))
        for seed_number, seed in enumerate(seed_inputs()):
            (seed_folder / f"seed-{seed_number}").write_bytes(seed)
        arguments.append(str(seed_folder))
    atheris.Setup(arguments, run_one_input)  # pyright: ignore[reportUnknownMemberType]
    atheris.Fuzz()  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    main()
