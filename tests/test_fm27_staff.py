from __future__ import annotations

import struct
from dataclasses import astuple, replace

import pytest

from fmsave._reader_stats import ClubStats
from fmsave.readers.clubs import ClubIndex, ClubRecordSpan
from fmsave.readers.staff import read_staff_lists
from tests.test_staff import STAFF_LAYOUT, empty_player_records

CLUB_UID = 4_001


def staff_lists_bytes(lists: tuple[tuple[int, ...], ...], width: int) -> bytes:
    # The affiliate-team count remains one byte even when staff counts widen.
    output = bytearray(b"\x01" + struct.pack("<I", 70_001))
    for values in lists:
        output.extend(len(values).to_bytes(width, "little"))
        output.extend(struct.pack(f"<{len(values)}I", *values))
    return bytes(output)


def club_index(game_db: bytes, *, record_end: int | None = None) -> ClubIndex:
    return ClubIndex(
        clubs=(),
        uid_by_club_index={},
        club_by_uid={},
        team_to_club={},
        affiliate_team_to_club={},
        stats=ClubStats(0, 0, 0, 0, 0, 0, 0, 0, None),
        game_db_bytes=len(game_db),
        record_spans=(
            ClubRecordSpan(CLUB_UID, 0, len(game_db) if record_end is None else record_end, 0),
        ),
    )


def test_u16_staff_count_reads_more_than_255_members_and_keeps_affiliate_count_u8() -> None:
    game_db = staff_lists_bytes((tuple(range(11, 311)), (401,), ()), 2)

    pairs, lists, counts = read_staff_lists(
        game_db,
        club_index(game_db),
        empty_player_records(),
        replace(STAFF_LAYOUT, list_count_bytes=2),
    )

    assert lists[CLUB_UID] == (tuple(range(10, 310)), (400,), ())
    assert len(pairs) == 301
    assert pairs[(CLUB_UID, 309)] == (0,)
    assert pairs[(CLUB_UID, 400)] == (1,)
    assert counts.clubs_checked == counts.clubs_lists_fit == 1
    assert counts.list_values == 301


@pytest.mark.parametrize("width", [1, 2])
def test_staff_count_width_preserves_ordinary_lists(width: int) -> None:
    game_db = staff_lists_bytes(((11, 21), (31,), ()), width)

    pairs, lists, counts = read_staff_lists(
        game_db,
        club_index(game_db),
        empty_player_records(),
        replace(STAFF_LAYOUT, list_count_bytes=width),
    )

    assert lists == {CLUB_UID: ((10, 20), (30,), ())}
    assert pairs == {(CLUB_UID, 10): (0,), (CLUB_UID, 20): (0,), (CLUB_UID, 30): (1,)}
    assert counts.clubs_lists_fit == 1
    assert counts.list_values == 3


@pytest.mark.parametrize("width", [-1, 0, 3])
def test_staff_list_count_rejects_unsupported_width(width: int) -> None:
    game_db = staff_lists_bytes(((), (), ()), 1)

    with pytest.raises(ValueError, match="list_count_bytes"):
        read_staff_lists(
            game_db,
            club_index(game_db),
            empty_player_records(),
            replace(STAFF_LAYOUT, list_count_bytes=width),
        )


@pytest.mark.parametrize("last_count_bytes", [b"", b"\x01"])
def test_u16_staff_count_truncation_omits_the_club(last_count_bytes: bytes) -> None:
    game_db = staff_lists_bytes(((11,), ()), 2) + last_count_bytes

    pairs, lists, counts = read_staff_lists(
        game_db,
        club_index(game_db),
        empty_player_records(),
        replace(STAFF_LAYOUT, list_count_bytes=2),
    )

    assert pairs == lists == {}
    assert counts.clubs_checked == 1
    assert counts.clubs_lists_fit == 0
    assert counts.list_values == 0


@pytest.mark.parametrize("record_end", [6, 7, 8])
def test_u16_staff_count_does_not_consume_bytes_from_the_next_record(record_end: int) -> None:
    game_db = staff_lists_bytes(((11,), (), ()), 2)

    pairs, lists, counts = read_staff_lists(
        game_db,
        club_index(game_db, record_end=record_end),
        empty_player_records(),
        replace(STAFF_LAYOUT, list_count_bytes=2),
    )

    assert pairs == lists == {}
    assert counts.clubs_lists_fit == 0
    assert counts.list_values == 0


def test_u16_staff_count_cannot_overrun_the_section_when_span_extends_beyond_it() -> None:
    game_db = staff_lists_bytes(((11, 21), (), ()), 2)[:-1]

    pairs, lists, counts = read_staff_lists(
        game_db,
        club_index(game_db, record_end=len(game_db) + 100),
        empty_player_records(),
        replace(STAFF_LAYOUT, list_count_bytes=2),
    )

    assert pairs == lists == {}
    assert counts.clubs_lists_fit == 0


def test_exact_fm27_staff_registration_uses_two_byte_list_counts() -> None:
    from fmsave._layouts import StaffLayout, find_layout

    layout = find_layout(StaffLayout, "game_db", 4000, "27.0.0+2486695").layout
    assert layout.list_count_bytes == 2
    assert layout.human_personality_floor == 0
    assert STAFF_LAYOUT.human_personality_floor == 0


def person_block(legal_name: str, personality: tuple[int, ...] = (10,) * 8) -> bytes:
    from tests.fixtures.container import packed_date
    from tests.fixtures.game_db import person_block_bytes

    return person_block_bytes(
        first_name_id=0,
        surname_id=0,
        common_name_id=0xFFFFFFFF,
        legal_name=legal_name,
        birth=packed_date(60, 2004),
        nation_id=44,
        personality=personality,
        trait_bits=0,
        relations=(),
    )


def own_contract() -> bytes:
    from tests.fixtures.career import NORTHBRIDGE_TEAM_A
    from tests.fixtures.container import packed_date
    from tests.fixtures.game_db import contract_bytes

    record, _tag_offset = contract_bytes(
        selector=19,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1_000,
        start=packed_date(1, 2029),
        tail={"end": packed_date(1, 2032), "status": 0},
        head={"type": 1},
    )
    return record


def unique_staff_rows(
    extra_staff: bytes,
    *,
    human_selector: int | None = None,
    human_personality_floor: int | None = None,
    require_unique_candidate: bool = True,
    fm27_jobs: bool = False,
):
    rows, _stats = unique_staff_read(
        extra_staff,
        human_selector=human_selector,
        human_personality_floor=human_personality_floor,
        require_unique_candidate=require_unique_candidate,
        fm27_jobs=fm27_jobs,
    )
    return rows


def unique_staff_read(
    extra_staff: bytes,
    *,
    human_selector: int | None = None,
    human_personality_floor: int | None = None,
    require_unique_candidate: bool = True,
    fm27_jobs: bool = False,
):
    from datetime import date

    from fmsave.readers.clubs import read_club_index
    from fmsave.readers.names import locate_name_pools
    from fmsave.readers.player_scan import locate_player_records
    from fmsave.readers.staff import read_staff
    from tests.fixtures.career import career_game_db
    from tests.fixtures.game_db import humans_body
    from tests.test_persons import registered_name_pool_layout
    from tests.test_staff import CLUB_LAYOUTS, PLAYER_LAYOUT, STAFF_LAYOUTS

    db = career_game_db(extra_staff=extra_staff)
    clubs = read_club_index(db, CLUB_LAYOUTS, "career example.fm")
    pools = locate_name_pools(db, registered_name_pool_layout(), "career example.fm")
    players = locate_player_records(db, pools.end_offset, PLAYER_LAYOUT, "career example.fm")
    layouts = replace(
        STAFF_LAYOUTS,
        staff=replace(
            STAFF_LAYOUTS.staff,
            human_personality_floor=human_personality_floor,
            **(FM27_JOB_VALUES if fm27_jobs else {}),  # pyright: ignore[reportArgumentType]
        ),
        person_blocks=replace(
            STAFF_LAYOUTS.person_blocks, require_unique_candidate=require_unique_candidate
        ),
    )
    rows, _lists, stats = read_staff(
        db,
        humans_body(count=int(human_selector is not None), selector=human_selector or 0),
        clubs,
        players,
        pools,
        date(2030, 7, 1),
        layouts,
        "career example.fm",
    )
    return rows, stats


def test_valid_unlisted_closing_header_keeps_neighbor_person_block_outside_staff_window() -> None:
    from tests.fixtures.staff import staff_object_bytes

    own = staff_object_bytes(
        person_id=18,
        uid=810_018,
        contract=own_contract(),
        person_block=person_block("Own Example"),
    )
    unlisted = staff_object_bytes(
        person_id=19,
        uid=810_019,
        person_block=person_block("Neighbor Example"),
    )

    rows = unique_staff_rows(own + unlisted)
    staff = next(row for row in rows if row.uid == 810_018)

    assert staff.legal_name == "Own Example"
    assert staff.unique_id == 810_019
    assert not any(row.uid == 810_019 for row in rows)


@pytest.mark.parametrize("bad_header", ["wrong_person", "nonmonotonic_uid", "ambiguous"])
def test_unsound_closing_header_does_not_invent_a_staff_person_boundary(bad_header: str) -> None:
    from tests.fixtures.staff import staff_object_bytes

    own = staff_object_bytes(
        person_id=18,
        uid=810_018,
        contract=own_contract(),
        person_block=person_block("Own Example"),
    )
    unlisted = staff_object_bytes(
        person_id=20 if bad_header == "wrong_person" else 19,
        uid=810_017 if bad_header == "nonmonotonic_uid" else 810_019,
        person_block=person_block("Neighbor Example"),
    )
    if bad_header == "ambiguous":
        unlisted += struct.pack("<III", 19, 810_020, 810_020)

    rows = unique_staff_rows(own + unlisted)
    staff = next(row for row in rows if row.uid == 810_018)

    assert staff.name is None
    assert staff.legal_name is None
    assert staff.unique_id is None


def test_human_contract_after_validated_object_end_is_not_owned_by_the_manager() -> None:
    from tests.fixtures.staff import staff_object_bytes

    human = staff_object_bytes(person_id=18, uid=810_018, kind=9)
    unlisted = staff_object_bytes(
        person_id=19,
        uid=810_019,
        contract=own_contract(),
        person_block=person_block("Neighbor Example"),
    )

    rows = unique_staff_rows(human + unlisted, human_selector=19)

    assert not any(row.uid == 810_018 for row in rows)
    assert not any(row.is_human_manager for row in rows)


# A new manager's profile stores a zero in one personality slot, below the range the ordinary
# search for a name block accepts.
ZERO_SLOT_PERSONALITY = (12, 10, 10, 10, 10, 10, 10, 0)


def manager_and_neighbor(*, kind: int = 9, personality: tuple[int, ...] = ZERO_SLOT_PERSONALITY):
    from tests.fixtures.staff import staff_object_bytes

    own = staff_object_bytes(
        person_id=18,
        uid=810_018,
        kind=kind,
        contract=own_contract(),
        person_block=person_block("Manager Example", personality),
    )
    neighbor = staff_object_bytes(
        person_id=19,
        uid=810_019,
        person_block=person_block("Neighbor Example"),
    )
    return own + neighbor


def test_human_manager_with_a_zero_personality_byte_is_named_under_the_floor() -> None:
    rows = unique_staff_rows(manager_and_neighbor(), human_selector=19, human_personality_floor=0)
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.uid == 810_018
    assert manager.legal_name == "Manager Example"
    assert manager.personality is not None
    assert astuple(manager.personality) == ZERO_SLOT_PERSONALITY
    assert manager.unique_id == 810_019


def test_human_manager_with_a_zero_personality_byte_stays_unnamed_without_the_floor() -> None:
    rows = unique_staff_rows(manager_and_neighbor(), human_selector=19)
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.legal_name is None
    assert manager.personality is None


def test_the_floor_leaves_staff_who_are_not_the_human_manager_alone() -> None:
    rows = unique_staff_rows(manager_and_neighbor(kind=1), human_personality_floor=0)
    staff = next(row for row in rows if row.uid == 810_018)

    assert staff.is_human_manager is False
    assert staff.legal_name is None


def test_the_floor_is_not_used_when_the_ordinary_search_finds_the_manager() -> None:
    rows = unique_staff_rows(
        manager_and_neighbor(personality=(10,) * 8), human_selector=19, human_personality_floor=0
    )
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.legal_name == "Manager Example"


# FM26 layouts accept the first block a window holds rather than a unique one, so the human's
# window has to end at his closing header or a neighbour's block is read as his.
@pytest.mark.parametrize(
    ("floor", "expected"), [(None, "Neighbor Example"), (0, "Manager Example")]
)
def test_fm26_human_window_ends_at_his_closing_header_under_the_floor(
    floor: int | None, expected: str
) -> None:
    rows = unique_staff_rows(
        manager_and_neighbor(),
        human_selector=19,
        human_personality_floor=floor,
        require_unique_candidate=False,
    )
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.legal_name == expected


def test_fm26_floor_leaves_a_human_whose_block_reads_normally_alone() -> None:
    rows = unique_staff_rows(
        manager_and_neighbor(personality=(10,) * 8),
        human_selector=19,
        human_personality_floor=0,
        require_unique_candidate=False,
    )
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.legal_name == "Manager Example"
    assert manager.personality is not None
    assert manager.personality.controversy == 10


def test_fm26_floor_does_not_change_the_window_of_staff_who_are_not_the_human() -> None:
    # The fix is scoped to the human manager: another person's window, and the first block in
    # it, are what they were without the floor.
    with_floor, without_floor = (
        next(
            row
            for row in unique_staff_rows(
                manager_and_neighbor(kind=1),
                human_personality_floor=floor,
                require_unique_candidate=False,
            )
            if row.uid == 810_018
        )
        for floor in (0, None)
    )

    assert with_floor == without_floor


@pytest.mark.parametrize(("floor", "has_row"), [(None, True), (0, False)])
def test_fm26_human_contract_past_his_closing_header_is_not_his_under_the_floor(
    floor: int | None, has_row: bool
) -> None:
    # His records and his name-block window end at the same closing header, so a record with
    # his selector inside the next object is never read as his contract.
    from tests.fixtures.staff import staff_object_bytes

    human = staff_object_bytes(person_id=18, uid=810_018, kind=9)
    neighbor = staff_object_bytes(
        person_id=19,
        uid=810_019,
        contract=own_contract(),
        person_block=person_block("Neighbor Example"),
    )

    rows = unique_staff_rows(
        human + neighbor,
        human_selector=19,
        human_personality_floor=floor,
        require_unique_candidate=False,
    )

    assert any(row.is_human_manager for row in rows) is has_row


# The job, offer and no-contract values the FM27 layout registers. The rest of the career
# fixture's layout stays FM26's, since its staff lists are written with one-byte counts.
FM27_JOB_VALUES: dict[str, object] = {
    "job_offset": 16,
    "offer_marker_offset": 19,
    "no_contract_selector_offset": 16,
    "no_contract_lead": b"\x05\x05",
}
# Where a contract record's job and the word after it sit, counted from its tag: the selector
# is five bytes past the tag.
JOB_FROM_TAG = 5 + 16
AFTER_JOB_FROM_TAG = 5 + 19
NOT_AN_OFFER = b"\xff\xff\xff\xff"


def test_fm27_registration_reads_jobs_offers_and_roles_with_no_contract() -> None:
    from fmsave._layouts import StaffLayout, find_layout

    layout = find_layout(StaffLayout, "game_db", 4000, "27.0.0+2486695").layout
    assert {name: getattr(layout, name) for name in FM27_JOB_VALUES} == FM27_JOB_VALUES
    assert STAFF_LAYOUT.job_offset is None
    assert STAFF_LAYOUT.offer_marker_offset is None
    assert STAFF_LAYOUT.no_contract_selector_offset is None


def job_contract(
    *,
    job: int,
    team_id: int | None = None,
    start_year: int = 2029,
    wage: int = 1_000,
    offer: bool = False,
) -> bytes:
    from tests.fixtures.career import NORTHBRIDGE_TEAM_A
    from tests.fixtures.container import packed_date
    from tests.fixtures.game_db import CONTRACT_TAG, contract_bytes

    record, tag_offset = contract_bytes(
        selector=19,
        team_id=NORTHBRIDGE_TEAM_A if team_id is None else team_id,
        wage=wage,
        start=packed_date(1, start_year),
        tail={"end": packed_date(1, 2032), "status": 0},
        head={"type": 1},
    )
    patched = bytearray(record)
    patched[tag_offset + JOB_FROM_TAG] = job
    after_job = tag_offset + AFTER_JOB_FROM_TAG
    patched[after_job : after_job + 4] = CONTRACT_TAG if offer else NOT_AN_OFFER
    return bytes(patched)


def no_contract_role(*, job: int, selector: int = 19) -> bytes:
    from tests.fixtures.career import NORTHBRIDGE_TEAM_A
    from tests.fixtures.container import packed_date
    from tests.fixtures.game_db import CONTRACT_TAG

    return (
        CONTRACT_TAG
        + packed_date(120, 2010)
        + b"\x0a\x00"
        + NOT_AN_OFFER
        + b"\x05\x05"
        + struct.pack("<II", selector, NORTHBRIDGE_TEAM_A)
        + bytes(8)
        + bytes((job, 0, 0))
        + NOT_AN_OFFER
    )


def person_with(record: bytes, name: str = "Role Example") -> bytes:
    from tests.fixtures.staff import staff_object_bytes

    return staff_object_bytes(
        person_id=18, uid=810_018, contract=record, person_block=person_block(name)
    ) + staff_object_bytes(person_id=19, uid=810_019, person_block=person_block("Neighbor"))


@pytest.mark.parametrize(("code", "label"), [(16, "MANAGER"), (88, "TECHNICAL_DIRECTOR")])
def test_a_contracted_persons_job_comes_from_his_contract_record(code: int, label: str) -> None:
    from fmsave import StaffJob

    rows = unique_staff_rows(person_with(job_contract(job=code)), fm27_jobs=True)
    row = next(row for row in rows if row.uid == 810_018)

    assert row.job is not None
    assert row.job.label is StaffJob[label]
    assert row.job.raw == code
    assert row.has_contract is True


def test_a_job_code_no_screen_has_labelled_keeps_its_raw_number() -> None:
    from fmsave import StaffJob

    rows = unique_staff_rows(person_with(job_contract(job=26)), fm27_jobs=True)
    row = next(row for row in rows if row.uid == 810_018)

    assert row.job is not None
    assert row.job.label is StaffJob.UNKNOWN
    assert row.job.raw == 26


def test_without_the_layout_values_no_job_is_read_and_an_offer_is_a_row() -> None:
    rows = unique_staff_rows(person_with(job_contract(job=16, offer=True)))
    row = next(row for row in rows if row.uid == 810_018)

    assert row.job is None
    assert row.has_contract is True


def test_an_offer_gives_no_row_and_is_counted() -> None:
    rows, stats = unique_staff_read(person_with(job_contract(job=16, offer=True)), fm27_jobs=True)

    assert not any(row.uid == 810_018 for row in rows)
    assert stats.offer_records == 1


def test_an_offer_from_another_club_leaves_the_job_he_holds() -> None:
    from tests.fixtures.career import NORTHBRIDGE_UID, SOUTHPORT_TEAM

    records = job_contract(job=2) + job_contract(
        job=16, team_id=SOUTHPORT_TEAM, start_year=2030, offer=True
    )
    rows = unique_staff_rows(person_with(records), fm27_jobs=True)
    own = [row for row in rows if row.uid == 810_018]

    assert [(row.club_uid, row.job and row.job.raw) for row in own] == [(NORTHBRIDGE_UID, 2)]


def test_an_offer_to_renew_does_not_replace_the_contract_he_is_on() -> None:
    from datetime import date

    records = job_contract(job=2, wage=900) + job_contract(
        job=2, start_year=2030, wage=1_500, offer=True
    )
    rows = unique_staff_rows(person_with(records), fm27_jobs=True)
    row = next(row for row in rows if row.uid == 810_018)

    assert row.wage == 900
    assert row.contract_start == date(2029, 1, 1)


def test_a_role_held_with_no_contract_is_a_row_with_its_team_and_job() -> None:
    from fmsave import StaffJob
    from tests.fixtures.career import NORTHBRIDGE_TEAM_A, NORTHBRIDGE_UID

    rows, stats = unique_staff_read(
        person_with(no_contract_role(job=4), "Chair Example"), fm27_jobs=True
    )
    row = next(row for row in rows if row.uid == 810_018)

    assert row.club_uid == NORTHBRIDGE_UID
    assert row.team_id == NORTHBRIDGE_TEAM_A
    assert row.team_slot == 0
    assert row.job is not None
    assert row.job.label is StaffJob.CHAIRPERSON
    assert row.has_contract is False
    assert row.wage is None
    assert row.contract_start is None
    assert row.in_club_lists is False
    assert row.legal_name == "Chair Example"
    assert stats.no_contract_roles == 1


def test_a_role_with_no_contract_is_not_read_without_the_layout_values() -> None:
    rows = unique_staff_rows(person_with(no_contract_role(job=4)))

    assert not any(row.uid == 810_018 for row in rows)


def test_a_role_with_a_player_selector_is_not_a_staff_row() -> None:
    from tests.fixtures.career import PLAYER_A_PINDEX

    rows, stats = unique_staff_read(
        person_with(no_contract_role(job=4, selector=PLAYER_A_PINDEX + 1)), fm27_jobs=True
    )

    assert not any(row.uid == 810_018 for row in rows)
    assert stats.no_contract_roles == 0


def test_an_affiliate_listing_of_a_role_with_no_contract_at_its_parent_is_one_row() -> None:
    from types import SimpleNamespace
    from typing import cast

    from fmsave.readers.staff import _merge_membership

    parent, side, person = 5_001, 5_009, 18
    clubs = cast(
        "ClubIndex",
        SimpleNamespace(
            clubs=(
                SimpleNamespace(uid=parent, parent_club_uid=None),
                SimpleNamespace(uid=side, parent_club_uid=parent),
            )
        ),
    )

    rows, counts = _merge_membership(
        {(side, person): (0,)}, {}, {person: 100}, clubs, {(parent, person): (0, 70_001, 6)}
    )

    assert rows == {(parent, person): (None, (0,), side)}
    assert counts.merged_affiliate_pairs == 1


def test_a_listed_person_with_a_role_at_the_same_club_is_one_row_with_the_roles_team() -> None:
    from types import SimpleNamespace
    from typing import cast

    from fmsave.readers.staff import _merge_membership, _row_roles
    from tests.test_staff import STAFF_LAYOUTS

    club, person, team, job = 5_001, 18, 70_001, 38
    clubs = cast(
        "ClubIndex", SimpleNamespace(clubs=(SimpleNamespace(uid=club, parent_club_uid=None),))
    )
    roles = {(club, person): (0, team, job)}

    rows, _counts = _merge_membership({(club, person): (1,)}, {}, {person: 100}, clubs, roles)

    assert rows == {(club, person): (None, (1,), club)}
    assert _row_roles(b"", rows, roles, STAFF_LAYOUTS) == {(club, person): (team, job)}


def test_the_human_managers_job_comes_from_his_own_contract() -> None:
    from fmsave import StaffJob
    from tests.fixtures.staff import staff_object_bytes

    human = staff_object_bytes(
        person_id=18,
        uid=810_018,
        kind=9,
        contract=job_contract(job=16),
        person_block=person_block("Manager Example"),
    )
    neighbor = staff_object_bytes(person_id=19, uid=810_019, person_block=person_block("Neighbor"))

    rows = unique_staff_rows(human + neighbor, human_selector=19, fm27_jobs=True)
    manager = next(row for row in rows if row.is_human_manager)

    assert manager.job is not None
    assert manager.job.label is StaffJob.MANAGER
