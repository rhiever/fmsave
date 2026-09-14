"""Fuzz fmsave.open with damaged metadata sections inside an otherwise valid container."""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

import fmsave
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    game_info_body,
    save_summary_body,
)

METADATA_BODIES = {"game_info": game_info_body(), "save_game_summary": save_summary_body()}
METADATA_SECTION_NAMES = sorted(METADATA_BODIES)


def open_with_replaced_body(section_name: str, replacement_body: bytes) -> None:
    """Open a fragment whose named section holds `replacement_body`; only fmsave errors may escape.

    The documented UnknownBuildWarning is silenced; any other warning fails the test.
    """
    sections = [
        SectionFrame(
            section.name,
            replacement_body if section.name == section_name else section.body,
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    fragment = build_container_fragment(sections)
    with tempfile.TemporaryDirectory() as temporary_folder:
        fragment_path = fragment.write(Path(temporary_folder) / "fuzz.bin")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warnings.simplefilter("ignore", fmsave.UnknownBuildWarning)
            try:
                with fmsave.open(fragment_path) as career_save:
                    repr(career_save.info)
            except fmsave.FmsaveError:
                pass


@settings(max_examples=300, deadline=None)
@given(section_name=st.sampled_from(METADATA_SECTION_NAMES), data=st.data())
def test_mutated_metadata_bodies(section_name: str, data: st.DataObject) -> None:
    mutated_body = bytearray(METADATA_BODIES[section_name])
    byte_changes = data.draw(
        st.lists(
            st.tuples(st.integers(0, len(mutated_body) - 1), st.integers(0, 255)),
            min_size=1,
            max_size=4,
        )
    )
    for position, new_value in byte_changes:
        mutated_body[position] = new_value
    open_with_replaced_body(section_name, bytes(mutated_body))


@settings(max_examples=200, deadline=None)
@given(section_name=st.sampled_from(METADATA_SECTION_NAMES), data=st.data())
def test_truncated_metadata_bodies(section_name: str, data: st.DataObject) -> None:
    original_body = METADATA_BODIES[section_name]
    kept_length = data.draw(st.integers(0, len(original_body) - 1))
    open_with_replaced_body(section_name, original_body[:kept_length])
