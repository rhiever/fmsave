from __future__ import annotations

import copy
import dataclasses
import pickle
from array import array
from datetime import date
from pathlib import Path

import pytest

import fmsave
import fmsave._save as save_module
from fmsave import Table
from fmsave._layouts import NamePoolLayout, PlayerRecordLayout, SuspensionLayout, find_layout
from fmsave._save import (
    CONTRACTS_TABLE_CACHE_KEY,
    PLAYERS_TABLE_CACHE_KEY,
    SUSPENSIONS_TABLE_CACHE_KEY,
)
from fmsave._status import field_status
from fmsave.models.players import Player
from fmsave.models.suspensions import PlayerSuspension, Suspension
from fmsave.readers.names import locate_name_pools
from fmsave.readers.player_scan import PlayerRecords, locate_player_records
from fmsave.readers.players import PlayerDecoder
from fmsave.readers.suspensions import SuspensionEntry, locate_suspensions
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    default_sections,
    packed_date,
    section_body,
)
from tests.fixtures.game_db import (
    STUB_STATUS_KIND,
    SUSPENSION_ENTRY_BYTES,
    club_record_bytes,
    game_db_body,
    name_pools_bytes,
    person_block_bytes,
    player_record_bytes,
    status_record_bytes,
    suspension_entry_bytes,
)
from tests.helpers.export_asserts import assert_matches_json_normalize

FILE_NAME = "career example.fm"
GAME_DB_SCHEMA = 4000

# player_record_bytes writes this many header bytes before the record start.
PLAYER_RECORD_HEADER_BYTES = 26
# A decoy entry starts this many bytes before the first player's record start.
BEFORE_FIRST_PLAYER_DECOY_DISTANCE = 40

FIRST_NAMES = ["Alex", "Sam"]
SURNAMES = ["Example", "Sample"]
COMMON_NAMES = ["Exo"]

RATINGS = tuple([10] * 15)
RAW_ATTRIBUTES = tuple([50] * 54)

SOUTHPORT_CLUB_UID = 5002
SOUTHPORT_TEAM_ID = 70003
SOUTHPORT_CLUB = club_record_bytes(
    club_index=1,
    uid=SOUTHPORT_CLUB_UID,
    nation_id=3,
    fa_nation_id=4,
    city_id=78,
    name="Southport Example",
    short_name="Southport",
    team_ids=(SOUTHPORT_TEAM_ID,),
    float_anchor_only=True,
)
SOUTHPORT_STATUS = status_record_bytes(
    ordinal=51,
    club_index=1,
    uid=SOUTHPORT_CLUB_UID,
    kind=STUB_STATUS_KIND,
    last_league_position=5,
    reputation=3000,
)

PLAYER_A_UID = 900001
PLAYER_B_UID = 900002

# Contiguous, right after player A's 300-byte record body.
PLAYER_A_ENTRIES = (
    suspension_entry_bytes(competition_id=1234, issued=packed_date(51, 2031), e7=3, e14=1),
    suspension_entry_bytes(competition_id=4321, issued=packed_date(306, 2030), e7=64, e14=5),
)
PLAYER_A_BLOCK = person_block_bytes(
    first_name_id=0,
    surname_id=0,
    common_name_id=0xFFFFFFFF,
    legal_name=None,
    birth=packed_date(60, 2004),
    nation_id=44,
    personality=(15, 12, 9, 20, 18, 7, 11, 3),
    trait_bits=0,
    relations=(),
)
# Signatures inside player B's window that must not be kept.
PLAYER_B_DECOYS = (
    suspension_entry_bytes(competition_id=2222, issued=packed_date(0, 2031), e7=3, e14=1),
    suspension_entry_bytes(competition_id=0, issued=packed_date(51, 2031), e7=3, e14=1),
    suspension_entry_bytes(competition_id=60000, issued=packed_date(51, 2031), e7=3, e14=1),
)
BEFORE_FIRST_PLAYER_DECOY = suspension_entry_bytes(
    competition_id=777, issued=packed_date(51, 2031), e7=3, e14=1
)

EXPECTED_PLAYER_A_ENTRIES = (
    SuspensionEntry(1234, date(2031, 2, 20), 3, 1),
    SuspensionEntry(4321, date(2030, 11, 2), 64, 5),
)


def _player_bytes(*, pindex: int, uid: int, team_id: int, trailing: bytes) -> bytes:
    return player_record_bytes(
        pindex=pindex,
        uid=uid,
        current_ability=120,
        potential_ability=140,
        bucket=100,
        home_reputation=5000,
        current_reputation=5200,
        world_reputation=5100,
        team_id=team_id,
        ratings=RATINGS,
        raw_attributes=RAW_ATTRIBUTES,
        transfer_value_raw=0xFFFFFFFF,
        join_date=packed_date(60, 2029),
        sharpness=7000,
        condition=9000,
        height_cm=180,
        trailing=trailing,
    )


def example_game_db() -> bytes:
    prefix = (
        name_pools_bytes(FIRST_NAMES, SURNAMES, COMMON_NAMES)
        + game_db_body([SOUTHPORT_CLUB], [SOUTHPORT_STATUS], gap_bytes=2000)
        + bytes(64)
    )
    player_a = _player_bytes(
        pindex=11,
        uid=PLAYER_A_UID,
        team_id=SOUTHPORT_TEAM_ID,
        trailing=b"".join(PLAYER_A_ENTRIES) + PLAYER_A_BLOCK,
    )
    player_b = _player_bytes(
        pindex=12,
        uid=PLAYER_B_UID,
        team_id=0xFFFFFFFF,
        trailing=bytes(40) + b"".join(PLAYER_B_DECOYS) + bytes(64),
    )
    payload = bytearray(prefix + player_a + player_b)
    # The decoy overwrites the end of the zero gap and the first, unread bytes of A's header.
    decoy_offset = len(prefix) + PLAYER_RECORD_HEADER_BYTES - BEFORE_FIRST_PLAYER_DECOY_DISTANCE
    payload[decoy_offset : decoy_offset + SUSPENSION_ENTRY_BYTES] = BEFORE_FIRST_PLAYER_DECOY
    return section_body(".dat", GAME_DB_SCHEMA, bytes(payload))


def registered_suspension_layout() -> SuspensionLayout:
    return find_layout(SuspensionLayout, "game_db", GAME_DB_SCHEMA, "").layout


def registered_player_layout() -> PlayerRecordLayout:
    return find_layout(PlayerRecordLayout, "game_db", GAME_DB_SCHEMA, "").layout


def example_player_records(game_db: bytes) -> PlayerRecords:
    name_pool_layout = find_layout(NamePoolLayout, "game_db", GAME_DB_SCHEMA, "").layout
    name_pools = locate_name_pools(game_db, name_pool_layout, FILE_NAME)
    return locate_player_records(
        game_db, name_pools.end_offset, registered_player_layout(), FILE_NAME
    )


def synthetic_player_records(record_offsets: tuple[int, ...]) -> PlayerRecords:
    return PlayerRecords(
        record_offsets=array("Q", record_offsets),
        pindexes=array("I", range(len(record_offsets))),
        uids=array("I", range(900100, 900100 + len(record_offsets))),
        markerless_count=0,
        position_by_pindex={},
        position_by_uid={},
        layout=registered_player_layout(),
    )


def buffer_with_entry(entry_offset: int, entry: bytes, *, buffer_length: int = 1000) -> bytes:
    buffer = bytearray(buffer_length)
    buffer[entry_offset : entry_offset + len(entry)] = entry
    return bytes(buffer)


VALID_ENTRY = suspension_entry_bytes(competition_id=1234, issued=packed_date(51, 2031), e7=3, e14=1)
VALID_ENTRY_LOCATED = SuspensionEntry(1234, date(2031, 2, 20), 3, 1)


@pytest.fixture
def suspensions_fragment_path(tmp_path: Path) -> Path:
    sections = [
        SectionFrame("game_db", example_game_db()) if section.name == "game_db" else section
        for section in default_sections()
    ]
    return build_container_fragment(sections).write(tmp_path / "Private Folder" / FILE_NAME)


def test_locate_keeps_only_valid_entries_inside_a_player_window() -> None:
    game_db = example_game_db()
    player_records = example_player_records(game_db)
    assert list(player_records.uids) == [PLAYER_A_UID, PLAYER_B_UID]
    first_record_offset = player_records.record_offsets[0]
    decoy_offset = first_record_offset - BEFORE_FIRST_PLAYER_DECOY_DISTANCE
    # The decoy before the first player really is a well-formed entry.
    assert game_db[decoy_offset : decoy_offset + SUSPENSION_ENTRY_BYTES] == (
        BEFORE_FIRST_PLAYER_DECOY
    )
    entries_start = first_record_offset + 300
    assert game_db[entries_start : entries_start + 2 * SUSPENSION_ENTRY_BYTES] == b"".join(
        PLAYER_A_ENTRIES
    )

    located = locate_suspensions(game_db, player_records, registered_suspension_layout())

    assert dict(located) == {0: EXPECTED_PLAYER_A_ENTRIES}


def test_players_carry_their_unserved_suspensions(suspensions_fragment_path: Path) -> None:
    with fmsave.open(suspensions_fragment_path) as career_save:
        players_table = career_save.players()
    assert players_table.by_uid(PLAYER_A_UID).suspensions == (
        PlayerSuspension(1234, date(2031, 2, 20)),
        PlayerSuspension(4321, date(2030, 11, 2)),
    )
    assert players_table.by_uid(PLAYER_B_UID).suspensions == ()


def test_suspensions_table_lists_each_entry_with_its_player_and_club(
    suspensions_fragment_path: Path,
) -> None:
    with fmsave.open(suspensions_fragment_path) as career_save:
        suspensions_table = career_save.suspensions()
        assert isinstance(suspensions_table, Table)
        assert suspensions_table.record_type is Suspension
        assert career_save.suspensions() is suspensions_table
        assert SUSPENSIONS_TABLE_CACHE_KEY == "table:suspensions"
        assert career_save._context._cache[SUSPENSIONS_TABLE_CACHE_KEY] is suspensions_table
        player_a = career_save.players().by_uid(PLAYER_A_UID)

    assert len(suspensions_table) == 2
    assert [(row.player_uid, row.suspension_competition_id) for row in suspensions_table] == [
        (PLAYER_A_UID, 1234),
        (PLAYER_A_UID, 4321),
    ]
    assert player_a.name == "Alex Example"
    for row in suspensions_table:
        assert row.player_name == player_a.name
        assert row.club_uid == SOUTHPORT_CLUB_UID
        assert row.club_name == "Southport Example"
    first_row = suspensions_table[0]
    second_row = suspensions_table[1]
    assert first_row.issued_date == date(2031, 2, 20)
    assert first_row.unknown == {"e7": 3, "e14": 1}
    assert second_row.issued_date == date(2030, 11, 2)
    assert second_row.unknown == {"e7": 64, "e14": 5}
    filtered = suspensions_table.where(suspension_competition_id=4321)
    assert len(filtered) == 1
    assert filtered[0] == second_row


@pytest.mark.parametrize(
    ("entry_offset", "expected_position"),
    [
        pytest.param(169, None, id="one-byte-before-the-first-window"),
        pytest.param(170, 0, id="first-window-start"),
        pytest.param(469, 0, id="one-byte-before-the-second-window"),
        pytest.param(470, 1, id="second-window-start"),
        pytest.param(980, 1, id="ends-at-the-buffer-end"),
    ],
)
def test_an_entry_belongs_to_the_last_player_whose_window_starts_at_or_before_it(
    entry_offset: int, expected_position: int | None
) -> None:
    """Windows start 30 bytes before each record start (200 and 500 here)."""
    player_records = synthetic_player_records((200, 500))
    located = locate_suspensions(
        buffer_with_entry(entry_offset, VALID_ENTRY),
        player_records,
        registered_suspension_layout(),
    )
    expected = {} if expected_position is None else {expected_position: (VALID_ENTRY_LOCATED,)}
    assert dict(located) == expected


def test_a_signature_whose_entry_would_start_before_offset_zero_is_ignored() -> None:
    """The signature starts 4 bytes into an entry: with the entry's last 16 bytes at offset 0,
    its fields are all valid, and only the entry's negative start rules it out.
    """
    buffer = bytearray(200)
    buffer[0 : SUSPENSION_ENTRY_BYTES - 4] = VALID_ENTRY[4:]
    located = locate_suspensions(
        bytes(buffer), synthetic_player_records((10,)), registered_suspension_layout()
    )
    assert dict(located) == {}


@pytest.mark.parametrize(
    ("competition_id", "issued", "kept_issued_date"),
    [
        pytest.param(1, packed_date(51, 2031), date(2031, 2, 20), id="id-1-kept"),
        pytest.param(59999, packed_date(51, 2031), date(2031, 2, 20), id="id-59999-kept"),
        pytest.param(0, packed_date(51, 2031), None, id="id-0-rejected"),
        pytest.param(60000, packed_date(51, 2031), None, id="id-60000-rejected"),
        pytest.param(
            1234, packed_date(51, 2031, time_slot=5), date(2031, 2, 20), id="time-slot-ignored"
        ),
        pytest.param(1234, packed_date(366, 2032), date(2032, 12, 31), id="day-366-leap-year"),
        pytest.param(1234, packed_date(0, 2031), None, id="day-0-rejected"),
        pytest.param(1234, packed_date(366, 2031), None, id="day-366-non-leap-year-rejected"),
        pytest.param(1234, packed_date(51, 1900), None, id="year-1900-rejected"),
        pytest.param(1234, packed_date(51, 1901), date(1901, 2, 20), id="year-1901-kept"),
        pytest.param(1234, packed_date(51, 2200), date(2200, 2, 20), id="year-2200-kept"),
        pytest.param(1234, packed_date(51, 2201), None, id="year-2201-rejected"),
    ],
)
def test_an_entry_is_kept_only_with_a_valid_date_and_an_id_inside_the_bounds(
    competition_id: int, issued: bytes, kept_issued_date: date | None
) -> None:
    entry = suspension_entry_bytes(competition_id=competition_id, issued=issued, e7=9, e14=6)
    located = locate_suspensions(
        buffer_with_entry(400, entry),
        synthetic_player_records((200,)),
        registered_suspension_layout(),
    )
    expected = (
        {}
        if kept_issued_date is None
        else {0: (SuspensionEntry(competition_id, kept_issued_date, 9, 6),)}
    )
    assert dict(located) == expected


def test_contiguous_entries_keep_their_offset_order_within_each_player() -> None:
    player_records = synthetic_player_records((200, 600))
    buffer = bytearray(1000)
    entries_by_offset = {
        450: suspension_entry_bytes(competition_id=30, issued=packed_date(10, 2031), e7=1, e14=1),
        470: suspension_entry_bytes(competition_id=20, issued=packed_date(20, 2031), e7=2, e14=2),
        490: suspension_entry_bytes(competition_id=10, issued=packed_date(30, 2031), e7=3, e14=3),
        800: suspension_entry_bytes(competition_id=40, issued=packed_date(40, 2031), e7=4, e14=4),
    }
    for entry_offset, entry in entries_by_offset.items():
        buffer[entry_offset : entry_offset + SUSPENSION_ENTRY_BYTES] = entry
    located = locate_suspensions(bytes(buffer), player_records, registered_suspension_layout())
    assert list(located) == [0, 1]
    assert [entry.competition_id for entry in located[0]] == [30, 20, 10]
    assert [entry.competition_id for entry in located[1]] == [40]


def has_signature_at(buffer: bytes, signature_start: int) -> bool:
    """Whether the signature (FF FF, then 05 at +9, FF at +11 and FF at +14) starts here."""
    return (
        buffer[signature_start] == 0xFF
        and buffer[signature_start + 1] == 0xFF
        and buffer[signature_start + 9] == 0x05
        and buffer[signature_start + 11] == 0xFF
        and buffer[signature_start + 14] == 0xFF
    )


@pytest.mark.parametrize(
    ("real_entry", "planted_bytes", "false_signature_distance", "expected_entry"),
    [
        pytest.param(
            # Year 2047 is stored as 0x07FF and e7 0xFF03 puts FF at +8; the false signature's
            # 05 lands on the entry's zero byte at +6.
            suspension_entry_bytes(
                competition_id=1234, issued=packed_date(51, 2047), e7=0xFF03, e14=1
            ),
            {-3: 0xFF, -2: 0xFF, 6: 0x05},
            7,
            SuspensionEntry(1234, date(2047, 2, 20), 0xFF03, 1),
            id="false-signature-3-bytes-before-the-entry",
        ),
        pytest.param(
            # Day 5 puts 05 at +9, year 2047 puts FF at +11 and e14 255 puts FF at +14.
            suspension_entry_bytes(
                competition_id=1234, issued=packed_date(5, 2047), e7=3, e14=0xFF
            ),
            {0: 0xFF, 1: 0xFF},
            4,
            SuspensionEntry(1234, date(2047, 1, 5), 3, 0xFF),
            id="false-signature-at-the-entry-start",
        ),
    ],
)
def test_a_real_entry_overlapped_by_an_earlier_false_signature_is_still_found(
    real_entry: bytes,
    planted_bytes: dict[int, int],
    false_signature_distance: int,
    expected_entry: SuspensionEntry,
) -> None:
    """A false signature that starts fewer than 15 bytes before a real one shares bytes with
    it. The false signature's own entry has no valid issued date, so it is not kept, and the
    real entry behind it must still be found.
    """
    entry_offset = 400
    buffer = bytearray(buffer_with_entry(entry_offset, real_entry))
    for relative_offset, value in planted_bytes.items():
        buffer[entry_offset + relative_offset] = value
    real_signature_start = entry_offset + 4
    false_signature_start = real_signature_start - false_signature_distance
    assert has_signature_at(bytes(buffer), false_signature_start)
    assert has_signature_at(bytes(buffer), real_signature_start)

    located = locate_suspensions(
        bytes(buffer), synthetic_player_records((200,)), registered_suspension_layout()
    )

    assert dict(located) == {0: (expected_entry,)}


@pytest.mark.parametrize(
    ("reader_name", "row_count"),
    [("players", 2), ("contracts", 0), ("suspensions", 2)],
)
def test_readers_raise_save_closed_error_after_close_and_earlier_tables_keep_working(
    suspensions_fragment_path: Path, reader_name: str, row_count: int
) -> None:
    career_save = fmsave.open(suspensions_fragment_path)
    table = getattr(career_save, reader_name)()
    rows_before_close = list(table)
    career_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        getattr(career_save, reader_name)()
    assert len(rows_before_close) == row_count
    assert list(table) == rows_before_close

    never_read_save = fmsave.open(suspensions_fragment_path)
    never_read_save.close()
    with pytest.raises(fmsave.SaveClosedError):
        getattr(never_read_save, reader_name)()


@pytest.mark.parametrize(
    ("layout_changes", "message"),
    [
        pytest.param({"signature": ()}, "signature must not be empty", id="empty-signature"),
        pytest.param(
            {"signature": ((4, 0xFF), (4, 0xFF), (13, 0x05))},
            "signature offset 4 appears more than once",
            id="repeated-signature-offset",
        ),
        pytest.param(
            {"signature": ((-1, 0xFF), (13, 0x05))},
            "signature offset -1 is before the entry start",
            id="negative-signature-offset",
        ),
        pytest.param(
            {"competition_id_offset": 18},
            "field 'competition_id' at offset 18 ends past the last signature byte",
            id="field-past-the-signature",
        ),
        pytest.param(
            {"unknown_e14_offset": 16},
            "overlaps an earlier field",
            id="overlapping-fields",
        ),
        pytest.param(
            {"competition_id_exclusive_range": (60000, 0)},
            "competition_id_exclusive_range .* leaves no competition id strictly between",
            id="inverted-id-range",
        ),
    ],
)
def test_locate_suspensions_rejects_an_inconsistent_layout(
    layout_changes: dict[str, object], message: str
) -> None:
    broken_layout = dataclasses.replace(registered_suspension_layout(), **layout_changes)
    with pytest.raises(ValueError, match=message):
        locate_suspensions(bytes(100), synthetic_player_records((50,)), broken_layout)


@pytest.mark.parametrize("first_reader", ["players", "contracts", "suspensions"])
def test_any_first_reader_decodes_every_player_once_and_fills_all_three_tables(
    suspensions_fragment_path: Path, monkeypatch: pytest.MonkeyPatch, first_reader: str
) -> None:
    decode_calls = [0]
    locate_calls = [0]
    original_decode = PlayerDecoder.decode
    original_locate = save_module.locate_suspensions

    def counting_decode(self: PlayerDecoder, *args: object, **kwargs: object) -> object:
        decode_calls[0] += 1
        return original_decode(self, *args, **kwargs)  # type: ignore[arg-type]

    def counting_locate(*args: object, **kwargs: object) -> object:
        locate_calls[0] += 1
        return original_locate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PlayerDecoder, "decode", counting_decode)
    monkeypatch.setattr(save_module, "locate_suspensions", counting_locate)
    with fmsave.open(suspensions_fragment_path) as career_save:
        first_table = getattr(career_save, first_reader)()
        assert decode_calls[0] == 2  # both players, once each
        assert locate_calls[0] == 1
        cache = career_save._context._cache
        assert {
            PLAYERS_TABLE_CACHE_KEY,
            CONTRACTS_TABLE_CACHE_KEY,
            SUSPENSIONS_TABLE_CACHE_KEY,
        } <= (cache.keys())

        tables_by_reader = {
            "players": career_save.players(),
            "contracts": career_save.contracts(),
            "suspensions": career_save.suspensions(),
        }
        assert decode_calls[0] == 2
        assert locate_calls[0] == 1
        assert tables_by_reader[first_reader] is first_table
        assert tables_by_reader["players"] is cache[PLAYERS_TABLE_CACHE_KEY]
        assert tables_by_reader["contracts"] is cache[CONTRACTS_TABLE_CACHE_KEY]
        assert tables_by_reader["suspensions"] is cache[SUSPENSIONS_TABLE_CACHE_KEY]


def test_field_statuses_follow_the_suspension_coverage() -> None:
    assert field_status(Player, "suspensions") == "verified"
    assert field_status(PlayerSuspension, "suspension_competition_id") == "verified"
    assert field_status(PlayerSuspension, "issued_date") == "verified"
    for verified_field in (
        "player_uid",
        "club_uid",
        "club_name",
        "suspension_competition_id",
        "issued_date",
    ):
        assert field_status(Suspension, verified_field) == "verified", verified_field
    assert field_status(Suspension, "player_name") == "unconfirmed"
    assert field_status(Suspension, "unknown") == "unconfirmed"
    assert Suspension.UNKNOWN_KEYS == ("e7", "e14")


def test_suspension_records_survive_pickle_and_deepcopy(suspensions_fragment_path: Path) -> None:
    with fmsave.open(suspensions_fragment_path) as career_save:
        players_table = career_save.players()
        suspensions_table = career_save.suspensions()
    player_a = players_table.by_uid(PLAYER_A_UID)
    assert player_a.suspensions
    assert len(suspensions_table) == 2
    for example in (player_a.suspensions[0], suspensions_table[0], player_a, suspensions_table):
        copied = pickle.loads(pickle.dumps(example))
        assert copied == example
        assert type(copied) is type(example)
        deep_copied = copy.deepcopy(example)
        assert deep_copied == example
        assert type(deep_copied) is type(example)


def test_export_flattens_player_suspensions_and_suspension_rows(
    suspensions_fragment_path: Path,
) -> None:
    with fmsave.open(suspensions_fragment_path) as career_save:
        players_table = career_save.players()
        suspensions_table = career_save.suspensions()

    assert_matches_json_normalize(list(players_table), Player)
    assert_matches_json_normalize(list(suspensions_table), Suspension)

    player_rows = players_table.to_dicts(json_ready=True)
    assert player_rows[0]["suspensions"] == [
        {"suspension_competition_id": 1234, "issued_date": "2031-02-20"},
        {"suspension_competition_id": 4321, "issued_date": "2030-11-02"},
    ]
    assert player_rows[1]["suspensions"] == []
    suspension_columns = suspensions_table.to_columns()
    assert suspension_columns["unknown_e7"] == [3, 64]
    assert suspension_columns["unknown_e14"] == [1, 5]
    assert suspension_columns["issued_date"] == [date(2031, 2, 20), date(2030, 11, 2)]
