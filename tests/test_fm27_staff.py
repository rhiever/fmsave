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
    assert STAFF_LAYOUT.human_personality_floor is None


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
        staff=replace(STAFF_LAYOUTS.staff, human_personality_floor=human_personality_floor),
        person_blocks=replace(STAFF_LAYOUTS.person_blocks, require_unique_candidate=True),
    )
    rows, _lists, _stats = read_staff(
        db,
        humans_body(count=int(human_selector is not None), selector=human_selector or 0),
        clubs,
        players,
        pools,
        date(2030, 7, 1),
        layouts,
        "career example.fm",
    )
    return rows


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
