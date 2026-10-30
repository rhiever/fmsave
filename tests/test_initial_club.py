from __future__ import annotations

import struct

import pytest

import fmsave
from fmsave.readers.affiliates import build_affiliate_groups
from fmsave.readers.clubs import find_club_layouts, own_record_spans, read_club_index
from tests.fixtures.club_tables import club_table

LAYOUTS = find_club_layouts(4000, "26.3.2+2329565")


@pytest.mark.parametrize("padding", [0, 64, 1000])
@pytest.mark.parametrize("finance", [0, 1, 2])
def test_initial_club_is_read_from_its_own_table_and_joins(padding: int, finance: int) -> None:
    data = bytes(padding) + club_table(finance=finance)
    index = read_club_index(data, LAYOUTS, "example.fm")
    assert [club.name for club in index.clubs] == ["Example Initial", "Example Following"]
    initial, following = index.clubs
    assert initial.uid == 0
    assert initial.unique_id == 6100
    assert following.uid == 6101
    assert following.unique_id == 6200
    assert index.uid_by_club_index == {0: 0, 1: 6101}
    assert index.team_to_club[71001] == (0, 0)
    assert index.team_to_club[71002] == (6101, 0)
    assert initial.reputation is None
    assert initial.last_league_position is None
    assert initial.gender is not None and initial.gender.raw == 0
    groups, stats = build_affiliate_groups(((0, 1),), index)
    assert groups[0].club_uids == (0, 6101)
    assert stats.members_resolved == 2
    spans = own_record_spans(data, index, LAYOUTS.records)
    assert spans[0].record_start >= 0
    assert spans[0].record_end < spans[1].record_start + 1
    assert fmsave.Table(index.clubs, fmsave.Club).by_uid(0).name == "Example Initial"


def test_invalid_footer_does_not_create_an_initial_club() -> None:
    data = bytearray(club_table())
    first_footer = data.index(struct.pack("<III", 0, 6100, 6100))
    struct.pack_into("<I", data, first_footer, 5)
    with pytest.raises(fmsave.ReaderCheckError):
        read_club_index(bytes(data), LAYOUTS, "example.fm")


@pytest.mark.parametrize("bad_count", [1, 3, 200_001])
def test_bad_table_count_is_rejected(bad_count: int) -> None:
    data = bytearray(club_table())
    struct.pack_into("<I", data, 0, bad_count)
    with pytest.raises(fmsave.ReaderCheckError):
        read_club_index(bytes(data), LAYOUTS, "example.fm")


def test_single_club_table_has_no_dependency_on_a_neighbor() -> None:
    from tests.fixtures.club_tables import club_body

    data = struct.pack("<IB", 1, 0) + club_body("Example Only", "Only", ())
    data += struct.pack("<III", 0, 6300, 6300)
    index = read_club_index(data, LAYOUTS, "example.fm")
    assert [(c.uid, c.unique_id, c.name) for c in index.clubs] == [(0, 6300, "Example Only")]
    assert index.clubs[0].teams == ()


@pytest.mark.parametrize("finance", [0, 1, 2])
def test_extended_initial_club_keeps_its_fields_and_joins(finance: int) -> None:
    ordinary = club_table(finance=finance)
    data = ordinary[:5] + bytes((12,)) + bytes(4) + ordinary[6:]
    index = read_club_index(data, LAYOUTS, "example.fm")
    assert [(c.uid, c.unique_id, c.name) for c in index.clubs] == [
        (0, 6100, "Example Initial"),
        (6101, 6200, "Example Following"),
    ]
    assert index.clubs[0].nation_id == 3
    assert index.team_to_club[71001] == (0, 0)


def test_malformed_later_record_fails_the_whole_table_walk() -> None:
    data = club_table()[:-1]
    with pytest.raises(fmsave.ReaderCheckError):
        read_club_index(data, LAYOUTS, "example.fm")


def test_initial_club_resolves_player_and_contract_joins(tmp_path) -> None:
    from dataclasses import replace

    from tests.fixtures.career import (
        PLAYER_A_UID,
        career_competition_id_pairs,
        career_game_db,
        clubs_region_bytes,
        example_clubs,
    )
    from tests.fixtures.club_tables import club_body
    from tests.fixtures.container import build_container_fragment, default_sections

    native = struct.pack("<IB", 2, 0)
    native += club_body("Example Initial", "Initial", (70003,))
    native += struct.pack("<III", 0, 6100, 6100)
    native += club_body("Example Following", "Following", (70001, 70002))
    native += struct.pack("<III", 1, 6200, 6200)
    original = career_game_db()
    old = clubs_region_bytes(example_clubs(), competition_id_pairs=career_competition_id_pairs())
    assert original.count(old) == 1
    replacement = native + bytes(70_000) + career_competition_id_pairs()
    new = original.replace(old, replacement)
    sections = [replace(s, body=new) if s.name == "game_db" else s for s in default_sections()]
    path = build_container_fragment(sections).write(tmp_path / "example.fm")
    with fmsave.open(path) as save:
        player = save.players().by_uid(PLAYER_A_UID)
        assert player.club_uid == 0
        assert player.club_name == "Example Initial"
        assert player.contract is not None
        assert player.contract.club_uid == 0
        contracts = save.contracts().where(player_uid=PLAYER_A_UID)
        assert len(contracts) == 1
        assert contracts[0].club_uid == 0


def test_initial_record_cannot_be_mistaken_for_a_preceding_footer() -> None:
    from tests.fixtures.club_tables import club_body

    data = bytearray(16)
    data[13] = 1
    data.extend(struct.pack("<IB", 256, 0))
    for ordinal in range(256):
        data.extend(club_body(f"Example Club {ordinal}", f"Example {ordinal}", (71001 + ordinal,)))
        data.extend(struct.pack("<III", ordinal, 6100 + ordinal, 6100 + ordinal))
    index = read_club_index(bytes(data), LAYOUTS, "example.fm")
    assert len(index.clubs) == 256
    assert index.clubs[0].uid == 0
    assert index.clubs[0].unique_id == 6100
    assert index.clubs[-1].unique_id == 6355


@pytest.mark.parametrize("mode", ["ordinal", "duplicate_id", "variant"])
def test_corrupted_table_records_are_rejected(mode: str) -> None:
    data = bytearray(club_table())
    footer = data.index(struct.pack("<III", 1, 6200, 6200))
    if mode == "ordinal":
        struct.pack_into("<I", data, footer, 8)
    elif mode == "duplicate_id":
        struct.pack_into("<II", data, footer + 4, 6100, 6100)
    else:
        previous = data.index(struct.pack("<III", 0, 6100, 6100))
        data[previous + 12] = 7
    with pytest.raises(fmsave.ReaderCheckError):
        read_club_index(bytes(data), LAYOUTS, "example.fm")


def test_validated_table_accepts_a_distinct_random_footer_word() -> None:
    data = bytearray(club_table())
    first = data.index(struct.pack("<III", 0, 6100, 6100))
    struct.pack_into("<I", data, first + 8, 9100)
    index = read_club_index(bytes(data), LAYOUTS, "example.fm")
    assert [(c.uid, c.unique_id) for c in index.clubs] == [(0, 6100), (6101, 6200)]


def test_native_team_list_does_not_come_from_finance_bytes() -> None:
    from tests.fixtures.club_tables import club_body
    from tests.fixtures.game_db import team_list_bytes

    body = bytearray(club_body("Example Initial", "Initial", (71001,), finance=1))
    names_end = 1 + 26 + 4 + len("Example Initial") + 4 + len("Initial")
    history = names_end + 8 + 1 + 1 + 70 + 5
    decoy = team_list_bytes((71999,))
    body[history : history + len(decoy)] = decoy
    data = struct.pack("<IB", 2, 0) + body + struct.pack("<III", 0, 6100, 6100)
    data += club_body("Example Following", "Following", (71002,))
    data += struct.pack("<III", 1, 6200, 6200)
    index = read_club_index(bytes(data), LAYOUTS, "example.fm")
    assert index.team_to_club[71001] == (0, 0)
    assert 71999 not in index.team_to_club


def test_full_save_without_a_valid_club_table_fails_loudly(monkeypatch) -> None:
    import fmsave.readers.clubs as module

    data = bytearray(club_table())
    data[5 + 1 + 26 + 4 + len("Example Initial") + 4 + len("Initial") + 8 + 1] = 7
    monkeypatch.setattr(module, "FULL_SAVE_MINIMUM_GAME_DB_BYTES", len(data))
    with pytest.raises(fmsave.ReaderCheckError):
        read_club_index(bytes(data), LAYOUTS, "example.fm")


def test_large_record_does_not_truncate_later_club_spans() -> None:
    from tests.fixtures.club_tables import club_body

    bodies = [
        club_body("Example Initial", "Initial", (71001,)),
        club_body("Example Large", "Large", (71002,)),
        club_body("Example Last", "Last", (71003,)),
    ]
    bodies[1] = bodies[1][:-2] + struct.pack("<H", 3000) + bytes(3000 * 28)
    data = struct.pack("<IB", 3, 0) + b"".join(
        body + struct.pack("<III", ordinal, uid, uid)
        for ordinal, (body, uid) in enumerate(zip(bodies, (6100, 6200, 6300), strict=True))
    )
    index = read_club_index(data, LAYOUTS, "example.fm")
    assert len(index.clubs) == 3
    assert index.team_to_club[71003] == (6201, 0)
    assert index.record_spans[-1].record_end == len(data) - 12
    assert all(span.record_start < span.record_end for span in index.record_spans)


def test_authenticated_spans_ignore_club_shaped_finance_data() -> None:
    from tests.fixtures.club_tables import club_body
    from tests.fixtures.game_db import club_record_bytes

    body = bytearray(club_body("Example Initial", "Initial", (71001,), finance=1))
    names_end = 1 + 26 + 4 + len("Example Initial") + 4 + len("Initial")
    history = names_end + 8 + 1 + 1 + 70 + 5
    decoy = club_record_bytes(
        club_index=99,
        uid=9100,
        nation_id=3,
        fa_nation_id=3,
        city_id=77,
        name="Example Decoy",
        short_name="Decoy",
        team_ids=(),
    )
    body[history : history + len(decoy)] = decoy
    data = struct.pack("<IB", 2, 0) + body + struct.pack("<III", 0, 6100, 6100)
    data += club_body("Example Following", "Following", (71002,))
    data += struct.pack("<III", 1, 6200, 6200)
    index = read_club_index(bytes(data), LAYOUTS, "example.fm")
    assert [c.name for c in index.clubs] == ["Example Initial", "Example Following"]
    assert index.clubs[0].uid == 0
    spans = own_record_spans(bytes(data), index, LAYOUTS.records)
    assert spans[0].record_end == 5 + len(body)
    assert spans == index.record_spans


def test_table_rows_that_give_no_club_are_counted_by_reason() -> None:
    from fmsave._checks import check_clubs
    from fmsave._layouts import GateBounds, find_layout
    from tests.fixtures.club_tables import club_body

    extended = club_body("Example Extended", "Extended", (71002,))
    extended = bytes((12,)) + bytes(4) + extended[1:]
    unanchored = bytearray(club_body("Example Unanchored", "Unanchored", (71003,)))
    struct.pack_into("<I", unanchored, 5, 5)
    rejected = bytearray(club_body("Example Rejected", "Rejected", (71004,)))
    struct.pack_into("<I", rejected, 1, 1000)
    bodies = [
        club_body("Example Initial", "Initial", (71001,)),
        extended,
        bytes(unanchored),
        bytes(rejected),
        club_body("Example Last", "Last", (71005,)),
    ]
    data = struct.pack("<IB", len(bodies), 0) + b"".join(
        body + struct.pack("<III", ordinal, 6100 + 100 * ordinal, 6100 + 100 * ordinal)
        for ordinal, body in enumerate(bodies)
    )
    index = read_club_index(data, LAYOUTS, "example.fm")
    # Counting the rows must leave the clubs read, and their joins, as they were.
    assert [(c.uid, c.name) for c in index.clubs] == [
        (0, "Example Initial"),
        (6401, "Example Last"),
    ]
    assert set(index.team_to_club) == {71001, 71005}
    stats = index.stats
    assert (stats.table_rows_extended, stats.table_rows_unanchored, stats.table_rows_rejected) == (
        1,
        1,
        1,
    )
    bounds = find_layout(GateBounds, "game_db", 4000, "").layout
    assert dict(check_clubs(stats, bounds, len(data)).anomalies) == {
        "unlinked_affiliate_teams": 0,
        "extended_table_rows": 1,
        "unanchored_table_rows": 1,
        "rejected_table_rows": 1,
    }
