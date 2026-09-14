from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

import pytest

from fmsave._container import ContainerLimits, decompress_frame, read_exact, read_index
from fmsave._errors import CorruptSaveError, NotAFmSaveError
from tests.fixtures.container import (
    FILE_MAGIC,
    HEADER_SIZE,
    TRAILER_HEADER,
    SectionFrame,
    build_container_fragment,
    default_sections,
    section_body,
    skippable_frame,
)

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

EXPECTED_SECTIONS = {
    "game_info",
    "memory_pools",
    "save_game_summary",
    "game_db",
    "non_pl_hist_ls",
    "humans",
    "tc_history_dt",
}


@pytest.fixture
def fragment_path(tmp_path: Path) -> Path:
    return build_container_fragment().write(
        tmp_path / "Ünïcode folder with spaces" / "fragment.bin"
    )


def test_index_lists_sections_attachments_and_save_name(fragment_path: Path) -> None:
    fragment = build_container_fragment()
    container_index = read_index(fragment_path)
    assert container_index.save_name == "Example Career"
    assert set(container_index.sections) == EXPECTED_SECTIONS
    assert [entry.frame_offset for entry in container_index.entries] == sorted(
        entry.frame_offset for entry in container_index.entries
    )
    for entry in container_index.entries:
        assert entry.frame_offset == fragment.frame_offsets[entry.name + entry.extension]
    attachment_entries = [entry for entry in container_index.entries if not entry.is_section]
    assert [(entry.name, entry.extension) for entry in attachment_entries] == [("1_2_3", ".apm")]
    assert container_index.sections["tc_history_dt"].extension == ".cmt"
    assert container_index.sections["humans"].decompressed_size == 8 + 32
    assert all(entry.trailing_values == (0, 0) for entry in container_index.entries)
    assert container_index.trailer_offset == fragment.trailer_offset
    assert container_index.file_name == "fragment.bin"


def test_regions_cover_sections_and_the_unlisted_span(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    unlisted_names = {
        name for name in container_index.regions if name.startswith("unlisted_after_")
    }
    assert unlisted_names == {"unlisted_after_non_pl_hist_ls"}
    unlisted_region = container_index.regions["unlisted_after_non_pl_hist_ls"]
    assert unlisted_region.entry is None
    assert unlisted_region.start == container_index.sections["non_pl_hist_ls"].frame_end
    assert unlisted_region.end == container_index.sections["humans"].frame_offset
    assert set(container_index.regions) == EXPECTED_SECTIONS | unlisted_names
    humans_region = container_index.regions["humans"]
    assert humans_region.entry == container_index.sections["humans"]


def test_fingerprint(fragment_path: Path) -> None:
    container_index = read_index(fragment_path)
    assert container_index.fingerprint.file_size == fragment_path.stat().st_size
    assert container_index.fingerprint.mtime_ns == fragment_path.stat().st_mtime_ns
    assert len(container_index.fingerprint.header_digest) == 64


@pytest.mark.parametrize("content", [b"", b"hello world, not a save", b"\x02\x01fm"])
def test_non_saves_raise_not_a_save(tmp_path: Path, content: bytes) -> None:
    file_path = tmp_path / "Private Folder Name" / "notes.txt"
    file_path.parent.mkdir()
    file_path.write_bytes(content)
    with pytest.raises(NotAFmSaveError) as error_info:
        read_index(file_path)
    assert "Private Folder Name" not in str(error_info.value)


def write_bytes(tmp_path: Path, content: bytes) -> Path:
    file_path = tmp_path / "broken.bin"
    file_path.write_bytes(content)
    return file_path


def test_magic_but_too_short_is_corrupt(tmp_path: Path) -> None:
    with pytest.raises(CorruptSaveError):
        read_index(write_bytes(tmp_path, FILE_MAGIC + bytes(4)))


def test_truncated_file_is_corrupt_with_hint(tmp_path: Path) -> None:
    content = build_container_fragment().content
    with pytest.raises(CorruptSaveError) as error_info:
        read_index(write_bytes(tmp_path, content[:-10]))
    assert "try again" in str(error_info.value)


def test_trailer_pointer_outside_file_is_corrupt(tmp_path: Path) -> None:
    content = bytearray(build_container_fragment().content)
    content[9:17] = (len(content) * 2).to_bytes(8, "little")
    with pytest.raises(CorruptSaveError):
        read_index(write_bytes(tmp_path, bytes(content)))


def test_trailer_pointer_to_wrong_place_is_corrupt(tmp_path: Path) -> None:
    content = bytearray(build_container_fragment().content)
    content[9:17] = (40).to_bytes(8, "little")
    with pytest.raises(CorruptSaveError):
        read_index(write_bytes(tmp_path, bytes(content)))


def test_directory_without_sections_is_corrupt(tmp_path: Path) -> None:
    fragment = build_container_fragment([], attachments=(("1_2_3", ".apm", b"only"),))
    with pytest.raises(CorruptSaveError):
        read_index(fragment.write(tmp_path / "fragment.bin"))


def test_entry_running_past_trailer_is_corrupt(tmp_path: Path) -> None:
    fragment = build_container_fragment(declared_sizes={"humans.dat": (10**9, 40)})
    with pytest.raises(CorruptSaveError):
        read_index(fragment.write(tmp_path / "fragment.bin"))


def test_overlapping_entries_are_corrupt(tmp_path: Path) -> None:
    fragment = build_container_fragment(declared_sizes={"game_info.dat": (10_000, 300)})
    with pytest.raises(CorruptSaveError):
        read_index(fragment.write(tmp_path / "fragment.bin"))


def test_duplicate_section_names_are_corrupt(tmp_path: Path) -> None:
    sections = default_sections() + [SectionFrame("humans", section_body(".dat", 21, bytes(4)))]
    with pytest.raises(CorruptSaveError):
        read_index(build_container_fragment(sections).write(tmp_path / "fragment.bin"))


def test_frame_cap_is_enforced(fragment_path: Path) -> None:
    with pytest.raises(CorruptSaveError):
        read_index(fragment_path, ContainerLimits(frame_decompressed_cap=100))


def test_total_cap_is_enforced(fragment_path: Path) -> None:
    with pytest.raises(CorruptSaveError):
        read_index(fragment_path, ContainerLimits(total_decompressed_cap=500))


def test_non_ascii_save_name(tmp_path: Path) -> None:
    fragment = build_container_fragment(save_name="Carrière Exemple 東京")
    assert (
        read_index(fragment.write(tmp_path / "fragment.bin")).save_name == "Carrière Exemple 東京"
    )


def header_pointing_at(trailer_offset: int) -> bytes:
    header = bytearray(build_container_fragment().content[:HEADER_SIZE])
    header[9:17] = (trailer_offset - 9).to_bytes(8, "little")
    return bytes(header)


def with_trailer_frame(trailer_frame: bytes) -> bytes:
    fragment = build_container_fragment()
    trailer_frame_at = fragment.trailer_offset + len(TRAILER_HEADER)
    return fragment.content[:trailer_frame_at] + trailer_frame


def trailer_payload_of(content: bytes, trailer_offset: int) -> bytes:
    return zstd.decompress(content[trailer_offset + len(TRAILER_HEADER) :])


def test_trailer_pointer_before_first_frame_is_corrupt(tmp_path: Path) -> None:
    content = bytearray(build_container_fragment().content)
    content[9:17] = (0).to_bytes(8, "little")
    with pytest.raises(CorruptSaveError, match="missing"):
        read_index(write_bytes(tmp_path, bytes(content)))


def test_oversized_directory_is_rejected_before_it_is_read(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.bin"
    with file_path.open("wb") as save_file:
        save_file.write(header_pointing_at(HEADER_SIZE))
        save_file.truncate(HEADER_SIZE + len(TRAILER_HEADER) + 64 * 1024**2 + 1)
    with pytest.raises(CorruptSaveError, match="implausibly large"):
        read_index(file_path)


def test_undecodable_directory_is_corrupt(tmp_path: Path) -> None:
    content = with_trailer_frame(b"these bytes are not a zstd frame")
    with pytest.raises(CorruptSaveError, match="could not be decompressed"):
        read_index(write_bytes(tmp_path, content))


def test_directory_decompressing_past_its_cap_is_corrupt(tmp_path: Path) -> None:
    content = with_trailer_frame(zstd.compress(bytes(64 * 1024**2 + 1)))
    with pytest.raises(CorruptSaveError, match="more than"):
        read_index(write_bytes(tmp_path, content))


def test_truncated_directory_frame_names_the_file_only(tmp_path: Path) -> None:
    fragment = build_container_fragment()
    trailer_frame = zstd.compress(trailer_payload_of(fragment.content, fragment.trailer_offset))
    file_path = tmp_path / "Private Folder Name" / "broken.bin"
    file_path.parent.mkdir()
    file_path.write_bytes(with_trailer_frame(trailer_frame[:-4]))
    with pytest.raises(CorruptSaveError, match="truncated") as error_info:
        read_index(file_path)
    assert "Private Folder Name" not in str(error_info.value)


def test_bytes_after_directory_frame_are_corrupt(tmp_path: Path) -> None:
    content = build_container_fragment().content + b"extra"
    with pytest.raises(CorruptSaveError, match="after its frame"):
        read_index(write_bytes(tmp_path, content))


def test_zero_compressed_size_is_corrupt(tmp_path: Path) -> None:
    fragment = build_container_fragment(declared_sizes={"humans.dat": (0, 40)})
    with pytest.raises(CorruptSaveError, match="outside the frame area"):
        read_index(fragment.write(tmp_path / "fragment.bin"))


def test_entry_overlapping_the_next_frame_inside_the_frame_area_is_corrupt(
    tmp_path: Path,
) -> None:
    frame_offsets = build_container_fragment().frame_offsets
    overlapping_size = frame_offsets["memory_pools.dat"] - frame_offsets["game_info.dat"] + 1
    fragment = build_container_fragment(declared_sizes={"game_info.dat": (overlapping_size, 300)})
    assert frame_offsets["game_info.dat"] + overlapping_size <= fragment.trailer_offset
    with pytest.raises(CorruptSaveError, match="outside the frame area"):
        read_index(fragment.write(tmp_path / "fragment.bin"))


def test_gap_before_the_trailer_is_named_after_the_attachment(tmp_path: Path) -> None:
    fragment = build_container_fragment(declared_sizes={"1_2_3.apm": (1, 10)})
    container_index = read_index(fragment.write(tmp_path / "fragment.bin"))
    attachment_offset = fragment.frame_offsets["1_2_3.apm"]
    trailing_region = container_index.regions["unlisted_after_1_2_3.apm"]
    assert trailing_region.entry is None
    assert (trailing_region.start, trailing_region.end) == (
        attachment_offset + 1,
        fragment.trailer_offset,
    )
    assert "1_2_3" not in container_index.regions


def test_region_name_clash_is_corrupt(tmp_path: Path) -> None:
    sections = default_sections()[:5] + [
        SectionFrame(
            "humans",
            section_body(".dat", 21, bytes(32)),
            unlisted_frames_after=(skippable_frame(b"gap"),),
        ),
        SectionFrame("unlisted_after_humans", section_body(".dat", 3, bytes(8))),
    ]
    with pytest.raises(CorruptSaveError, match="appears twice"):
        read_index(build_container_fragment(sections).write(tmp_path / "fragment.bin"))


def directory_entry_bytes(
    name: bytes,
    extension: bytes,
    *,
    extension_length: int = 4,
    tail_length: int = 40,
) -> bytes:
    """An entry whose frame sits at the first frame's offset, so parsing it always fails."""
    tail = struct.pack("<5Q", 0, 64, 300, 0, 0)[:tail_length]
    return (
        struct.pack("<I", len(name)) + name + struct.pack("<I", extension_length) + extension + tail
    )


def with_directory_extended_by(extra_bytes: bytes) -> bytes:
    fragment = build_container_fragment()
    trailer_frame_at = fragment.trailer_offset + len(TRAILER_HEADER)
    payload = trailer_payload_of(fragment.content, fragment.trailer_offset)
    closing_padding = bytes(16)
    assert payload.endswith(closing_padding)
    directory = payload.removesuffix(closing_padding)
    return fragment.content[:trailer_frame_at] + zstd.compress(directory + extra_bytes)


@pytest.mark.parametrize("name", [b"extra", b"a" * 256], ids=["short-name", "256-byte-name"])
def test_well_formed_extra_entry_is_parsed(tmp_path: Path, name: bytes) -> None:
    content = with_directory_extended_by(directory_entry_bytes(name, b".dat"))
    with pytest.raises(CorruptSaveError, match="outside the frame area"):
        read_index(write_bytes(tmp_path, content))


WELL_FORMED_EXTRA_ENTRY = directory_entry_bytes(b"extra", b".dat")


@pytest.mark.parametrize(
    "extra_bytes",
    [
        pytest.param(
            directory_entry_bytes(b"", b".dat") + WELL_FORMED_EXTRA_ENTRY, id="empty-name"
        ),
        pytest.param(
            directory_entry_bytes(b"a" * 257, b".dat") + WELL_FORMED_EXTRA_ENTRY, id="long-name"
        ),
        pytest.param(
            directory_entry_bytes(b"bad-name", b".dat") + WELL_FORMED_EXTRA_ENTRY, id="name-chars"
        ),
        pytest.param(
            directory_entry_bytes(b"extra", b".dat", extension_length=5) + WELL_FORMED_EXTRA_ENTRY,
            id="extension-length",
        ),
        pytest.param(
            directory_entry_bytes(b"extra", b"xdat") + WELL_FORMED_EXTRA_ENTRY, id="extension-dot"
        ),
        pytest.param(
            directory_entry_bytes(b"extra", b".d-t") + WELL_FORMED_EXTRA_ENTRY,
            id="extension-chars",
        ),
        pytest.param(directory_entry_bytes(b"extra", b".dat", tail_length=39), id="short-tail"),
        pytest.param(b"\x05\x00\x00", id="short-length"),
    ],
)
def test_entry_parsing_stops_at_the_first_malformed_entry(
    tmp_path: Path, extra_bytes: bytes
) -> None:
    container_index = read_index(write_bytes(tmp_path, with_directory_extended_by(extra_bytes)))
    assert set(container_index.sections) == EXPECTED_SECTIONS
    assert len(container_index.entries) == len(EXPECTED_SECTIONS) + 1


def test_read_exact_reports_a_short_read() -> None:
    with pytest.raises(CorruptSaveError, match="fragment.bin ended early") as error_info:
        read_exact(io.BytesIO(b"abc"), 1, 5, "fragment.bin")
    assert "try again" in str(error_info.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [(bytes(11), "more than 10 bytes"), (bytes(9), "expected 10")],
    ids=["too-long", "too-short"],
)
def test_decompress_frame_checks_the_expected_size(payload: bytes, message: str) -> None:
    with pytest.raises(CorruptSaveError, match=message):
        decompress_frame(
            zstd.compress(payload),
            expected_size=10,
            cap=1024,
            what="a frame",
            file_name="fragment.bin",
        )
