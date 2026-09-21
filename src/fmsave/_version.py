"""Game and build detection, and the metadata returned as `Save.info`."""

from __future__ import annotations

import os
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import fmsave
from fmsave._container import (
    ContainerIndex,
    damaged_part_error,
    read_section,
    read_section_heads,
)
from fmsave._errors import (
    ISSUES_URL,
    CorruptSaveError,
    ReaderCheckError,
    UnknownBuildWarning,
    UnsupportedGameError,
)
from fmsave._frozen import FrozenMapping
from fmsave._layouts import (
    FALLBACK_BUILD,
    GameInfoLayout,
    SaveSummaryLayout,
    SummaryStringsLayout,
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
from fmsave.readers._common import SAVE_SUMMARY_SECTION
from fmsave.readers.managed import read_summary_strings

SUPPORTED_GAME_MAJOR = 26
SECTION_MAGIC_PREFIX = b"\x03\x01"
SECTION_HEAD_BYTES = 8
SCHEMA_OFFSET = 6
LENGTH_PREFIX_BYTES = 4
GAME_INFO_SECTION = "game_info"
VERSION_CANDIDATE_START = re.compile(rb"(?<![0-9.])[0-9]{1,3}\.")


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
    """The first string whose u32 length prefix spans exactly a full version match."""
    version_pattern = re.compile(layout.version_pattern.encode("ascii"))
    for candidate in VERSION_CANDIDATE_START.finditer(summary):
        version_start = candidate.start()
        if version_start < LENGTH_PREFIX_BYTES:
            continue
        version_length = read_u32(summary, version_start - LENGTH_PREFIX_BYTES)
        version_end = version_start + version_length
        if (
            version_length == 0
            or version_length > layout.max_version_bytes
            or version_end > len(summary)
        ):
            continue
        version_match = version_pattern.fullmatch(summary, version_start, version_end)
        if version_match is None:
            continue
        return GameVersion(
            major=int(version_match.group(1)),
            build=version_match.group(0).decode("ascii"),
            build_number=int(version_match.group(4)),
        )
    raise UnsupportedGameError(
        f"{file_name}: no game version found. fmsave reads Football Manager 26 saves; for other versions see {ISSUES_URL}"
    )


@dataclass(frozen=True, slots=True)
class SummaryFacts:
    version: GameVersion
    summary_strings: tuple[str, ...]
    game_date: date | None


def read_summary_date(
    summary: bytes, layout: SaveSummaryLayout, version: GameVersion
) -> date | None:
    """Read the structured summary clock, never a date-shaped byte scan.

    Schema 29 stores a setup string, build string, counted division names, an eight-byte
    manager header, manager and club names, club uid, then the date. A fresh career can have
    this date before `game_info` has a clock. Other summary shapes remain readable for their
    version and strings, but cannot supply a fallback date.
    """
    try:
        _, offset = read_length_prefixed_string(
            summary, layout.structured_strings_offset, layout.max_setup_string_bytes
        )
        stored_version, offset = read_length_prefixed_string(
            summary, offset, layout.max_version_bytes
        )
        if stored_version != version.build:
            return None
        division_count = read_u32(summary, offset)
        if division_count > layout.max_divisions:
            return None
        offset += LENGTH_PREFIX_BYTES
        for _ in range(division_count):
            _, offset = read_length_prefixed_string(summary, offset, layout.max_summary_name_bytes)
        _, offset = read_length_prefixed_string(
            summary, offset + layout.manager_header_bytes, layout.max_summary_name_bytes
        )
        _, offset = read_length_prefixed_string(summary, offset, layout.max_summary_name_bytes)
        return decode_date(summary, offset + layout.club_uid_bytes)
    except CorruptSaveError:
        return None


def read_summary_facts(container_index: ContainerIndex) -> SummaryFacts:
    """Read the summary's version, strings and fallback date once, rejecting games other than FM26."""
    file_name = container_index.file_name
    summary = read_section(container_index, SAVE_SUMMARY_SECTION)
    summary_schema = section_schema(
        summary,
        container_index.sections[SAVE_SUMMARY_SECTION].extension,
        SAVE_SUMMARY_SECTION,
        file_name,
    )
    summary_layout = find_layout(SaveSummaryLayout, SAVE_SUMMARY_SECTION, summary_schema, "").layout
    version = find_game_version(summary, summary_layout, file_name)
    if version.major != SUPPORTED_GAME_MAJOR:
        raise UnsupportedGameError(
            f"{file_name} is an {version.game} save ({version.build}). fmsave {__version__} reads FM26 saves "
            f"only; {version.game} is not supported yet. See {ISSUES_URL}"
        )
    strings_layout = find_layout(
        SummaryStringsLayout, SAVE_SUMMARY_SECTION, summary_schema, ""
    ).layout
    return SummaryFacts(
        version,
        read_summary_strings(summary, strings_layout),
        read_summary_date(summary, summary_layout, version),
    )


def decode_game_info(
    game_info: bytes, layout: GameInfoLayout, version: GameVersion, file_name: str
) -> GameInfoFacts:
    """Decode `game_info`; a read outside the section is reported with the file name."""
    try:
        return decode_game_info_fields(game_info, layout, version, file_name)
    except CorruptSaveError as error:
        raise damaged_part_error(file_name, GAME_INFO_SECTION, error) from error


def decode_game_info_fields(
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


def read_game_info_facts(
    container_index: ContainerIndex,
    section_schemas: Mapping[str, int],
    version: GameVersion,
    known_build: bool,
) -> GameInfoFacts:
    """Decode `game_info`; on a fallback layout, damage-shaped failures mean the layout does not fit."""
    file_name = container_index.file_name
    layout_match = find_layout(
        GameInfoLayout, GAME_INFO_SECTION, section_schemas.get(GAME_INFO_SECTION), version.build
    )
    game_info = read_section(container_index, GAME_INFO_SECTION)
    try:
        return decode_game_info(game_info, layout_match.layout, version, file_name)
    except CorruptSaveError as error:
        if known_build and layout_match.exact:
            raise
        raise ReaderCheckError(
            f"{file_name}: game_info does not fit the layout fmsave used for build {version.build}. "
            f"Please report it at {ISSUES_URL}"
        ) from error


def read_save_info(container_index: ContainerIndex) -> SaveInfo:
    """Detect the game and build and read save metadata. Warns on unknown FM26 builds."""
    file_name = container_index.file_name
    summary_facts = read_summary_facts(container_index)
    version = summary_facts.version
    known_build = version.build in known_builds()
    if not known_build:
        warnings.warn(
            UnknownBuildWarning(
                f"{file_name} was saved by FM26 build {version.build}, which fmsave {__version__} has no "
                f"layouts for. Using the {FALLBACK_BUILD} layouts; readers check their results and raise "
                "ReaderCheckError if they do not fit."
            ),
            skip_file_prefixes=(str(Path(fmsave.__file__).parent) + os.sep,),
        )
    section_names = list(container_index.sections)
    heads = read_section_heads(container_index, section_names, SECTION_HEAD_BYTES)
    section_schemas = {
        name: section_schema(heads[name], container_index.sections[name].extension, name, file_name)
        for name in section_names
    }
    facts = read_game_info_facts(container_index, section_schemas, version, known_build)
    sections = tuple(
        SectionInfo(
            name=entry.name,
            extension=entry.extension,
            file_offset=entry.frame_offset,
            compressed_size=entry.compressed_size,
            decompressed_size=entry.decompressed_size,
            schema=section_schemas[entry.name],
            unknown=FrozenMapping(
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
        game_date=facts.game_date if facts.game_date is not None else summary_facts.game_date,
        time_slot=facts.time_slot,
        save_name=container_index.save_name,
        sections=sections,
        summary_strings=summary_facts.summary_strings,
        section_schemas=FrozenMapping(section_schemas),
        file_name=file_name,
    )
