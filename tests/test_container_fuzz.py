from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from fmsave._container import (
    ContainerLimits,
    read_index,
    read_region_frames,
    read_section,
    read_section_heads,
)
from fmsave._errors import FmsaveError
from tests.fixtures.container import FILE_MAGIC, build_container_fragment

FUZZ_LIMITS = ContainerLimits(
    total_decompressed_cap=16 * 1024 * 1024, frame_decompressed_cap=4 * 1024 * 1024
)
VALID_CONTENT = build_container_fragment().content


def exercise_container(content: bytes) -> None:
    """Run every container read; only fmsave errors may escape."""
    with tempfile.TemporaryDirectory() as temporary_folder:
        file_path = Path(temporary_folder) / "fuzz.bin"
        file_path.write_bytes(content)
        try:
            container_index = read_index(file_path, FUZZ_LIMITS)
            section_names = list(container_index.sections)
            read_section_heads(container_index, section_names, 8)
            for section_name in section_names:
                read_section(container_index, section_name)
            for region_name, region in container_index.regions.items():
                if region.entry is None:
                    list(read_region_frames(container_index, region_name))
        except FmsaveError:
            pass


@settings(max_examples=200, deadline=None)
@given(content=st.binary(max_size=512))
def test_random_bytes(content: bytes) -> None:
    exercise_container(content)


@settings(max_examples=200, deadline=None)
@given(content=st.binary(max_size=512))
def test_random_bytes_after_magic(content: bytes) -> None:
    exercise_container(FILE_MAGIC + content)


@settings(max_examples=300, deadline=None)
@given(
    position=st.integers(min_value=0, max_value=len(VALID_CONTENT) - 1),
    new_value=st.integers(0, 255),
)
def test_single_byte_mutations(position: int, new_value: int) -> None:
    mutated = bytearray(VALID_CONTENT)
    mutated[position] = new_value
    exercise_container(bytes(mutated))


@settings(max_examples=200, deadline=None)
@given(length=st.integers(min_value=0, max_value=len(VALID_CONTENT)))
def test_truncations(length: int) -> None:
    exercise_container(VALID_CONTENT[:length])
