from __future__ import annotations

import dataclasses
import struct

import pytest

import fmsave
from fmsave.readers import season_history as history
from fmsave.readers.season_stats import SeasonPlayer, find_season_stats_layout
from tests.fixtures.season_history import history_archive, history_index, history_unit

FILE_NAME = "fictional history.fm"
BUILD = "26.3.2+2329565"


def test_history_index_uses_adjacent_words_and_preserves_order() -> None:
    walk = history.walk_history_index(history_index([(304, 152, 456, 0)]), FILE_NAME)
    assert walk.lists == ((304, 152, 456, 0),)


def test_history_index_accepts_wrapped_encoded_words() -> None:
    walk = history.walk_history_index(
        history_index([(304, 0xFFFFFF68, 608)], encoded=True), FILE_NAME
    )
    assert walk.lists == ((304, 152, 456),)


@pytest.mark.parametrize("cut", [0, 7, 8, 10, 13, 17, 23, -1])
def test_history_index_rejects_truncation(cut: int) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        history.walk_history_index(history_index([(0, 152)])[:cut], FILE_NAME)


@pytest.mark.parametrize(
    "damage",
    [
        lambda data: data[:8] + struct.pack("<I", 0xFFFFFFFF) + data[12:],
        lambda data: data[:-6] + struct.pack("<I", 139) + data[-2:],
        lambda data: data[:-2] + b"\x00\x06",
        lambda data: data + b"\x00",
    ],
    ids=["count", "unit", "footer", "trailing"],
)
def test_history_index_rejects_malformed_counts_unit_size_or_footer(damage) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        history.walk_history_index(damage(history_index([(0,)])), FILE_NAME)


def build_rows(units, lists, selectors, *, players=None):
    return history.build_history(
        history.walk_history_index(history_index(lists), FILE_NAME),
        history_archive(units),
        selectors,
        players or {900001: SeasonPlayer(900001, "Alex Example", 70002, False)},
        {},
        {},
        find_season_stats_layout(BUILD),
        FILE_NAME,
    )


def test_history_decodes_metadata_transfers_and_reuses_rates() -> None:
    units = [
        history_unit(
            team=70001,
            year=2031,
            starts=2,
            minutes=180,
            goals=3,
            rated_appearances=2,
            rating_sum=146,
            expected_goals=1.25,
        ),
        history_unit(team=70003, year=2029, kind=2, starts=1, minutes=90, assists=2),
    ]
    rows, counts = build_rows(units, [(0, 152)], {900001: 0})
    assert [(r.team_id, r.season_year, r.kind.value) for r in rows] == [
        (70001, 2031, "league"),
        (70003, 2029, "cup"),
    ]
    row = rows[0]
    assert isinstance(row, fmsave.PlayerSeasonHistory)
    assert row.competition_reference == 43
    assert (row.average_rating, row.expected_goals, row.goals_per_90) == (7.3, 1.25, 1.5)
    assert (row.player_name, row.club_uid, row.saves_held) == ("Alex Example", None, None)
    assert counts.rows == 2
    assert counts.unresolved_teams == 2
    for field in (*[f.name for f in dataclasses.fields(row)], *row.COMPUTED_FIELDS):
        assert fmsave.field_status(type(row), field) in ("verified", "unconfirmed")
    for field in ("season_year", "competition_reference"):
        assert fmsave.field_status(type(row), field) == "unconfirmed"


def test_history_goalkeeper_uses_shared_goalkeeper_words_and_sparse_minutes() -> None:
    rows, _ = build_rows(
        [history_unit(minutes=90, word_35=7, word_37=8, word_69=9, word_83=10)],
        [(0,)],
        {900001: 0},
        players={900001: SeasonPlayer(900001, None, None, True)},
    )
    row = rows[0]
    assert (row.saves_held, row.saves_parried, row.saves_tipped, row.shots_on_target_faced) == (
        7,
        8,
        9,
        10,
    )
    assert row.aerial_challenges_attempted is None
    assert row.average_rating is None


@pytest.mark.parametrize("offsets", [(1,), (152,), (0, 0)])
def test_history_rejects_misaligned_out_of_range_and_duplicate_offsets(offsets) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows([history_unit()], [offsets], {900001: 0})


def test_history_rejects_duplicate_nonempty_list_ownership() -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows(
            [history_unit()],
            [(0,)],
            {900001: 0, 900002: 0},
            players={uid: SeasonPlayer(uid, None, None, False) for uid in (900001, 900002)},
        )


def test_history_rejects_invalid_selector() -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows([history_unit()], [(0,)], {900001: 1})


def test_history_empty_and_absent_lists_have_no_rows() -> None:
    rows, counts = build_rows([], [()], {900001: 0xFFFFFFFF})
    assert rows == ()
    assert counts.rows == 0


@pytest.mark.parametrize(
    "damage",
    [
        lambda unit: b"\x01" + unit[1:],
        lambda unit: unit[:31] + b"\x05" + unit[32:],
        lambda unit: unit[:-1],
    ],
    ids=["marker", "kind", "length"],
)
def test_history_rejects_bad_archive_records(damage) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows([damage(history_unit())], [(0,)], {900001: 0})


def test_history_rejects_offsets_shared_by_separately_owned_lists() -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows(
            [history_unit()],
            [(0,), (0,)],
            {900001: 0, 900002: 1},
            players={uid: SeasonPlayer(uid, None, None, False) for uid in (900001, 900002)},
        )


def test_history_validates_unowned_archive_units() -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        build_rows([history_unit(kind=8)], [()], {900001: 0})


def test_save_history_joins_validated_players_and_caches(tmp_path) -> None:
    from tests.fixtures.career import PLAYER_A_UID, career_fragment

    path = career_fragment(
        history_archive_section=history_archive([history_unit(minutes=180, starts=2)]),
        history_index_section=history_index([(0,)]),
        player_history_selectors=(0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
    ).write(tmp_path / "history.fm")
    with fmsave.open(path, strict=True) as save:
        table = save.player_season_history()
        assert len(table) == 1
        assert table[0].player_uid == PLAYER_A_UID
        assert table[0].player_name == save.players().by_uid(PLAYER_A_UID).name
        assert save.player_season_history() is table
    assert table[0].minutes == 180
    with pytest.raises(fmsave.SaveClosedError):
        save.player_season_history()


@pytest.mark.parametrize("missing", ["archive", "index"])
def test_save_history_requires_archive_and_unique_index(tmp_path, missing) -> None:
    from tests.fixtures.career import career_fragment

    path = career_fragment(
        history_archive_section=b"" if missing == "archive" else None,
        history_index_section=b"" if missing == "index" else None,
    ).write(tmp_path / "missing.fm")
    with fmsave.open(path) as save, pytest.raises(fmsave.ReaderCheckError):
        save.player_season_history()


def test_history_selector_uses_validated_block_start_and_window_bounds() -> None:
    layout = history.find_history_layout(BUILD)
    body = bytearray(100)
    struct.pack_into("<I", body, 29, 7)
    struct.pack_into("<I", body, 21, 19)
    assert history.history_selector(bytes(body), 50, 0, 100, layout) == 7
    assert history.history_selector(bytes(body), 50, 30, 100, layout) == 0xFFFFFFFF
    assert history.history_selector(bytes(body), None, 0, 100, layout) == 0xFFFFFFFF


def test_history_free_words_are_not_archive_offsets() -> None:
    index = history.walk_history_index(history_index([], free=[1, 7, 0xFFFFFFFF]), FILE_NAME)
    rows, _ = history.build_history(
        index, history_archive(), {}, {}, {}, {}, find_season_stats_layout(BUILD), FILE_NAME
    )
    assert rows == ()


def test_history_rejects_repeated_single_references() -> None:
    index = history.walk_history_index(history_index([], singles=[0, 0]), FILE_NAME)
    with pytest.raises(fmsave.ReaderCheckError):
        history.build_history(
            index,
            history_archive([history_unit()]),
            {},
            {},
            {},
            {},
            find_season_stats_layout(BUILD),
            FILE_NAME,
        )


@pytest.mark.parametrize(
    "scope,expected",
    [
        (["--all"], 1),
        (["--club", "5002"], 1),
        (["--club", "5001"], 0),
    ],
    ids=["all", "current-club", "historical-club"],
)
def test_cli_history_scope_tracks_current_player_membership(
    tmp_path, capsys, scope, expected
) -> None:
    import csv
    import io

    from fmsave import cli
    from tests.fixtures.career import career_fragment

    path = career_fragment(
        history_archive_section=history_archive([history_unit(minutes=180, starts=2, goals=4)]),
        history_index_section=history_index([(0,)]),
        player_history_selectors=(0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
    ).write(tmp_path / "history.fm")
    code = cli.main(["export", str(path), "player-season-history", *scope])
    output = capsys.readouterr()
    assert code == 0, output.err
    rows = list(csv.DictReader(io.StringIO(output.out)))
    assert len(rows) == expected
    if rows:
        assert rows[0]["season_year"] == "2030"
        assert rows[0]["goals_per_90"] == "2.0"


def test_history_validation_reports_structural_anomalies(tmp_path) -> None:
    from tests.fixtures.career import career_fragment

    path = career_fragment(
        history_archive_section=history_archive([history_unit(), history_unit(team=12345)]),
        history_index_section=history_index([(0,), (152,)]),
        player_history_selectors=(0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
    ).write(tmp_path / "history.fm")
    with fmsave.open(path, strict=True) as save:
        report = fmsave.validate_save(save)
    checked = next(row for row in report.readers if row.reader == "player_season_history")
    assert (checked.status, checked.record_count, checked.gates) == ("ok", 1, ())
    assert checked.anomalies["unowned_archive_units"] == 1
    assert checked.anomalies["unowned_history_lists"] == 1
    assert checked.anomalies["players_without_history"] == 3
    assert checked.coverage["season_year"] == 1.0


def index_container(tmp_path, bodies, *, game_db=None, archive=None):
    from tests.fixtures.career import SPAN_SECTION_NAME
    from tests.fixtures.container import SectionFrame, build_container_fragment, default_sections
    from tests.fixtures.span import span_frames

    sections = [
        SectionFrame(
            section.name,
            game_db if section.name == "game_db" and game_db is not None else section.body,
            section.extension,
            (*section.unlisted_frames_after, *span_frames(bodies))
            if section.name == SPAN_SECTION_NAME
            else section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    sections.append(
        SectionFrame(
            "player_stats_hist_dt", history_archive() if archive is None else archive, ".cmt"
        )
    )
    return build_container_fragment(sections).write(tmp_path / "indexed.fm")


def test_history_index_accepts_only_one_complete_structural_walk(tmp_path) -> None:
    from fmsave._container import read_index

    good = history_index([(0,)])
    path = index_container(tmp_path, [good[:-1], good])
    assert history.read_history_index(
        read_index(path), history.find_history_layout(BUILD)
    ).lists == ((0,),)


def test_history_index_rejects_ambiguous_complete_frames(tmp_path) -> None:
    from fmsave._container import read_index

    path = index_container(tmp_path, [history_index(), history_index()])
    with pytest.raises(fmsave.ReaderCheckError, match="2 frames"):
        history.read_history_index(read_index(path), history.find_history_layout(BUILD))


@pytest.mark.parametrize("object_kind", [2, 3])
def test_history_ownership_accepts_distinct_identity_copy_words(tmp_path, object_kind) -> None:
    from tests.fixtures.career import PLAYER_A_UID, career_game_db

    body = bytearray(
        career_game_db(player_history_selectors=(0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF))
    )
    identity_at = body.index(struct.pack("<II", PLAYER_A_UID, PLAYER_A_UID))
    allocated_uid = 2_000_000_123
    struct.pack_into("<II", body, identity_at, allocated_uid, 810123)
    body[identity_at + 8] = object_kind
    path = index_container(
        tmp_path,
        [history_index([(0,)])],
        game_db=bytes(body),
        archive=history_archive([history_unit(starts=2, minutes=180)]),
    )
    with fmsave.open(path, strict=True) as save:
        row = save.player_season_history()[0]
        assert (row.player_uid, row.minutes) == (allocated_uid, 180)


def test_validated_person_anchor_resets_when_a_later_window_has_no_person() -> None:
    from tests.test_persons import PLAYER_A_BLOCK, build_decoder, game_db_prefix

    prefix = game_db_prefix()
    body = prefix + PLAYER_A_BLOCK + bytes(100)
    decoder = build_decoder(body)
    assert decoder.decode(body, len(prefix), len(prefix) + len(PLAYER_A_BLOCK)) is not None
    assert decoder.last_block_start is not None
    assert decoder.decode(body, len(prefix) + len(PLAYER_A_BLOCK), len(body)) is None
    assert decoder.last_block_start is None


@pytest.mark.parametrize(
    "header",
    [
        b"\x03\x01tad.\x06\x00",
        b"\x03\x01tmc.\x05\x00",
        b"\x03\x01tmc.\x07\x00",
        b"\x03\x00tmc.\x06\x00",
    ],
    ids=["wrong-tag", "older-schema", "newer-schema", "wrong-marker"],
)
def test_history_archive_rejects_other_headers(header) -> None:
    index = history.walk_history_index(history_index(), FILE_NAME)
    with pytest.raises(fmsave.ReaderCheckError):
        history.build_history(
            index, header, {}, {}, {}, {}, find_season_stats_layout(BUILD), FILE_NAME
        )


@pytest.mark.parametrize(
    "position", [8, 12, 16, 24], ids=["singles", "lists", "list-items", "free"]
)
def test_history_index_bounds_each_count_before_allocating(position) -> None:
    body = bytearray(history_index([(0,)]))
    struct.pack_into("<I", body, position, 0xFFFFFFFF)
    with pytest.raises(fmsave.ReaderCheckError):
        history.walk_history_index(bytes(body), FILE_NAME)


@pytest.mark.parametrize(
    "header",
    [
        b"\x03\x01tmc.\x04\x00",
        b"\x03\x01tad.\x03\x00",
        b"\x03\x01tad.\x05\x00",
    ],
    ids=["wrong-tag", "older-schema", "newer-schema"],
)
def test_history_index_rejects_other_headers(header) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        history.walk_history_index(header + history_index()[8:], FILE_NAME)


def test_history_does_not_search_inside_frames_for_ownership(tmp_path) -> None:
    from fmsave._container import read_index

    path = index_container(tmp_path, [b"prefix" + history_index()])
    with pytest.raises(fmsave.ReaderCheckError, match="no history index frame"):
        history.read_history_index(read_index(path), history.find_history_layout(BUILD))


def test_history_single_and_list_references_cannot_alias() -> None:
    index = history.walk_history_index(history_index([(0,)], singles=[0]), FILE_NAME)
    with pytest.raises(fmsave.ReaderCheckError):
        history.build_history(
            index,
            history_archive([history_unit()]),
            {},
            {},
            {},
            {},
            find_season_stats_layout(BUILD),
            FILE_NAME,
        )


@pytest.mark.parametrize(
    "kind,expected",
    [
        (0, "non_competitive"),
        (1, "league"),
        (2, "cup"),
        (3, "continental"),
        (4, "international"),
    ],
)
def test_history_decodes_each_archived_competition_kind(kind, expected) -> None:
    rows, _ = build_rows([history_unit(kind=kind)], [(0,)], {900001: 0})
    assert rows[0].kind.value == expected


def test_history_can_share_an_empty_list_without_duplicate_rows() -> None:
    rows, counts = build_rows(
        [],
        [()],
        {900001: 0, 900002: 0},
        players={uid: SeasonPlayer(uid, None, None, False) for uid in (900001, 900002)},
    )
    assert rows == ()
    assert counts.players_without_history == 2


def test_failed_history_cache_does_not_retain_archive_traceback_frames(
    tmp_path, monkeypatch
) -> None:
    import fmsave._context as context_module
    from tests.fixtures.career import career_fragment

    path = career_fragment(
        history_archive_section=history_archive([history_unit(kind=5)]),
        history_index_section=history_index([(0,)]),
        player_history_selectors=(0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
    ).write(tmp_path / "malformed-history.fm")
    reads = []
    read_section = context_module.read_section

    def count_archive(index, name):
        if name == "player_stats_hist_dt":
            reads.append(name)
        return read_section(index, name)

    monkeypatch.setattr(context_module, "read_section", count_archive)
    with fmsave.open(path) as save:
        for _ in range(3):
            with pytest.raises(fmsave.ReaderCheckError, match="unexpected marker or kind"):
                save.player_season_history()
            assert save._context._loaned_sections == {}
            failures = [
                value
                for value in save._context._cache.values()
                if isinstance(value, context_module._FailedBuild)
            ]
            assert failures
            for failed in failures:
                assert failed.error.__traceback__ is None
                assert failed.error.__cause__ is None
                assert failed.error.__context__ is None
    assert reads == ["player_stats_hist_dt"]


@pytest.mark.parametrize("following_kind", [16, 1, 8])
@pytest.mark.parametrize("has_own_person", [False, True], ids=["missing-own", "valid-own"])
def test_person_and_history_are_not_borrowed_from_object_after_closure(
    tmp_path,
    following_kind,
    has_own_person,
) -> None:
    from tests.fixtures.container import packed_date, section_body
    from tests.fixtures.game_db import person_block_bytes, player_record_bytes
    from tests.test_persons import game_db_prefix
    from tests.test_players import PLAYER_A, closing_header_bytes

    def block(first_name, surname):
        return person_block_bytes(
            first_name_id=first_name,
            surname_id=surname,
            common_name_id=0xFFFFFFFF,
            legal_name=None,
            birth=packed_date(60, 2005),
            nation_id=44,
            personality=(15, 12, 9, 20, 18, 7, 11, 3),
            trait_bits=0,
            relations=(),
            history_selector=0,
        )

    own_person = block(1, 1) if has_own_person else b""
    neighbor = block(0, 0)
    region = player_record_bytes(
        **{
            **PLAYER_A,
            "trailing": own_person + closing_header_bytes(12, 900002, following_kind) + neighbor,
        }
    )
    path = index_container(
        tmp_path,
        [history_index([(0,)])],
        game_db=section_body(".dat", 4000, game_db_prefix() + region),
        archive=history_archive([history_unit(starts=1, minutes=90)]),
    )
    with fmsave.open(path, strict=True) as save:
        player = save.players().by_uid(900001)
        assert player.unique_id == 900002
        assert player.name == ("Sam Sample" if has_own_person else None)
        rows = save.player_season_history()
        assert len(rows) == (1 if has_own_person else 0)
        if rows:
            assert rows[0].player_name == "Sam Sample"
