from __future__ import annotations

import copy
import pickle
import struct
from dataclasses import dataclass
from pathlib import Path

import pytest

import fmsave
from fmsave import ManagedClub, Table
from fmsave._layouts import SummaryStringsLayout, find_layout
from fmsave._status import field_status
from fmsave.readers.managed import read_summary_strings
from fmsave.readers.players import PlayerDecoder
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    length_prefixed,
    packed_date,
    save_summary_body,
    section_body,
)
from tests.fixtures.game_db import (
    NORMAL_STATUS_KIND,
    STUB_STATUS_KIND,
    club_record_bytes,
    contract_bytes,
    game_db_body,
    humans_body,
    status_record_bytes,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000
SUMMARY_SCHEMA = 29
BUILD_STRING = "26.3.2+2329565"

MANAGER_NAME = "Alex Manager"
MANAGER_SELECTOR = 500
MANAGER_PERSON_UID = 777001
OTHER_PERSON_UID = 777002
UNREGISTERED_TEAM_ID = 79999

NORTHBRIDGE_UID = 5001
NORTHBRIDGE_TEAM_A = 70001
SOUTHPORT_UID = 5002
SOUTHPORT_TEAM = 70003
ATHLETIC_UID = 5004
ATHLETIC_TEAM = 70005


@dataclass(frozen=True)
class ExampleClub:
    club_index: int
    uid: int
    name: str
    short_name: str
    team_ids: tuple[int, ...]
    float_anchor_only: bool = False


EXAMPLE_CLUBS = (
    ExampleClub(1, NORTHBRIDGE_UID, "Northbridge FC", "Northbridge", (NORTHBRIDGE_TEAM_A, 70002)),
    ExampleClub(
        2,
        SOUTHPORT_UID,
        "Southport Example",
        "Southport",
        (SOUTHPORT_TEAM,),
        float_anchor_only=True,
    ),
    ExampleClub(4, ATHLETIC_UID, "Example Athletic", "Athletic", (70005, 70004, 70006)),
)


def club_region_bytes() -> bytes:
    club_records = [
        club_record_bytes(
            club_index=club.club_index,
            uid=club.uid,
            nation_id=3,
            fa_nation_id=3,
            city_id=77,
            name=club.name,
            short_name=club.short_name,
            team_ids=club.team_ids,
            float_anchor_only=club.float_anchor_only,
        )
        for club in EXAMPLE_CLUBS
    ]
    status_records = [
        status_record_bytes(
            ordinal=51 + position,
            club_index=club.club_index,
            uid=club.uid,
            kind=NORMAL_STATUS_KIND if position != 1 else STUB_STATUS_KIND,
            last_league_position=position + 1,
            reputation=5000 - position * 1000,
        )
        for position, club in enumerate(EXAMPLE_CLUBS)
    ]
    return game_db_body(club_records, status_records, gap_bytes=2000)


def person_header_bytes(person_id: int, uid: int) -> bytes:
    """A non-player person header: the person id, then the uid twice."""
    return struct.pack("<III", person_id, uid, uid)


def chain_record(*, selector: int, team_id: int, end: bytes | None) -> bytes:
    """A chain record; with `end`, it carries a parsed tail ending on that date."""
    tail = None if end is None else {"end": end, "status": 3}
    record, _tag_offset = contract_bytes(
        selector=selector,
        team_id=team_id,
        wage=4000,
        start=packed_date(183, 2029),
        tail=tail,
        head=None if end is None else {"type": 1},
    )
    return record


def null_end_chain_record(*, selector: int, team_id: int) -> bytes:
    """A chain record with a parsed tail whose end is the null date."""
    record, _tag_offset = contract_bytes(
        selector=selector,
        team_id=team_id,
        wage=4000,
        start=packed_date(183, 2029),
        tail={"end": None, "status": 3},
        head={"type": 1},
    )
    return record


# The fragment's in-game date is 2031-03-01 (day 60).
ENDED_BEFORE_CLOCK = packed_date(59, 2031)
ENDS_ON_CLOCK = packed_date(60, 2031)


def example_game_db(
    *,
    person_headers: tuple[bytes, ...] = (person_header_bytes(499, MANAGER_PERSON_UID),),
    chain_records: tuple[bytes, ...] = (
        chain_record(
            selector=MANAGER_SELECTOR, team_id=NORTHBRIDGE_TEAM_A, end=packed_date(182, 2032)
        ),
    ),
) -> bytes:
    payload = club_region_bytes() + bytes(64)
    for person_header in person_headers:
        payload += person_header + bytes(64)
    for record in chain_records:
        payload += record + bytes(64)
    return section_body(".dat", GAME_DB_SCHEMA, payload)


def linked_summary(short_name: str = "Northbridge", club_uid: int = NORTHBRIDGE_UID) -> bytes:
    return save_summary_body(
        leading_strings=("Example League",),
        trailing_strings=("Example Cup", MANAGER_NAME),
        club_uid_after=(short_name, club_uid),
    )


RIVAL_MANAGER_NAME = "Sam Rival"

# "Athletic" linked to its club after a rival manager, then "Northbridge" after the manager.
TWO_LINK_SUMMARY = section_body(
    ".dat",
    SUMMARY_SCHEMA,
    length_prefixed("Example League")
    + struct.pack("<I", 7)
    + length_prefixed(BUILD_STRING)
    + length_prefixed(RIVAL_MANAGER_NAME)
    + length_prefixed("Athletic")
    + struct.pack("<I", ATHLETIC_UID)
    + length_prefixed(MANAGER_NAME)
    + length_prefixed("Northbridge")
    + struct.pack("<I", NORTHBRIDGE_UID),
)

UNLINKED_SUMMARY = save_summary_body(
    leading_strings=("Example League",),
    trailing_strings=("Example Cup", MANAGER_NAME, "Northbridge"),
)


def write_fragment(
    tmp_path: Path,
    *,
    game_db: bytes | None = None,
    humans: bytes | None = None,
    summary: bytes | None = None,
) -> Path:
    replacements = {
        "game_db": example_game_db() if game_db is None else game_db,
        "humans": humans_body(count=1, selector=MANAGER_SELECTOR) if humans is None else humans,
        "save_game_summary": linked_summary() if summary is None else summary,
    }
    sections = [
        SectionFrame(
            section.name,
            replacements.get(section.name, section.body),
            section.extension,
            section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def read_managed_clubs(fragment_path: Path) -> Table[ManagedClub]:
    with fmsave.open(fragment_path) as career_save:
        return career_save.managed_clubs()


def registered_summary_strings_layout() -> SummaryStringsLayout:
    return find_layout(SummaryStringsLayout, "save_game_summary", SUMMARY_SCHEMA, "").layout


EXPECTED_ROW = ManagedClub(
    club_uid=NORTHBRIDGE_UID,
    club_name="Northbridge FC",
    club_short_name="Northbridge",
    manager_name=MANAGER_NAME,
    manager_staff_uid=MANAGER_PERSON_UID,
)


def test_managed_clubs_links_the_human_manager_to_the_club(tmp_path: Path) -> None:
    with fmsave.open(write_fragment(tmp_path)) as career_save:
        managed_clubs = career_save.managed_clubs()
        assert isinstance(managed_clubs, Table)
        assert managed_clubs.record_type is ManagedClub
        assert career_save.managed_clubs() is managed_clubs
        assert career_save._context._cache["table:managed_clubs"] is managed_clubs
    assert list(managed_clubs) == [EXPECTED_ROW]


def test_summary_strings_are_read_at_open_in_file_order(tmp_path: Path) -> None:
    with fmsave.open(write_fragment(tmp_path)) as career_save:
        summary_strings = career_save.info.summary_strings
    assert summary_strings == (
        "Example League",
        BUILD_STRING,
        "Example Cup",
        MANAGER_NAME,
        "Northbridge",
    )


def test_save_info_repr_hides_the_summary_strings(tmp_path: Path) -> None:
    with fmsave.open(write_fragment(tmp_path)) as career_save:
        save_info = career_save.info
    assert MANAGER_NAME in save_info.summary_strings
    description = repr(save_info)
    for summary_string in (*save_info.summary_strings, "Northbridge"):
        if summary_string != BUILD_STRING:
            assert summary_string not in description


def test_a_summary_link_to_a_different_club_raises_reader_check_error(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path, summary=linked_summary("Athletic", ATHLETIC_UID))
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        read_managed_clubs(fragment_path)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "Private Folder" not in message
    assert str(NORTHBRIDGE_UID) in message
    assert str(ATHLETIC_UID) in message
    for name_text in (MANAGER_NAME, "Athletic", "Northbridge"):
        assert name_text not in message


def test_route_one_alone_gives_a_row_without_a_manager_name(tmp_path: Path) -> None:
    managed_clubs = read_managed_clubs(write_fragment(tmp_path, summary=UNLINKED_SUMMARY))
    assert list(managed_clubs) == [
        ManagedClub(NORTHBRIDGE_UID, "Northbridge FC", "Northbridge", None, MANAGER_PERSON_UID)
    ]


def test_route_two_alone_gives_a_row_from_the_summary(tmp_path: Path) -> None:
    game_db = example_game_db(
        chain_records=(
            chain_record(selector=501, team_id=NORTHBRIDGE_TEAM_A, end=packed_date(182, 2032)),
        )
    )
    managed_clubs = read_managed_clubs(write_fragment(tmp_path, game_db=game_db))
    assert list(managed_clubs) == [EXPECTED_ROW]


def test_neither_route_resolving_gives_an_empty_table(tmp_path: Path) -> None:
    fragment_path = write_fragment(
        tmp_path, game_db=example_game_db(chain_records=()), summary=UNLINKED_SUMMARY
    )
    managed_clubs = read_managed_clubs(fragment_path)
    assert isinstance(managed_clubs, Table)
    assert managed_clubs.record_type is ManagedClub
    assert len(managed_clubs) == 0


def test_a_contract_that_ended_before_the_game_date_gives_an_empty_table(tmp_path: Path) -> None:
    game_db = example_game_db(
        chain_records=(
            chain_record(
                selector=MANAGER_SELECTOR, team_id=NORTHBRIDGE_TEAM_A, end=ENDED_BEFORE_CLOCK
            ),
        )
    )
    fragment_path = write_fragment(tmp_path, game_db=game_db, summary=UNLINKED_SUMMARY)
    assert len(read_managed_clubs(fragment_path)) == 0


@pytest.mark.parametrize(
    ("current_record", "current_club_uid"),
    [
        pytest.param(
            chain_record(selector=MANAGER_SELECTOR, team_id=SOUTHPORT_TEAM, end=None),
            SOUTHPORT_UID,
            id="current-record-without-a-tail",
        ),
        pytest.param(
            null_end_chain_record(selector=MANAGER_SELECTOR, team_id=SOUTHPORT_TEAM),
            SOUTHPORT_UID,
            id="current-record-with-a-null-end",
        ),
        pytest.param(
            chain_record(selector=MANAGER_SELECTOR, team_id=SOUTHPORT_TEAM, end=ENDS_ON_CLOCK),
            SOUTHPORT_UID,
            id="current-record-ending-on-the-game-date",
        ),
    ],
)
def test_an_ended_contract_loses_to_a_current_one(
    tmp_path: Path, current_record: bytes, current_club_uid: int
) -> None:
    game_db = example_game_db(
        chain_records=(
            chain_record(selector=MANAGER_SELECTOR, team_id=ATHLETIC_TEAM, end=ENDED_BEFORE_CLOCK),
            current_record,
        )
    )
    fragment_path = write_fragment(tmp_path, game_db=game_db, summary=UNLINKED_SUMMARY)
    assert [row.club_uid for row in read_managed_clubs(fragment_path)] == [current_club_uid]


def test_a_single_human_linked_to_another_club_as_well_raises(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path, summary=TWO_LINK_SUMMARY)
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        read_managed_clubs(fragment_path)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert str(NORTHBRIDGE_UID) in message
    assert str(ATHLETIC_UID) in message
    for name_text in (MANAGER_NAME, RIVAL_MANAGER_NAME, "Athletic", "Northbridge"):
        assert name_text not in message


def test_two_humans_pass_when_one_link_names_the_contract_club(tmp_path: Path) -> None:
    fragment_path = write_fragment(
        tmp_path,
        humans=humans_body(count=2, selector=MANAGER_SELECTOR),
        summary=TWO_LINK_SUMMARY,
    )
    assert list(read_managed_clubs(fragment_path)) == [EXPECTED_ROW]


def test_links_to_two_clubs_without_a_contract_raise(tmp_path: Path) -> None:
    fragment_path = write_fragment(
        tmp_path, game_db=example_game_db(chain_records=()), summary=TWO_LINK_SUMMARY
    )
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        read_managed_clubs(fragment_path)
    message = str(error_info.value)
    assert FILE_NAME in message
    assert "Private Folder" not in message
    for name_text in (MANAGER_NAME, RIVAL_MANAGER_NAME, "Athletic", "Northbridge"):
        assert name_text not in message


def test_selector_zero_leaves_the_summary_to_decide_alone(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path, humans=humans_body(count=1, selector=0))
    assert list(read_managed_clubs(fragment_path)) == [
        ManagedClub(NORTHBRIDGE_UID, "Northbridge FC", "Northbridge", MANAGER_NAME, None)
    ]


def test_no_human_managers_gives_an_empty_table(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path, humans=humans_body(count=0, selector=0))
    with fmsave.open(fragment_path) as career_save:
        managed_clubs = career_save.managed_clubs()
        assert career_save.managed_clubs() is managed_clubs
    assert isinstance(managed_clubs, Table)
    assert managed_clubs.record_type is ManagedClub
    assert len(managed_clubs) == 0


def test_two_human_managers_list_only_the_first(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path, humans=humans_body(count=2, selector=MANAGER_SELECTOR))
    assert list(read_managed_clubs(fragment_path)) == [EXPECTED_ROW]


def test_two_person_header_candidates_leave_the_person_uid_unset(tmp_path: Path) -> None:
    game_db = example_game_db(
        person_headers=(
            person_header_bytes(499, MANAGER_PERSON_UID),
            person_header_bytes(499, OTHER_PERSON_UID),
        )
    )
    managed_clubs = read_managed_clubs(write_fragment(tmp_path, game_db=game_db))
    assert len(managed_clubs) == 1
    assert managed_clubs[0].manager_staff_uid is None
    assert managed_clubs[0].club_uid == NORTHBRIDGE_UID


@pytest.mark.parametrize(
    "rejected_header",
    [
        pytest.param(struct.pack("<III", 499, 777003, 777004), id="uids-differ"),
        pytest.param(struct.pack("<III", 499, 0, 0), id="zero-uid"),
        pytest.param(struct.pack("<III", 499, 0xFFFFFFFF, 0xFFFFFFFF), id="missing-uid"),
    ],
)
def test_a_person_header_counts_only_with_a_doubled_real_uid(
    tmp_path: Path, rejected_header: bytes
) -> None:
    game_db = example_game_db(
        person_headers=(rejected_header, person_header_bytes(499, MANAGER_PERSON_UID))
    )
    managed_clubs = read_managed_clubs(write_fragment(tmp_path, game_db=game_db))
    assert managed_clubs[0].manager_staff_uid == MANAGER_PERSON_UID


def test_route_one_prefers_a_tailed_record_then_the_latest_end(tmp_path: Path) -> None:
    game_db = example_game_db(
        chain_records=(
            chain_record(selector=MANAGER_SELECTOR, team_id=SOUTHPORT_TEAM, end=None),
            chain_record(
                selector=MANAGER_SELECTOR, team_id=ATHLETIC_TEAM, end=packed_date(182, 2031)
            ),
            chain_record(
                selector=MANAGER_SELECTOR, team_id=NORTHBRIDGE_TEAM_A, end=packed_date(182, 2032)
            ),
            chain_record(
                selector=MANAGER_SELECTOR, team_id=UNREGISTERED_TEAM_ID, end=packed_date(1, 2040)
            ),
        )
    )
    fragment_path = write_fragment(tmp_path, game_db=game_db, summary=UNLINKED_SUMMARY)
    managed_clubs = read_managed_clubs(fragment_path)
    assert [row.club_uid for row in managed_clubs] == [NORTHBRIDGE_UID]


def test_route_one_takes_a_tail_less_record_when_no_record_has_a_tail(tmp_path: Path) -> None:
    game_db = example_game_db(
        chain_records=(chain_record(selector=MANAGER_SELECTOR, team_id=SOUTHPORT_TEAM, end=None),)
    )
    fragment_path = write_fragment(tmp_path, game_db=game_db, summary=UNLINKED_SUMMARY)
    assert [row.club_uid for row in read_managed_clubs(fragment_path)] == [SOUTHPORT_UID]


def test_a_truncated_humans_section_raises_corrupt_save_error(tmp_path: Path) -> None:
    short_humans = section_body(".dat", 21, struct.pack("<H", 1) + b"\x01")
    fragment_path = write_fragment(tmp_path, humans=short_humans)
    with pytest.raises(fmsave.CorruptSaveError) as error_info:
        read_managed_clubs(fragment_path)
    message = str(error_info.value)
    assert f"{FILE_NAME}: section 'humans'" in message
    assert "Private Folder" not in message


def test_managed_clubs_does_not_decode_players(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_decode(self: PlayerDecoder, *args: object, **kwargs: object) -> object:
        raise AssertionError("managed_clubs() decoded a player")

    monkeypatch.setattr(PlayerDecoder, "decode", refuse_decode)
    with fmsave.open(write_fragment(tmp_path)) as career_save:
        managed_clubs = career_save.managed_clubs()
        cached_keys = set(career_save._context._cache)
    assert list(managed_clubs) == [EXPECTED_ROW]
    assert "table:players" not in cached_keys
    assert "table:contracts" not in cached_keys


def test_managed_clubs_raises_save_closed_error_after_close(tmp_path: Path) -> None:
    fragment_path = write_fragment(tmp_path)
    career_save = fmsave.open(fragment_path)
    managed_clubs = career_save.managed_clubs()
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.managed_clubs()
    assert list(managed_clubs) == [EXPECTED_ROW]

    never_read_save = fmsave.open(fragment_path)
    never_read_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        never_read_save.managed_clubs()


def test_managed_club_survives_pickle_and_deepcopy() -> None:
    for copied_row in (pickle.loads(pickle.dumps(EXPECTED_ROW)), copy.deepcopy(EXPECTED_ROW)):
        assert copied_row == EXPECTED_ROW
        assert type(copied_row) is ManagedClub
    table = Table((EXPECTED_ROW,), ManagedClub)
    assert pickle.loads(pickle.dumps(table)) == table
    assert copy.deepcopy(table) == table


def test_managed_club_fields_are_all_unconfirmed() -> None:
    for field_name in (
        "club_uid",
        "club_name",
        "club_short_name",
        "manager_name",
        "manager_staff_uid",
    ):
        assert field_status(ManagedClub, field_name) == "unconfirmed"
    assert field_status(fmsave.SaveInfo, "summary_strings") == "unconfirmed"


def test_managed_club_export_matches_json_normalize() -> None:
    rows = [
        EXPECTED_ROW,
        ManagedClub(SOUTHPORT_UID, "Southport Example", "Southport", None, None),
    ]
    assert_matches_json_normalize(rows, ManagedClub)


def summary_with_payload(payload: bytes) -> bytes:
    return section_body(".dat", SUMMARY_SCHEMA, payload)


def test_summary_scan_keeps_non_ascii_strings_and_the_length_bounds() -> None:
    payload = (
        length_prefixed("Łódź Example")
        + length_prefixed("ab")
        + length_prefixed("x" * 120)
        + length_prefixed(BUILD_STRING)
    )
    assert read_summary_strings(
        summary_with_payload(payload), registered_summary_strings_layout()
    ) == ("Łódź Example", "ab", "x" * 120, BUILD_STRING)


@pytest.mark.parametrize(
    "rejected_bytes",
    [
        pytest.param(struct.pack("<I", 1) + b"A", id="length-1"),
        pytest.param(struct.pack("<I", 121) + b"y" * 121, id="length-121"),
        pytest.param(length_prefixed("Bad\x07Name"), id="control-byte"),
        pytest.param(struct.pack("<I", 4) + b"\xff\xfe\xfd\xfc", id="invalid-utf-8"),
        pytest.param(struct.pack("<I", 40) + b"too short", id="runs-past-the-end"),
    ],
)
def test_summary_scan_skips_bytes_that_are_not_strings(rejected_bytes: bytes) -> None:
    payload = length_prefixed("Example League") + rejected_bytes
    assert read_summary_strings(
        summary_with_payload(payload), registered_summary_strings_layout()
    ) == ("Example League",)


def test_summary_scan_starts_after_the_header_and_resumes_after_each_string() -> None:
    # The header's schema word (29) followed by two zero bytes would read as a 29-byte string
    # of "w"; the scan starts after the 8-byte header, so it is not one. The last byte of "ab"
    # ("b" is 98) followed by three zero bytes would read as a 98-byte string of "z" that
    # overlaps "ab"; the scan resumes at the end of "ab", so it is not one either.
    payload = b"\x00\x00" + b"w" * 29 + length_prefixed("ab") + b"\x00\x00\x00" + b"z" * 98
    summary = summary_with_payload(payload)
    assert read_summary_strings(summary, registered_summary_strings_layout()) == ("ab",)
