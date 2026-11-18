"""Synthetic staff search coverage at the public and binary reader boundaries."""

from __future__ import annotations

import struct
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import StaffLayout
from fmsave._layouts import fm27_27_0_0 as fm27
from fmsave.readers.staff import _read_ability_block
from tests.fixtures.career import (
    MISSING_NAME_ID,
    NORTHBRIDGE_TEAM_A,
    SOUTHPORT_TEAM,
    STAFF_CONTRACTED_UID,
    STAFF_LISTED_ONLY_PERSON_ID,
    STAFF_LISTED_ONLY_UID,
    career_fragment,
)
from tests.fixtures.container import packed_date
from tests.fixtures.game_db import contract_bytes, person_block_bytes
from tests.fixtures.staff import staff_object_bytes
from tests.test_staff import STAFF_LAYOUT

INDEPENDENT_ID = 26
INDEPENDENT_UID = 730_026


def _profile() -> bytes:
    return person_block_bytes(
        first_name_id=1,
        surname_id=1,
        common_name_id=MISSING_NAME_ID,
        legal_name=None,
        birth=packed_date(100, 1988),
        nation_id=44,
        personality=(9,) * 8,
        trait_bits=0,
        relations=(),
    )


def _contract(team_id: int, *, start_year: int = 2030, end_year: int = 2032) -> bytes:
    return contract_bytes(
        selector=INDEPENDENT_ID + 1,
        team_id=team_id,
        wage=1_300,
        start=packed_date(1, start_year),
        tail={"end": packed_date(1, end_year)},
    )[0]


def _independent(*, contract: bytes = b"", uid: int = INDEPENDENT_UID) -> bytes:
    return staff_object_bytes(
        person_id=INDEPENDENT_ID,
        uid=uid,
        entries=((900, 1000), (800, 1100)),
        contract=contract,
        person_block=_profile(),
    )


def _close_independent() -> bytes:
    return struct.pack("<III", INDEPENDENT_ID + 1, 730_027, 730_027) + bytes(32)


def test_independent_staff_profile_is_cached_and_stays_outside_legacy_tables(
    tmp_path: Path,
) -> None:
    path = career_fragment(extra_staff=_independent() + _close_independent()).write(
        tmp_path / "career.bin"
    )
    with fmsave.open(path) as save:
        legacy = save.staff()
        lists = save.staff_lists()
        candidates = save.staff_candidates()

        assert save.staff_candidates() is candidates
        assert save.staff() is legacy
        assert save.staff_lists() is lists
        assert INDEPENDENT_UID not in {staff.uid for staff in legacy}
        assert INDEPENDENT_UID not in {uid for row in lists for uid in row.staff_uids}

    candidate = next(row for row in candidates if row.uid == INDEPENDENT_UID)
    assert candidate.name == "Sam Sample"
    assert candidate.birth_date == date(1988, 4, 9)
    assert candidate.employment == "unknown"
    assert candidate.appointments == ()
    assert next(row for row in candidates if row.uid == STAFF_LISTED_ONLY_UID).employment == (
        "unknown"
    )
    assert next(row for row in candidates if row.uid == STAFF_CONTRACTED_UID).employment == (
        "employed"
    )
    with pytest.raises(fmsave.SaveClosedError):
        save.staff_candidates()


def test_each_current_club_appointment_is_retained_on_one_candidate(tmp_path: Path) -> None:
    person = _independent(contract=_contract(NORTHBRIDGE_TEAM_A) + _contract(SOUTHPORT_TEAM))
    path = career_fragment(extra_staff=person + _close_independent()).write(tmp_path / "career.bin")

    with fmsave.open(path) as save:
        candidates = [row for row in save.staff_candidates() if row.uid == INDEPENDENT_UID]

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.employment == "employed"
    assert [role.club_name for role in candidate.appointments] == [
        "Northbridge FC",
        "Southport Example",
    ]
    assert [role.team_id for role in candidate.appointments] == [NORTHBRIDGE_TEAM_A, SOUTHPORT_TEAM]
    assert all(role.has_contract and role.wage == 1_300 for role in candidate.appointments)
    assert all(role.job is None for role in candidate.appointments)


@pytest.mark.parametrize(
    "contract",
    [
        _contract(999_901),
        _contract(NORTHBRIDGE_TEAM_A, start_year=2032, end_year=2033),
        _contract(NORTHBRIDGE_TEAM_A, start_year=2027, end_year=2029),
    ],
    ids=["unresolved-team", "future-contract", "expired-contract"],
)
def test_role_evidence_can_leave_employment_unknown(tmp_path: Path, contract: bytes) -> None:
    path = career_fragment(
        extra_staff=_independent(contract=contract) + _close_independent()
    ).write(tmp_path / "career.bin")
    with fmsave.open(path) as save:
        candidate = next(row for row in save.staff_candidates() if row.uid == INDEPENDENT_UID)

    assert candidate.employment == "unknown"
    assert candidate.appointments == ()


def test_independent_profiles_with_conflicting_person_headers_are_omitted(tmp_path: Path) -> None:
    path = career_fragment(
        extra_staff=_independent()
        + _close_independent()
        + _independent(uid=830_026)
        + struct.pack("<III", INDEPENDENT_ID + 1, 830_027, 830_027)
        + bytes(32)
    ).write(tmp_path / "career.bin")
    with fmsave.open(path) as save:
        candidates = save.staff_candidates()
    assert {row.uid for row in candidates}.isdisjoint({INDEPENDENT_UID, 830_026})


@pytest.mark.parametrize("layout", [STAFF_LAYOUT, fm27.STAFF])
def test_staff_ratings_read_at_their_stored_scales_by_layout(layout: StaffLayout) -> None:
    preferences = (7,) * 4 + (19,) + (7,) * 7 + (18, 83) + (7,) * 12
    values = (0,) + tuple(range(30, 54)) + (101,)
    staff = staff_object_bytes(
        person_id=27, uid=730_027, r4=16, preferences=preferences, block_40=values
    )

    block, _, _, _ = _read_ability_block(staff, 0, layout)
    assert block is not None
    assert block.ratings["goalkeeping"] == 30
    assert block.ratings["judging_player_ability"] == 31
    assert block.ratings["attacking"] == 37
    assert block.ratings["technical"] == 41
    assert block.ratings["authority"] == 19
    assert block.ratings["working_with_youngsters"] == 18
    assert block.ratings["determination"] == 83
    assert block.ratings["set_pieces"] is None
    assert block.unknown["r4"] == 16


def _fm27_candidates(
    extra_staff: bytes, human_selector: int = 0
) -> tuple[fmsave.StaffCandidate, ...]:
    from fmsave.readers.clubs import read_club_index
    from fmsave.readers.names import locate_name_pools
    from fmsave.readers.player_scan import locate_player_records
    from fmsave.readers.staff import read_staff_candidates
    from tests.fixtures.career import career_game_db
    from tests.fixtures.game_db import humans_body
    from tests.test_persons import registered_name_pool_layout
    from tests.test_staff import CLUB_LAYOUTS, FILE_NAME, PLAYER_LAYOUT, STAFF_LAYOUTS

    db = career_game_db(extra_staff=extra_staff)
    clubs = read_club_index(db, CLUB_LAYOUTS, FILE_NAME)
    pools = locate_name_pools(db, registered_name_pool_layout(), FILE_NAME)
    players = locate_player_records(db, pools.end_offset, PLAYER_LAYOUT, FILE_NAME)
    return read_staff_candidates(
        db,
        humans_body(count=int(human_selector > 0), selector=human_selector),
        clubs,
        players,
        pools,
        date(2031, 3, 1),
        replace(STAFF_LAYOUTS, staff=replace(fm27.STAFF, list_count_bytes=1)),
        FILE_NAME,
    )


def test_fm27_appointments_keep_distinct_same_team_jobs_and_exclude_offers() -> None:
    from tests.test_fm27_staff import job_contract, no_contract_role, person_with

    job = job_contract(job=2, wage=900)
    renewal = job_contract(job=2, start_year=2030, wage=1_500, offer=True)
    offer = job_contract(job=16, team_id=SOUTHPORT_TEAM, offer=True)
    board = no_contract_role(job=4)
    raw_job = no_contract_role(job=222)
    candidates = _fm27_candidates(person_with(job + renewal + offer + board + raw_job))

    candidate = next(row for row in candidates if row.uid == 810_018)
    assert candidate.legal_name == "Role Example"
    assert candidate.employment == "employed"
    assert [
        (role.job and role.job.label, role.job and role.job.raw)
        for role in (candidate.appointments)
    ] == [
        (fmsave.StaffJob.COACH, 2),
        (fmsave.StaffJob.CHAIRPERSON, 4),
        (fmsave.StaffJob.UNKNOWN, 222),
    ]
    assert [role.has_contract for role in candidate.appointments] == [True, False, False]
    assert [role.wage for role in candidate.appointments] == [900, None, None]


def test_zero_personality_human_profile_can_follow_a_large_manager_object() -> None:
    from tests.test_fm27_staff import ZERO_SLOT_PERSONALITY, own_contract, person_block

    person = staff_object_bytes(
        person_id=18,
        uid=810_018,
        kind=9,
        padding_before_contract=25_000,
        contract=own_contract(),
        person_block=person_block("Manager Example", ZERO_SLOT_PERSONALITY),
    )
    neighbor = staff_object_bytes(
        person_id=19, uid=810_019, person_block=person_block("Neighbor Example")
    )
    manager = next(
        row
        for row in _fm27_candidates(person + neighbor, human_selector=19)
        if row.is_human_manager
    )

    assert manager.legal_name == "Manager Example"
    assert manager.personality is not None
    assert manager.personality.controversy == 0


def test_fm27_coherent_unlisted_profile_with_no_role_evidence_can_be_a_free_agent() -> None:
    from tests.test_fm27_staff import person_with

    candidate = next(row for row in _fm27_candidates(person_with(b"")) if row.uid == 810_018)

    assert candidate.employment is fmsave.StaffEmployment.FREE_AGENT
    assert candidate.appointments == ()
    assert fmsave.field_status(fmsave.StaffCandidate, "employment") == "unconfirmed"


@pytest.mark.parametrize("job", [16, 222], ids=["known-job", "unknown-job"])
def test_fm27_unresolved_role_without_contract_tag_blocks_free_agent_inference(job: int) -> None:
    from tests.test_fm27_staff import person_with

    role = struct.pack("<II", 19, 999_901) + bytes(8) + bytes((job, 0, 0)) + b"\xff" * 4
    candidate = next(row for row in _fm27_candidates(person_with(role)) if row.uid == 810_018)

    assert candidate.employment == "unknown"
    assert candidate.appointments == ()


def test_fm27_offer_without_confirmed_job_keeps_employment_unknown() -> None:
    from tests.test_fm27_staff import job_contract, person_with

    blob = person_with(job_contract(job=16, offer=True))
    candidate = next(row for row in _fm27_candidates(blob) if row.uid == 810_018)

    assert candidate.employment == "unknown"
    assert candidate.appointments == ()


def test_fm27_stored_zero_role_hint_does_not_confirm_a_free_agent() -> None:
    from tests.test_fm27_staff import person_block

    person = staff_object_bytes(
        person_id=18, uid=810_018, r4=0, person_block=person_block("Alex Example")
    )
    closing = struct.pack("<III", 19, 810_019, 810_019) + bytes(32)
    candidate = next(row for row in _fm27_candidates(person + closing) if row.uid == 810_018)

    assert candidate.employment == "unknown"


def test_fm27_list_membership_blocks_free_agent_inference() -> None:
    candidate = next(row for row in _fm27_candidates(b"") if row.uid == STAFF_LISTED_ONLY_UID)

    assert candidate.employment == "unknown"
    assert candidate.appointments == ()


def test_unbounded_staff_does_not_borrow_neighbor_profile_or_appointment() -> None:
    from tests.test_fm27_staff import job_contract, person_block

    own = staff_object_bytes(person_id=18, uid=810_018, contract=job_contract(job=2))
    neighbor = staff_object_bytes(
        person_id=20,
        uid=810_020,
        kind=2,
        contract=job_contract(job=14, team_id=SOUTHPORT_TEAM),
        person_block=person_block("Neighbor Example"),
    )
    candidate = next(row for row in _fm27_candidates(own + neighbor) if row.uid == 810_018)

    assert candidate.legal_name is None
    assert candidate.personality is None
    assert candidate.employment == "unknown"
    assert candidate.appointments == ()


def test_staff_ratings_cannot_cross_a_validated_object_boundary() -> None:
    from tests.test_fm27_staff import job_contract, person_block

    own = bytearray(
        staff_object_bytes(
            person_id=18,
            uid=810_018,
            contract=job_contract(job=2),
            person_block=person_block("Own Example"),
        )
    )
    own.extend(bytes(-len(own) % 7))
    own[13] = len(own) // 7
    neighbor = staff_object_bytes(
        person_id=19,
        uid=810_019,
        block_40=(97,) * 26,
        person_block=person_block("Neighbor Example"),
    )
    closing = struct.pack("<III", 20, 810_020, 810_020) + bytes(32)
    candidates = {row.uid: row for row in _fm27_candidates(bytes(own) + neighbor + closing)}
    assert candidates[810_018].legal_name == "Own Example"
    assert candidates[810_018].attributes is not None
    assert candidates[810_018].attributes.attacking is None
    assert candidates[810_019].attributes is not None
    assert candidates[810_019].attributes.attacking == 97


def test_listed_staff_id_seen_at_two_complete_headers_is_omitted(tmp_path: Path) -> None:
    duplicate_uid = 730_022
    duplicate = staff_object_bytes(
        person_id=STAFF_LISTED_ONLY_PERSON_ID,
        uid=duplicate_uid,
        person_block=_profile(),
    )
    path = career_fragment(extra_staff=duplicate).write(tmp_path / "career.bin")
    with fmsave.open(path) as save:
        uids = {row.uid for row in save.staff_candidates()}

    assert uids.isdisjoint({duplicate_uid, STAFF_LISTED_ONLY_UID})
