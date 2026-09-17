"""Reading the open vacancies out of the `job_centre` section.

The records are fixed size and back to back, so nothing is searched for: the count in the
header says how many there are and the walk reads them in order. What guards that walk is the
section's own size, because `records_offset + record_bytes * count` has to be the whole
section. That identity is the only check a start shifted by a whole record fails: every
per-record test then passes, on the next record's bytes.

Every field of a record comes from the layout, and the two dates are decoded with the scan's
own date reader, which masks the time-of-day bits these dates carry.
"""

from __future__ import annotations

import functools
import struct
from dataclasses import dataclass
from datetime import date

from fmsave._frozen import FrozenMapping
from fmsave._layouts import JobCentreLayout, find_layout
from fmsave._reader_stats import JobVacancyStats
from fmsave._scan import decode_date, decode_time_slot
from fmsave.models.jobs import JobVacancy
from fmsave.readers._common import (
    JOB_CENTRE_SECTION,
    MISSING_REFERENCE,
    build_gap_padded_struct,
    layout_mismatch,
)
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.competitions import CompetitionIndex

_UINT32 = struct.Struct("<I")
# What a record's team field holds when it names no team. No save measured stores either, but
# every other reader that ships a stored id reads them this way.
_NO_TEAM = frozenset({0, MISSING_REFERENCE})


@dataclass(frozen=True, slots=True)
class _RecordFields:
    """Everything one record read needs from a `JobCentreLayout`, derived once.

    `fields_struct` unpacks from the record start, and each `*_index` gives a value's place in
    the tuple it returns. The advertised date is in the struct only so that the build-time
    overlap check covers its four bytes; its value is read by `decode_date`, which masks the
    time-of-day bits. The second date is read from the struct as one little-endian int, because
    that is what it ships as: its meaning is unsettled, so it is not presented as a date.
    """

    fields_struct: struct.Struct
    team_id_index: int
    role_index: int
    date_12_index: int
    reserved_u16_index: int
    competition_index: int
    u20_index: int
    league_position_index: int
    reserved_u8_index: int
    flag_index: int


@functools.cache
def _record_fields(layout: JobCentreLayout) -> _RecordFields:
    """The layout's derived struct, built on first use for each layout.

    Raises:
        ValueError: The tag does not start the record, two fields overlap, or a field ends
            past the record's own last byte.
    """
    field_specs = [
        (layout.team_id_offset, "I", "team_id"),
        (layout.role_offset, "B", "role"),
        (layout.advertised_offset, "I", "advertised"),
        (layout.date_12_offset, "I", "date_12"),
        (layout.reserved_u16_offset, "H", "reserved_u16"),
        (layout.competition_offset, "H", "competition_id"),
        (layout.u20_offset, "H", "u20"),
        (layout.league_position_offset, "B", "league_position"),
        (layout.reserved_u8_offset, "B", "reserved_u8"),
        (layout.flag_offset, "B", "flag"),
    ]
    lowest_offset = min(offset for offset, _code, _name in field_specs)
    if lowest_offset < len(layout.tag):
        raise ValueError(
            f"the job record tag is {len(layout.tag)} bytes, so no field may start before "
            f"offset {len(layout.tag)}"
        )
    for offset, format_code, field_name in field_specs:
        if offset + struct.calcsize(format_code) > layout.record_bytes:
            raise ValueError(
                f"field {field_name!r} at offset {offset} ends past the {layout.record_bytes}-byte "
                "job record"
            )
    fields_struct, _start_offset, index_by_name = build_gap_padded_struct(
        field_specs, start_offset=0
    )
    return _RecordFields(
        fields_struct=fields_struct,
        team_id_index=index_by_name["team_id"],
        role_index=index_by_name["role"],
        date_12_index=index_by_name["date_12"],
        reserved_u16_index=index_by_name["reserved_u16"],
        competition_index=index_by_name["competition_id"],
        u20_index=index_by_name["u20"],
        league_position_index=index_by_name["league_position"],
        reserved_u8_index=index_by_name["reserved_u8"],
        flag_index=index_by_name["flag"],
    )


def find_job_centre_layout(schema: int | None, build: str) -> JobCentreLayout:
    """Look up the job-centre layout for a `job_centre` schema, falling back to the build."""
    return find_layout(JobCentreLayout, JOB_CENTRE_SECTION, schema, build).layout


def _record_count(job_centre: bytes, layout: JobCentreLayout, file_name: str) -> int:
    """The stored record count, once the section's size confirms it.

    Raises:
        ReaderCheckError: The section is too short to hold its header, or its size is not the
            header, the record size and the stored count together.
    """
    header_end = max(layout.count_offset + _UINT32.size, layout.records_offset)
    if header_end > len(job_centre):
        raise layout_mismatch(
            file_name,
            f"the section holds {len(job_centre)} bytes, too few for its {header_end}-byte header",
            section_name=JOB_CENTRE_SECTION,
        )
    (stored_count,) = _UINT32.unpack_from(job_centre, layout.count_offset)
    expected_bytes = layout.records_offset + layout.record_bytes * stored_count
    if expected_bytes != len(job_centre):
        raise layout_mismatch(
            file_name,
            f"the header claims {stored_count} records, which would make the section "
            f"{expected_bytes} bytes rather than {len(job_centre)}",
            section_name=JOB_CENTRE_SECTION,
        )
    return stored_count


def read_job_vacancies(
    job_centre: bytes,
    club_index: ClubIndex,
    competition_index: CompetitionIndex,
    clock: date,
    layout: JobCentreLayout,
    file_name: str,
) -> tuple[tuple[JobVacancy, ...], JobVacancyStats]:
    """One row per stored record, in stored order, with its club and competition joined.

    A record that fails one of the per-record checks is still returned: those checks judge the
    feed as a whole, so a single odd record is counted and reported rather than dropped, and
    what stops a wrong decode is the section's size identity and the shares those counts feed.

    The competition id is the record's own, so the competition index supplies a name and
    nothing else. The team id is looked up in the team-to-club map rather than the club index:
    a vacancy names a team, and the club is whichever one fields it. A stored 0 or the
    missing-reference word is no team at all and ships as None, as every other reader that
    hands out a stored id reads them.

    Raises:
        ReaderCheckError: The section is too short to hold its header, or its size is not the
            header, the record size and the stored count together.
    """
    stored_count = _record_count(job_centre, layout, file_name)
    fields = _record_fields(layout)
    unpack_from = fields.fields_struct.unpack_from
    tag = layout.tag
    tag_bytes = len(tag)
    club_for_team = club_index.team_to_club.get
    club_for_uid = club_index.club_by_uid.get
    competition_for = competition_index.competition_by_id.get
    vacancies: list[JobVacancy] = []
    tagged = 0
    dates_ordered = 0
    advertised_steps = 0
    advertised_ascending_steps = 0
    reserved_zero = 0
    competitions_known = 0
    teams_resolved = 0
    with_competition = 0
    with_league_position = 0
    flagged = 0
    previous_advertised: date | None = None
    for position in range(stored_count):
        record_offset = layout.records_offset + layout.record_bytes * position
        if job_centre[record_offset : record_offset + tag_bytes] == tag:
            tagged += 1
        field_values = unpack_from(job_centre, record_offset)
        advertised_offset = record_offset + layout.advertised_offset
        advertised_date = decode_date(job_centre, advertised_offset)
        advertised_slot = decode_time_slot(job_centre, advertised_offset)
        second_date = decode_date(job_centre, record_offset + layout.date_12_offset)
        if (
            advertised_date is not None
            and advertised_date <= clock
            and second_date is not None
            and second_date >= advertised_date
        ):
            dates_ordered += 1
        if advertised_date is not None:
            if previous_advertised is not None:
                advertised_steps += 1
                if advertised_date >= previous_advertised:
                    advertised_ascending_steps += 1
            previous_advertised = advertised_date
        if (
            field_values[fields.reserved_u16_index] == 0
            and field_values[fields.reserved_u8_index] == 0
        ):
            reserved_zero += 1

        stored_team_id: int = field_values[fields.team_id_index]
        team_id = None if stored_team_id in _NO_TEAM else stored_team_id
        team_club = None if team_id is None else club_for_team(team_id)
        if team_club is None:
            club_uid: int | None = None
            team_slot: int | None = None
            club_name: str | None = None
        else:
            club_uid, team_slot = team_club
            teams_resolved += 1
            club = club_for_uid(club_uid)
            club_name = None if club is None else club.name

        stored_competition_id: int = field_values[fields.competition_index]
        competition_id = (
            None if stored_competition_id == layout.no_competition else stored_competition_id
        )
        if competition_id is None or competition_id in competition_index.competition_by_id:
            competitions_known += 1
        if competition_id is not None:
            with_competition += 1
        competition = None if competition_id is None else competition_for(competition_id)
        competition_name = None if competition is None else competition.name

        stored_position: int = field_values[fields.league_position_index]
        league_position = stored_position or None
        if league_position is not None:
            with_league_position += 1
        flag: int = field_values[fields.flag_index]
        if flag:
            flagged += 1

        vacancies.append(
            JobVacancy(
                team_id=team_id,
                club_uid=club_uid,
                club_name=club_name,
                team_slot=team_slot,
                advertised_date=advertised_date,
                competition_id=competition_id,
                competition_name=competition_name,
                league_position=league_position,
                unknown=FrozenMapping(
                    {
                        "role": field_values[fields.role_index],
                        "advertised_slot": advertised_slot,
                        "date_12": field_values[fields.date_12_index],
                        "u20": field_values[fields.u20_index],
                        "b24": flag,
                    }
                ),
            )
        )
    stats = JobVacancyStats(
        records=stored_count,
        tagged=tagged,
        dates_ordered=dates_ordered,
        advertised_steps=advertised_steps,
        advertised_ascending_steps=advertised_ascending_steps,
        reserved_zero=reserved_zero,
        competitions_known=competitions_known,
        teams_resolved=teams_resolved,
        with_competition=with_competition,
        with_league_position=with_league_position,
        flagged=flagged,
    )
    return tuple(vacancies), stats
