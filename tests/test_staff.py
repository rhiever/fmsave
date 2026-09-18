from __future__ import annotations

import copy
import pickle
import struct
from array import array
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

import fmsave
import fmsave._save as save_module
from fmsave import Ability, Staff, StaffList, export, field_status
from fmsave._checks import (
    STAFF_LISTS_READER,
    STAFF_READER,
    GateResult,
    ReaderCheck,
    evaluate_staff,
    evaluate_staff_lists,
)
from fmsave._frozen import FrozenMapping
from fmsave._layouts import GateBounds, PlayerRecordLayout, find_layout
from fmsave._reader_stats import StaffStats
from fmsave._save import STAFF_LISTS_TABLE_CACHE_KEY, STAFF_TABLE_CACHE_KEY
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.clubs import ClubIndex, find_club_layouts, read_club_index
from fmsave.readers.names import NamePools
from fmsave.readers.player_scan import PlayerRecords
from fmsave.readers.staff import (
    StaffLayouts,
    _read_ability_block,
    find_staff_layouts,
    locate_listed_header,
    read_staff_lists,
)
from tests.fixtures.career import (
    BUILD_STRING,
    COLTS_UID,
    GAME_DB_SCHEMA,
    MANAGER_PERSON_UID,
    MISSING_NAME_ID,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_UID,
    SOUTHPORT_TEAM,
    SOUTHPORT_UID,
    STAFF_AFFILIATE_UID,
    STAFF_CONTRACT_ONLY_UID,
    STAFF_CONTRACTED_UID,
    STAFF_LISTED_ONLY_PERSON_ID,
    STAFF_LISTED_ONLY_UID,
    career_fragment,
)
from tests.fixtures.container import packed_date
from tests.fixtures.game_db import (
    club_record_bytes,
    contract_bytes,
    game_db_body,
    person_block_bytes,
    player_record_bytes,
)
from tests.fixtures.staff import staff_object_bytes

BOUNDS = find_layout(GateBounds, GAME_DB_SECTION, GAME_DB_SCHEMA, BUILD_STRING).layout
PLAYER_LAYOUT = find_layout(
    PlayerRecordLayout, GAME_DB_SECTION, GAME_DB_SCHEMA, BUILD_STRING
).layout
STAFF_LAYOUTS = find_staff_layouts({GAME_DB_SECTION: GAME_DB_SCHEMA}, BUILD_STRING)
STAFF_LAYOUT = STAFF_LAYOUTS.staff
CLUB_LAYOUTS = find_club_layouts(GAME_DB_SCHEMA, BUILD_STRING)
FILE_NAME = "career example.fm"
FULL_SIZE_GAME_DB_BYTES = 100 * 1024 * 1024
FRAGMENT_GAME_DB_BYTES = 1024 * 1024

# Extra people some tests add to the staff region, in front of the example staff.
FAR_CONTRACT_PERSON_ID = 26
FAR_CONTRACT_PERSON_UID = 810_026
BROKEN_SENTINEL_PERSON_ID = 27
BROKEN_SENTINEL_PERSON_UID = 810_027
BROKEN_SENTINEL_VALUE = 11
LAST_BLOCK_BYTE_PERSON_ID = 28
LAST_BLOCK_BYTE_PERSON_UID = 810_028
# A value outside the range the block of 26 further bytes holds, in the block's **last** byte.
OUT_OF_RANGE_BLOCK_VALUE = 200
# The three example staff of the fragment, plus the one a test adds. The human manager's object
# is not a staff object and is not counted.
STAFF_OBJECTS_WITH_ONE_ADDED = 4
# Comfortably more than the layout's own search behind a contract tag.
FAR_CONTRACT_PADDING_BYTES = 40_000
IGNORED_OBJECT_KIND = 16


@pytest.fixture(scope="module")
def career_staff(career_save_path: Path) -> tuple[tuple[Staff, ...], tuple[StaffList, ...]]:
    with fmsave.open(career_save_path) as career_save:
        return tuple(career_save.staff()), tuple(career_save.staff_lists())


def person_by_uid(rows: Sequence[Staff], uid: int) -> Staff:
    matching = [row for row in rows if row.uid == uid]
    assert len(matching) == 1
    return matching[0]


def observed_gate(reader_check: ReaderCheck, gate_name: str) -> float | None:
    """What one of a reader's checks observed, whether or not the check applied."""
    matching = [gate for gate in reader_check.gates if gate.name == gate_name]
    assert len(matching) == 1
    return matching[0].observed


def sound_stats(**overrides: object) -> StaffStats:
    """A `StaffStats` every check passes, with named fields replaced."""
    values: dict[str, object] = {
        "clubs_checked": 1_000,
        "clubs_lists_fit": 1_000,
        "list_values": 2_100,
        "player_values_in_lists": 4,
        "listed_persons": 2_000,
        "listed_persons_staff": 2_000,
        "staff_objects": 2_000,
        "ability_signatures": 2_000,
        "preference_slots_in_range": 2_000,
        "codes_in_set": 2_000,
        "block_40_in_range": 2_000,
        "persons": 2_000,
        "persons_with_block": 2_000,
        "discovery_hits": 40_000,
        "untailed_hits": 3_000,
        "unowned_tailed_hits": 0,
        "owned_records": 1_800,
        "listed_pairs": 1_000,
        "listed_pairs_contracted_here": 900,
        "merged_affiliate_pairs": 20,
        "ambiguous_headers": 0,
        "unlocated_persons": 0,
        "unresolved_contract_teams": 5,
        "repeat_contracts": 1,
        "human_found": True,
        "rows": 2_000,
        "list_rows": 300,
    }
    values.update(overrides)
    return StaffStats(**values)  # pyright: ignore[reportArgumentType]


def failed_gate_names(results: tuple[GateResult, ...]) -> list[str]:
    return [result.name for result in results if result.applied and not result.passed]


def all_staff_gates(stats: StaffStats, game_db_bytes: int) -> tuple[GateResult, ...]:
    return evaluate_staff(stats, BOUNDS, game_db_bytes) + evaluate_staff_lists(
        stats, BOUNDS, game_db_bytes
    )


def test_staff_lists_one_row_per_person_and_club_in_object_order(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    assert [row.uid for row in rows] == [
        MANAGER_PERSON_UID,
        STAFF_CONTRACTED_UID,
        STAFF_LISTED_ONLY_UID,
        STAFF_CONTRACT_ONLY_UID,
    ]


def test_the_human_manager_is_a_row_with_a_contract_and_no_ability(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    manager = person_by_uid(rows, MANAGER_PERSON_UID)
    assert manager.is_human_manager is True
    assert manager.club_uid == NORTHBRIDGE_UID
    assert manager.club_name == "Northbridge FC"
    assert manager.team_id == NORTHBRIDGE_TEAM_A
    assert manager.team_slot == 0
    assert manager.name == "Alex Sample"
    assert manager.in_club_lists is False
    assert manager.list_indexes == ()
    assert manager.listed_club_uid is None
    assert manager.has_contract is True
    assert manager.wage == 4_000
    assert manager.contract_start == date(2029, 7, 2)
    assert manager.contract_end == date(2032, 6, 30)
    assert manager.ability is None
    assert manager.preferences is None
    assert manager.attributes is not None
    assert manager.attributes.adaptability == 12
    assert dict(manager.unknown) == {
        "contract_e36": 3,
        "contract_e37": 0,
        "contract_e38": 0,
        "contract_e39": 0,
        "contract_type": 1,
    }


def test_a_listed_and_contracted_person_carries_both_sides(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    contracted = person_by_uid(rows, STAFF_CONTRACTED_UID)
    assert contracted.club_uid == NORTHBRIDGE_UID
    assert contracted.team_id == NORTHBRIDGE_TEAM_A
    assert contracted.in_club_lists is True
    assert contracted.list_indexes == (0,)
    assert contracted.listed_club_uid == NORTHBRIDGE_UID
    assert contracted.has_contract is True
    assert contracted.wage == 2_500
    assert contracted.contract_start == date(2029, 7, 2)
    assert contracted.contract_end == date(2032, 6, 30)
    assert contracted.ability == Ability(current=120, potential=140, potential_range_code=None)
    assert contracted.name == "Sam Example"
    assert contracted.birth_date == date(1980, 6, 15)
    assert contracted.age == 50
    assert contracted.nation_id == 44
    assert contracted.personality is not None
    assert contracted.personality.adaptability == 14
    assert contracted.attributes is not None
    assert contracted.attributes.adaptability == 14


def test_every_named_preference_comes_from_its_own_slot(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    preferences = person_by_uid(rows, STAFF_CONTRACTED_UID).preferences
    assert preferences is not None
    assert preferences.attacking == 1
    assert preferences.business == 2
    assert preferences.directness == 4
    assert preferences.interference == 7
    assert preferences.patience == 10
    assert preferences.trigger_press == 11
    assert preferences.resources == 12
    assert preferences.buying_players == 15
    assert preferences.mind_games == 16
    assert preferences.flexibility == 2
    assert preferences.hardness_of_training == 3
    assert preferences.squad_rotation == 4
    assert preferences.tempo == 5
    assert preferences.width == 6


def test_the_unknown_map_holds_the_object_and_the_contract_codes(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    unknown = person_by_uid(rows, STAFF_CONTRACTED_UID).unknown
    assert unknown["entry_count"] == 0
    assert [unknown[f"r{code_number}"] for code_number in range(4, 13)] == [
        16,
        4,
        22,
        29,
        28,
        33,
        30,
        35,
        3,
    ]
    assert unknown["preference_slot_2"] == 3
    assert unknown["preference_slot_4"] == 5
    assert unknown["preference_slot_5"] == 6
    assert unknown["preference_slot_7"] == 8
    assert unknown["preference_slot_8"] == 9
    assert unknown["preference_slot_12"] == 13
    assert unknown["preference_slot_13"] == 75
    assert unknown["preference_slot_16"] == 17
    assert unknown["preference_slot_17"] == 18
    assert unknown["preference_slot_18"] == 19
    assert unknown["preference_slot_19"] == 20
    assert unknown["preference_slot_20"] == 1
    assert unknown["contract_e36"] == 0
    assert unknown["contract_e39"] == 64
    assert unknown["contract_type"] == 1


def test_a_listed_person_with_no_contract_has_no_wage_or_dates(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    listed_only = person_by_uid(rows, STAFF_LISTED_ONLY_UID)
    assert listed_only.club_uid == NORTHBRIDGE_UID
    assert listed_only.team_id is None
    assert listed_only.team_slot is None
    assert listed_only.list_indexes == (1,)
    assert listed_only.has_contract is False
    assert listed_only.wage is None
    assert listed_only.contract_start is None
    assert listed_only.contract_end is None
    assert listed_only.ability is not None
    assert listed_only.ability.current == 80
    assert listed_only.ability.potential == 95
    assert listed_only.unknown["entry_count"] == 2
    assert listed_only.unknown["r4"] == 20
    assert not [key for key in listed_only.unknown if key.startswith("contract_")]
    assert listed_only.name == "Sam Sample"


def test_a_person_no_club_lists_is_a_row_where_his_contract_is(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, _list_rows = career_staff
    contract_only = person_by_uid(rows, STAFF_CONTRACT_ONLY_UID)
    assert contract_only.club_uid == SOUTHPORT_UID
    assert contract_only.club_name == "Southport Example"
    assert contract_only.team_id == SOUTHPORT_TEAM
    assert contract_only.in_club_lists is False
    assert contract_only.listed_club_uid is None
    assert contract_only.wage == 900
    assert contract_only.contract_end == date(2031, 6, 30)
    assert contract_only.unknown["contract_e36"] == 3
    assert contract_only.unknown["contract_type"] == 0


def test_a_club_that_lists_somebody_gets_all_three_lists(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    _rows, list_rows = career_staff
    assert [(row.club_uid, row.list_index) for row in list_rows] == [
        (NORTHBRIDGE_UID, 0),
        (NORTHBRIDGE_UID, 1),
        (NORTHBRIDGE_UID, 2),
    ]
    assert list_rows[0].person_uids == (STAFF_CONTRACTED_UID,)
    assert list_rows[0].person_names == ("Sam Example",)
    assert list_rows[1].person_uids == (STAFF_LISTED_ONLY_UID,)
    assert list_rows[2].person_uids == ()


def test_the_pass_counts_what_it_turned_away(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        career_save.staff()
        staff_check = career_save._reader_check(STAFF_READER)
        lists_check = career_save._reader_check(STAFF_LISTS_READER)
    assert staff_check is not None
    assert lists_check is not None
    assert staff_check.anomalies["untailed_hits"] >= 1
    assert staff_check.anomalies["ambiguous_headers"] == 0
    assert staff_check.anomalies["unlocated_persons"] == 0
    assert staff_check.anomalies["human_manager_missing"] == 0
    assert staff_check.record_count == 4
    assert lists_check.anomalies["player_values_in_lists"] == 1


def test_a_person_an_affiliate_side_lists_belongs_to_its_parent(tmp_path: Path) -> None:
    save_path = career_fragment(staff_affiliate=True).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        rows = tuple(career_save.staff())
        list_rows = tuple(career_save.staff_lists())
        staff_check = career_save._reader_check(STAFF_READER)

    assert len(rows) == 5
    affiliate_person = person_by_uid(rows, STAFF_AFFILIATE_UID)
    assert affiliate_person.club_uid == NORTHBRIDGE_UID
    assert affiliate_person.listed_club_uid == COLTS_UID
    assert affiliate_person.list_indexes == (2,)
    assert affiliate_person.in_club_lists is True
    assert affiliate_person.has_contract is True
    assert affiliate_person.wage == 1_200
    assert not [row for row in rows if row.club_uid == COLTS_UID]
    assert staff_check is not None
    assert staff_check.anomalies["merged_affiliate_pairs"] == 1
    assert len(list_rows) == 6
    colts_lists = [row for row in list_rows if row.club_uid == COLTS_UID]
    assert [row.person_uids for row in colts_lists] == [(), (), (STAFF_AFFILIATE_UID,)]


def test_a_person_with_two_headers_in_his_window_gets_no_row(tmp_path: Path) -> None:
    decoy = staff_object_bytes(
        person_id=STAFF_LISTED_ONLY_PERSON_ID,
        uid=STAFF_LISTED_ONLY_UID,
        current_ability=70,
        potential_ability=75,
    )
    save_path = career_fragment(extra_staff=decoy).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        rows = tuple(career_save.staff())
        staff_check = career_save._reader_check(STAFF_READER)

    assert not [row for row in rows if row.uid == STAFF_LISTED_ONLY_UID]
    assert staff_check is not None
    assert staff_check.anomalies["ambiguous_headers"] == 1


def test_a_decoy_of_another_object_kind_is_ignored(tmp_path: Path) -> None:
    decoy = staff_object_bytes(
        person_id=STAFF_LISTED_ONLY_PERSON_ID,
        uid=STAFF_LISTED_ONLY_UID,
        kind=IGNORED_OBJECT_KIND,
    )
    save_path = career_fragment(extra_staff=decoy).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        rows = tuple(career_save.staff())
        staff_check = career_save._reader_check(STAFF_READER)

    assert person_by_uid(rows, STAFF_LISTED_ONLY_UID).list_indexes == (1,)
    assert staff_check is not None
    assert staff_check.anomalies["ambiguous_headers"] == 0


def test_a_contract_too_far_from_its_header_belongs_to_nobody(tmp_path: Path) -> None:
    far_record, _tag_offset = _far_contract_record()
    far_person = staff_object_bytes(
        person_id=FAR_CONTRACT_PERSON_ID,
        uid=FAR_CONTRACT_PERSON_UID,
        contract=far_record,
        padding_before_contract=FAR_CONTRACT_PADDING_BYTES,
    )
    save_path = career_fragment(extra_staff=far_person).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        rows = tuple(career_save.staff())
        staff_check = career_save._reader_check(STAFF_READER)

    assert not [row for row in rows if row.uid == FAR_CONTRACT_PERSON_UID]
    assert staff_check is not None
    assert observed_gate(staff_check, "staff_unowned_tailed_contracts") == 1


def test_the_block_of_further_bytes_is_counted_from_its_own_first_to_its_own_last(
    tmp_path: Path,
) -> None:
    """The count is pinned from both ends: the last byte of the block is out of range here.

    Read one byte late, the block runs into the word after it, which is out of range for every
    object; read one byte short, the out-of-range byte below falls outside it. Either way this
    share moves, so neither the block's offset nor its length can shift unnoticed.
    """
    record, _tag_offset = contract_bytes(
        selector=LAST_BLOCK_BYTE_PERSON_ID + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=800,
        start=packed_date(1, 2030),
        tail={"end": packed_date(181, 2031), "status": 0},
        head={"type": 1},
    )
    out_of_range_block = (50,) * 25 + (OUT_OF_RANGE_BLOCK_VALUE,)
    person = staff_object_bytes(
        person_id=LAST_BLOCK_BYTE_PERSON_ID,
        uid=LAST_BLOCK_BYTE_PERSON_UID,
        block_40=out_of_range_block,
        contract=record,
        person_block=person_block_bytes(
            first_name_id=1,
            surname_id=1,
            common_name_id=MISSING_NAME_ID,
            legal_name=None,
            birth=packed_date(1, 1988),
            nation_id=44,
            personality=(8,) * 8,
            trait_bits=0,
            relations=(),
        ),
    )
    save_path = career_fragment(extra_staff=person).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        career_save.staff()
        staff_check = career_save._reader_check(STAFF_READER)

    assert staff_check is not None
    assert (
        observed_gate(staff_check, "staff_block_40_in_range")
        == (STAFF_OBJECTS_WITH_ONE_ADDED - 1) / STAFF_OBJECTS_WITH_ONE_ADDED
    )
    # Nothing else about the object is affected: the share above is the only thing that moves.
    assert observed_gate(staff_check, "staff_ability_signature") == 1.0


def test_a_header_with_no_room_for_an_object_reads_no_ability_block() -> None:
    truncated = struct.pack("<III", 7, 900, 900) + bytes((STAFF_LAYOUT.staff_kind,))

    assert _read_ability_block(truncated, 0, STAFF_LAYOUT) == (None, False, False, False)


def _far_contract_record() -> tuple[bytes, int]:
    return contract_bytes(
        selector=FAR_CONTRACT_PERSON_ID + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=700,
        start=packed_date(1, 2030),
        tail={"end": packed_date(181, 2031), "status": 0},
        head={"type": 1},
    )


def test_an_object_whose_sentinel_is_wrong_keeps_its_name_and_contract(tmp_path: Path) -> None:
    record, _tag_offset = contract_bytes(
        selector=BROKEN_SENTINEL_PERSON_ID + 1,
        team_id=NORTHBRIDGE_TEAM_A,
        wage=1_100,
        start=packed_date(1, 2030),
        tail={"end": packed_date(181, 2031), "status": 0},
        head={"type": 1},
    )
    broken = staff_object_bytes(
        person_id=BROKEN_SENTINEL_PERSON_ID,
        uid=BROKEN_SENTINEL_PERSON_UID,
        sentinel=BROKEN_SENTINEL_VALUE,
        contract=record,
        person_block=person_block_bytes(
            first_name_id=0,
            surname_id=1,
            common_name_id=MISSING_NAME_ID,
            legal_name=None,
            birth=packed_date(1, 1985),
            nation_id=44,
            personality=(6,) * 8,
            trait_bits=0,
            relations=(),
        ),
    )
    save_path = career_fragment(extra_staff=broken).write(tmp_path / "career.bin")

    with fmsave.open(save_path) as career_save:
        rows = tuple(career_save.staff())

    person = person_by_uid(rows, BROKEN_SENTINEL_PERSON_UID)
    assert person.ability is None
    assert person.preferences is None
    assert not [key for key in person.unknown if key.startswith(("r", "preference_slot_"))]
    assert person.name == "Alex Sample"
    assert person.wage == 1_100


def empty_player_records() -> PlayerRecords:
    return PlayerRecords(
        record_offsets=array("Q"),
        pindexes=array("I"),
        uids=array("I"),
        markerless_count=0,
        position_by_pindex={},
        position_by_uid={},
        layout=PLAYER_LAYOUT,
    )


def test_a_club_whose_lists_overrun_its_record_gives_no_rows() -> None:
    overrunning_count = bytes((200,))
    club_records = [
        club_record_bytes(
            club_index=1,
            uid=4_001,
            nation_id=3,
            fa_nation_id=3,
            city_id=7,
            name="Northbridge FC",
            short_name="Northbridge",
            team_ids=(70_001,),
            staff_lists=((30,), (), ()),
        ),
        club_record_bytes(
            club_index=2,
            uid=4_002,
            nation_id=3,
            fa_nation_id=3,
            city_id=7,
            name="Southport Example",
            short_name="Southport",
            team_ids=(70_003,),
            trailing_bytes=overrunning_count,
        ),
        club_record_bytes(
            club_index=3,
            uid=4_003,
            nation_id=3,
            fa_nation_id=3,
            city_id=7,
            name="Example Athletic",
            short_name="Athletic",
            team_ids=(70_005,),
            staff_lists=((), (), ()),
        ),
    ]
    game_db = game_db_body(club_records, [], gap_bytes=64)
    club_index = read_club_index(game_db, CLUB_LAYOUTS, FILE_NAME)

    listed_pairs, lists_by_club, counts = read_staff_lists(
        game_db, club_index, empty_player_records(), STAFF_LAYOUT
    )

    assert counts.clubs_checked == 3
    assert counts.clubs_lists_fit == counts.clubs_checked - 1
    assert 4_002 not in lists_by_club
    assert [club_uid for club_uid, _person_id in listed_pairs] == [4_001]


def test_a_person_below_every_pindex_is_looked_for_from_the_start_of_the_section() -> None:
    person_id = 5
    leading_bytes = 256
    person_object = staff_object_bytes(person_id=person_id, uid=810_005)
    player_blob = player_record_bytes(
        pindex=11,
        uid=900_001,
        current_ability=140,
        potential_ability=165,
        bucket=100,
        home_reputation=5_000,
        current_reputation=5_200,
        world_reputation=5_100,
        team_id=70_001,
        ratings=(1,) * 15,
        raw_attributes=(48,) * 54,
        transfer_value_raw=0,
        join_date=bytes(4),
        sharpness=7_000,
        condition=9_000,
        height_cm=180,
    )
    # The player record starts 26 bytes into its blob and its own header sits 19 bytes before
    # that, so the window a list-only person is looked for in ends here.
    player_record_offset = leading_bytes + len(person_object) + 26
    before_the_player = bytes(leading_bytes) + person_object + player_blob
    after_the_player = bytes(leading_bytes) + player_blob + person_object
    player_records = PlayerRecords(
        record_offsets=array("Q", [player_record_offset]),
        pindexes=array("I", [11]),
        uids=array("I", [900_001]),
        markerless_count=0,
        position_by_pindex={11: 0},
        position_by_uid={900_001: 0},
        layout=PLAYER_LAYOUT,
    )

    assert (
        locate_listed_header(before_the_player, person_id, player_records, STAFF_LAYOUT)
        == leading_bytes
    )
    assert locate_listed_header(after_the_player, person_id, player_records, STAFF_LAYOUT) is None


def test_export_flattens_every_group_and_unknown_key() -> None:
    columns = export.column_names(Staff)
    assert columns[:1] == ("uid",)
    for column_name in (
        "ability_current",
        "ability_potential",
        "ability_potential_range_code",
        "personality_adaptability",
        "attributes_adaptability",
        "preferences_attacking",
        "preferences_width",
    ):
        assert column_name in columns
    unknown_columns = [name for name in columns if name.startswith("unknown_")]
    assert len(unknown_columns) == len(Staff.UNKNOWN_KEYS) == 27
    assert export.column_names(StaffList) == (
        "club_uid",
        "club_name",
        "list_index",
        "person_uids",
        "person_names",
    )


def test_records_round_trip_and_carry_their_field_statuses(
    career_staff: tuple[tuple[Staff, ...], tuple[StaffList, ...]],
) -> None:
    rows, list_rows = career_staff
    for record in (*rows, *list_rows):
        assert pickle.loads(pickle.dumps(record)) == record
        assert copy.deepcopy(record) == record
    assert field_status(Staff, "preferences.tempo") == "verified"
    assert field_status(Staff, "ability.current") == "unconfirmed"
    assert field_status(Staff, "uid") == "unconfirmed"


def test_both_tables_come_from_one_decode_and_stop_after_close(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    real_read_staff = save_module.read_staff

    def counting_read_staff(
        game_db: bytes,
        humans: bytes,
        club_index: ClubIndex,
        player_records: PlayerRecords,
        name_pools: NamePools,
        clock: date,
        layouts: StaffLayouts,
        file_name: str,
    ) -> tuple[tuple[Staff, ...], tuple[StaffList, ...], StaffStats]:
        nonlocal calls
        calls += 1
        return real_read_staff(
            game_db,
            humans,
            club_index,
            player_records,
            name_pools,
            clock,
            layouts,
            file_name,
        )

    monkeypatch.setattr(save_module, "read_staff", counting_read_staff)
    with fmsave.open(career_save_path) as career_save:
        staff_rows = career_save.staff()
        list_rows = career_save.staff_lists()
        assert career_save.staff() is staff_rows
        assert career_save.staff_lists() is list_rows
        assert career_save._context.cached_value(STAFF_TABLE_CACHE_KEY) is staff_rows
        assert career_save._context.cached_value(STAFF_LISTS_TABLE_CACHE_KEY) is list_rows
    assert calls == 1
    with pytest.raises(fmsave.SaveClosedError):
        career_save.staff()
    with pytest.raises(fmsave.SaveClosedError):
        career_save.staff_lists()


@pytest.mark.parametrize(
    ("overrides", "failing_gate"),
    [
        ({"clubs_lists_fit": 980}, "staff_lists_fit"),
        ({"listed_persons_staff": 1_868}, "staff_list_ids_are_staff"),
        ({"ability_signatures": 1_450}, "staff_ability_signature"),
        ({"preference_slots_in_range": 52}, "staff_preference_slots"),
        ({"codes_in_set": 38}, "staff_codes_in_set"),
        ({"block_40_in_range": 150}, "staff_block_40_in_range"),
        ({"persons_with_block": 1_960}, "staff_person_blocks"),
        ({"persons": 999, "persons_with_block": 999}, "staff_minimum"),
        ({"listed_pairs_contracted_here": 590}, "staff_listed_contracted_here"),
        ({"unowned_tailed_hits": 1}, "staff_unowned_tailed_contracts"),
    ],
)
def test_each_gate_fails_on_its_own_misaligned_value(
    overrides: dict[str, object], failing_gate: str
) -> None:
    sound = all_staff_gates(sound_stats(), FULL_SIZE_GAME_DB_BYTES)
    assert failed_gate_names(sound) == []

    misaligned = all_staff_gates(sound_stats(**overrides), FULL_SIZE_GAME_DB_BYTES)

    assert failed_gate_names(misaligned) == [failing_gate]


def test_no_staff_gate_applies_to_a_fragment() -> None:
    results = all_staff_gates(sound_stats(persons=0), FRAGMENT_GAME_DB_BYTES)
    assert [result.applied for result in results] == [False] * len(results)


def test_an_empty_population_applies_no_share() -> None:
    empty = sound_stats(
        clubs_checked=0,
        clubs_lists_fit=0,
        listed_persons=0,
        listed_persons_staff=0,
        staff_objects=0,
        ability_signatures=0,
        preference_slots_in_range=0,
        codes_in_set=0,
        block_40_in_range=0,
        listed_pairs=0,
        listed_pairs_contracted_here=0,
    )
    results = all_staff_gates(empty, FULL_SIZE_GAME_DB_BYTES)
    unapplied = {result.name for result in results if not result.applied}
    assert unapplied == {
        "staff_lists_fit",
        "staff_list_ids_are_staff",
        "staff_ability_signature",
        "staff_preference_slots",
        "staff_codes_in_set",
        "staff_block_40_in_range",
        "staff_listed_contracted_here",
    }
    assert failed_gate_names(results) == []


def failing_check(stats: StaffStats, bounds: GateBounds, game_db_bytes: int) -> ReaderCheck:
    del bounds, game_db_bytes
    return ReaderCheck(
        "staff",
        stats.rows,
        (GateResult("staff_minimum", 0, 1, None, passed=False, applied=True),),
        FrozenMapping({}),
    )


def test_a_failed_check_leaves_neither_table_readable(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(save_module._checks, "check_staff", failing_check)
    with fmsave.open(career_save_path, strict=True) as career_save:
        with pytest.raises(fmsave.ReaderCheckError):
            career_save.staff()
        with pytest.raises(fmsave.ReaderCheckError):
            career_save.staff_lists()
