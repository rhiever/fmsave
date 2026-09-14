"""Game and build detection, and the metadata returned as `Save.info`."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from fmsave._container import ContainerIndex, read_section, read_section_heads
from fmsave._errors import (
    ISSUES_URL,
    CorruptSaveError,
    ReaderCheckError,
    UnknownBuildWarning,
    UnsupportedGameError,
)
from fmsave._layouts import (
    FALLBACK_BUILD,
    GameInfoLayout,
    SaveSummaryLayout,
    find_layout,
    known_builds,
)
from fmsave._package import __version__
from fmsave._scan import (
    decode_date,
    decode_time_slot,
    read_length_prefixed_string,
    read_u16,
    read_u32,
)
from fmsave.models.meta import SaveInfo, SectionInfo

SUPPORTED_GAME_MAJOR = 26
SECTION_MAGIC_PREFIX = b"\x03\x01"
SECTION_HEAD_BYTES = 8
SCHEMA_OFFSET = 6
GAME_INFO_SECTION = "game_info"
SAVE_SUMMARY_SECTION = "save_game_summary"


@dataclass(frozen=True, slots=True)
class GameVersion:
    major: int
    build: str
    build_number: int

    @property
    def game(self) -> str:
        return f"FM{self.major}"


@dataclass(frozen=True, slots=True)
class GameInfoFacts:
    db_version: str
    game_date: date | None
    time_slot: int


def section_schema(head: bytes, extension: str, section_name: str, file_name: str) -> int:
    expected_magic = SECTION_MAGIC_PREFIX + extension[::-1].encode("ascii")
    if len(head) < SECTION_HEAD_BYTES or head[: len(expected_magic)] != expected_magic:
        raise CorruptSaveError(
            f"{file_name}: section {section_name!r} does not start with a section signature"
        )
    return read_u16(head, SCHEMA_OFFSET)


def find_game_version(summary: bytes, layout: SaveSummaryLayout, file_name: str) -> GameVersion:
    version_pattern = re.compile(layout.version_pattern.encode("ascii"))
    for match in version_pattern.finditer(summary):
        version_text = match.group(0)
        if match.start() < 4 or len(version_text) > layout.max_version_bytes:
            continue
        if read_u32(summary, match.start() - 4) != len(version_text):
            continue
        return GameVersion(
            major=int(match.group(1)),
            build=version_text.decode("ascii"),
            build_number=int(match.group(4)),
        )
    raise UnsupportedGameError(
        f"{file_name}: no game version found. fmsave reads Football Manager 26 saves; for other versions see {ISSUES_URL}"
    )


def decode_game_info(
    game_info: bytes, layout: GameInfoLayout, version: GameVersion, file_name: str
) -> GameInfoFacts:
    db_version, version_end = read_length_prefixed_string(
        game_info, layout.db_version_length_offset, layout.max_db_version_bytes
    )
    stored_build_numbers = [
        read_u32(game_info, version_end + offset)
        for offset in layout.build_number_offsets_after_db_version
    ]
    if any(
        stored_build_number != version.build_number for stored_build_number in stored_build_numbers
    ):
        raise ReaderCheckError(
            f"{file_name}: game_info does not match build {version.build}, so the save layout differs "
            f"from what fmsave expects. Please report it at {ISSUES_URL}"
        )
    date_offset = version_end + layout.game_date_offset_after_db_version
    return GameInfoFacts(
        db_version=db_version,
        game_date=decode_date(game_info, date_offset),
        time_slot=decode_time_slot(game_info, date_offset),
    )


def read_save_info(container_index: ContainerIndex) -> SaveInfo:
    """Detect the game and build and read save metadata. Warns on unknown FM26 builds."""
    file_name = container_index.file_name
    section_names = list(container_index.sections)
    heads = read_section_heads(container_index, section_names, SECTION_HEAD_BYTES)
    section_schemas = {
        name: section_schema(heads[name], container_index.sections[name].extension, name, file_name)
        for name in section_names
    }
    summary_layout = find_layout(
        SaveSummaryLayout, SAVE_SUMMARY_SECTION, section_schemas.get(SAVE_SUMMARY_SECTION), ""
    ).layout
    version = find_game_version(
        read_section(container_index, SAVE_SUMMARY_SECTION), summary_layout, file_name
    )
    if version.major != SUPPORTED_GAME_MAJOR:
        raise UnsupportedGameError(
            f"{file_name} is an {version.game} save ({version.build}). fmsave {__version__} reads FM26 saves "
            f"only; {version.game} is not supported yet. See {ISSUES_URL}"
        )
    known_build = version.build in known_builds()
    if not known_build:
        warnings.warn(
            UnknownBuildWarning(
                f"{file_name} was saved by FM26 build {version.build}, which fmsave {__version__} has no "
                f"layouts for. Using the {FALLBACK_BUILD} layouts; readers check their results and raise "
                "ReaderCheckError if they do not fit."
            ),
            stacklevel=3,
        )
    game_info_layout = find_layout(
        GameInfoLayout, GAME_INFO_SECTION, section_schemas.get(GAME_INFO_SECTION), version.build
    ).layout
    facts = decode_game_info(
        read_section(container_index, GAME_INFO_SECTION), game_info_layout, version, file_name
    )
    sections = tuple(
        SectionInfo(
            name=entry.name,
            extension=entry.extension,
            file_offset=entry.frame_offset,
            compressed_size=entry.compressed_size,
            decompressed_size=entry.decompressed_size,
            schema=section_schemas[entry.name],
            unknown=MappingProxyType(
                {"tail0": entry.trailing_values[0], "tail1": entry.trailing_values[1]}
            ),
        )
        for entry in container_index.sections.values()
    )
    return SaveInfo(
        game=version.game,
        build=version.build,
        build_number=version.build_number,
        known_build=known_build,
        db_version=facts.db_version,
        game_date=facts.game_date,
        time_slot=facts.time_slot,
        save_name=container_index.save_name,
        sections=sections,
        section_schemas=MappingProxyType(dict(section_schemas)),
        file_name=file_name,
    )
