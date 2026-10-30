from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import fmsave
from fmsave._checks import check_season_stats, enforce, evaluate_season_stats
from fmsave._container import ContainerIndex, ContainerLimits, read_index
from fmsave._layouts import GateBounds, find_layout
from fmsave._reader_stats import SeasonStatsStats
from fmsave.checks import validate_save
from fmsave.export import column_names
from fmsave.models.season_stats import PlayerSeasonStats, SeasonStatsKind
from fmsave.readers.season_stats import (
    SeasonPlayer,
    build_season_stats,
    find_season_stats_layout,
    read_season_stats_section,
    walk_season_stats,
)
from tests.fixtures.career import (
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    NORTHBRIDGE_UID,
    PLAYER_A_UID,
    PLAYER_B_UID,
    PLAYER_C_UID,
    PLAYER_D_UID,
    SOUTHPORT_TEAM,
    SOUTHPORT_UID,
    SPAN_SECTION_NAME,
    career_fragment,
)
from tests.fixtures.container import SectionFrame, build_container_fragment, default_sections
from tests.fixtures.season_stats import (
    FOOTER_BYTES,
    OTHER_TEAM_SLOTS,
    OWN_SLOTS,
    ExampleRecord,
    season_stats_body,
    stat_line,
)
from tests.fixtures.span import span_frames

FILE_NAME = "career example.fm"
LAYOUT = find_season_stats_layout("26.3.2+2329565")
OUTFIELD_PINDEX = 11
KEEPER_PINDEX = 12
OUTFIELD_UID = 900001
KEEPER_UID = 900002
OWN_TEAM = 70001
OTHER_TEAM = 70002
UNLISTED_TEAM = 71234


def league_line() -> bytes:
    return stat_line(
        minutes=1080,
        starts=12,
        substitute_appearances=3,
        rated_appearances=15,
        rating_sum=1050,
        goals=4,
        assists=2,
        passes_attempted=500,
        passes_completed=450,
        word_35=40,
        word_37=25,
        word_83=6,
        word_95=12,
        word_71=7,
        word_69=19,
        expected_goals=3.65,
        expected_assists=1.47,
        distance_km=114.7,
        yellow_cards=3,
        red_cards=1,
    )


def own_slots(**lines: bytes) -> tuple[bytes | None, ...]:
    """Eight slots, each named slot filled and the rest absent."""
    order = (
        "non_competitive",
        "league",
        "cup",
        "continental",
        "international",
        "overall",
        "calendar_year_overall",
        "calendar_year_international",
    )
    return tuple(lines.get(name) for name in order)


def example_body() -> bytes:
    outfield = ExampleRecord(
        key=OUTFIELD_PINDEX + 1,
        own_slots=own_slots(league=league_line(), overall=league_line()),
        other_teams=(
            (OTHER_TEAM, (None, stat_line(minutes=90, starts=1), None, None, None, None)),
        ),
    )
    keeper = ExampleRecord(
        key=KEEPER_PINDEX + 1,
        own_slots=own_slots(
            overall=stat_line(minutes=900, starts=10, word_35=16, word_37=20, word_69=8, word_83=57)
        ),
        rating_items=0,
        form_entries=0,
    )
    return season_stats_body([outfield, keeper])


def test_the_walk_reads_every_record_its_slots_and_its_other_teams() -> None:
    walk = walk_season_stats(example_body(), LAYOUT, FILE_NAME)

    assert [record.key for record in walk.records] == [OUTFIELD_PINDEX + 1, KEEPER_PINDEX + 1]
    outfield, keeper = walk.records
    assert len(outfield.own_lines) == OWN_SLOTS
    assert [line is not None for line in outfield.own_lines] == [
        False,
        True,
        False,
        False,
        False,
        True,
        False,
        False,
    ]
    assert [team_id for team_id, _ in outfield.other_teams] == [OTHER_TEAM]
    assert len(outfield.other_teams[0][1]) == OTHER_TEAM_SLOTS
    assert keeper.other_teams == ()


@pytest.mark.parametrize(
    ("damage", "expected_text"),
    [
        pytest.param(lambda body: body[:-1], "footer", id="footer-short"),
        pytest.param(lambda body: body + b"\x00", "footer", id="footer-long"),
        pytest.param(lambda body: body[:8] + b"\x02" + body[9:], "record", id="record-marker"),
    ],
)
def test_a_body_that_does_not_walk_to_its_footer_raises(damage, expected_text: str) -> None:
    with pytest.raises(fmsave.ReaderCheckError) as error_info:
        walk_season_stats(damage(example_body()), LAYOUT, FILE_NAME)
    assert expected_text in str(error_info.value)


def test_a_slot_byte_that_is_neither_absent_nor_a_line_raises() -> None:
    record = ExampleRecord(key=1, own_slots=own_slots(league=b"\x01\x07" + bytes(137)))
    with pytest.raises(fmsave.ReaderCheckError, match="slot"):
        walk_season_stats(season_stats_body([record]), LAYOUT, FILE_NAME)


def test_an_empty_section_walks_to_no_records() -> None:
    walk = walk_season_stats(season_stats_body([]), LAYOUT, FILE_NAME)
    assert walk.records == ()


def rows_by_kind(rows, uid):
    return {row.kind: row for row in rows if row.player_uid == uid and row.team_id == OWN_TEAM}


def example_rows():
    players = {
        OUTFIELD_PINDEX: SeasonPlayer(
            uid=OUTFIELD_UID, name="Alex Example", team_id=OWN_TEAM, goalkeeper=False
        ),
        KEEPER_PINDEX: SeasonPlayer(
            uid=KEEPER_UID, name="Sam Sample", team_id=OWN_TEAM, goalkeeper=True
        ),
    }
    body = example_body()
    return build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, players, {}, {}, LAYOUT
    )


def test_each_present_slot_builds_one_row_labelled_with_its_kind() -> None:
    rows, _ = example_rows()
    outfield = rows_by_kind(rows, OUTFIELD_UID)
    assert set(outfield) == {SeasonStatsKind.LEAGUE, SeasonStatsKind.OVERALL}
    other = [row for row in rows if row.team_id == OTHER_TEAM]
    assert [(row.player_uid, row.kind, row.minutes) for row in other] == [
        (OUTFIELD_UID, SeasonStatsKind.LEAGUE, 90)
    ]


def test_a_line_decodes_to_public_units() -> None:
    rows, _ = example_rows()
    league = rows_by_kind(rows, OUTFIELD_UID)[SeasonStatsKind.LEAGUE]
    assert (league.starts, league.substitute_appearances, league.minutes) == (12, 3, 1080)
    assert league.average_rating == 7.0
    assert (league.goals, league.assists, league.yellow_cards, league.red_cards) == (4, 2, 3, 1)
    assert (league.passes_attempted, league.passes_completed) == (500, 450)
    assert league.expected_goals == 3.65
    assert league.expected_assists == 1.47
    assert league.distance_km == 114.7


def test_an_outfield_line_reads_the_shared_words_as_outfield_stats() -> None:
    rows, _ = example_rows()
    league = rows_by_kind(rows, OUTFIELD_UID)[SeasonStatsKind.LEAGUE]
    assert (league.aerial_challenges_attempted, league.headers_won) == (40, 25)
    assert (league.blocks, league.clearances, league.open_play_crosses_completed) == (6, 12, 7)
    assert (league.saves_held, league.saves_parried, league.saves_tipped) == (None, None, None)
    assert league.shots_on_target_faced is None


def test_a_goalkeeper_line_reads_the_shared_words_as_saves() -> None:
    rows, _ = example_rows()
    overall = rows_by_kind(rows, KEEPER_UID)[SeasonStatsKind.OVERALL]
    assert (overall.saves_held, overall.saves_parried, overall.saves_tipped) == (16, 20, 8)
    assert overall.shots_on_target_faced == 57
    assert (overall.aerial_challenges_attempted, overall.headers_won) == (None, None)
    assert (overall.blocks, overall.clearances, overall.open_play_crosses_completed) == (
        None,
        None,
        None,
    )


def test_an_unrated_line_has_no_average_rating_and_a_negative_prevented_goal_total_is_kept() -> (
    None
):
    record = ExampleRecord(
        key=OUTFIELD_PINDEX + 1,
        own_slots=own_slots(overall=stat_line(minutes=10, expected_goals_prevented=-4.42)),
    )
    body = season_stats_body([record])
    players = {OUTFIELD_PINDEX: SeasonPlayer(OUTFIELD_UID, None, OWN_TEAM, False)}
    rows, _ = build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, players, {}, {}, LAYOUT
    )
    assert rows[0].average_rating is None
    assert rows[0].expected_goals_prevented == -4.42


def test_a_record_whose_key_names_no_player_builds_no_row_and_is_counted() -> None:
    record = ExampleRecord(key=500, own_slots=own_slots(overall=stat_line(minutes=90)))
    body = season_stats_body([record])
    rows, stats = build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, {}, {}, {}, LAYOUT
    )
    assert rows == ()
    assert (stats.records, stats.records_keyed_to_players) == (1, 0)


BOUNDS = find_layout(GateBounds, "game_db", 4000, "").layout
FULL_SIZE_GAME_DB_BYTES = 300 * 1024 * 1024


def career_rows(career_save_path: Path) -> list:
    with fmsave.open(career_save_path) as career_save:
        return list(career_save.player_season_stats())


def test_player_season_stats_builds_a_row_for_every_line_of_every_player(
    career_save_path: Path,
) -> None:
    rows = career_rows(career_save_path)
    summary = sorted((row.player_uid, row.team_id, row.kind.value, row.minutes) for row in rows)
    assert summary == sorted(
        [
            (PLAYER_A_UID, SOUTHPORT_TEAM, "league", 1080),
            (PLAYER_A_UID, SOUTHPORT_TEAM, "overall", 1080),
            (PLAYER_A_UID, NORTHBRIDGE_TEAM_B, "league", 90),
            (PLAYER_C_UID, NORTHBRIDGE_TEAM_A, "league", 45),
            (PLAYER_C_UID, NORTHBRIDGE_TEAM_A, "overall", 45),
            (PLAYER_D_UID, None, "league", 90),
            (PLAYER_D_UID, None, "overall", 90),
        ]
    )
    assert PLAYER_B_UID not in {row.player_uid for row in rows}


def test_each_row_carries_its_team_s_club(career_save_path: Path) -> None:
    rows = career_rows(career_save_path)
    own = next(
        row for row in rows if row.player_uid == PLAYER_A_UID and row.kind.value == "overall"
    )
    other = next(row for row in rows if row.team_id == NORTHBRIDGE_TEAM_B)
    assert (own.club_uid, own.team_slot) == (SOUTHPORT_UID, 0)
    assert (other.club_uid, other.team_slot) == (NORTHBRIDGE_UID, 1)
    assert other.club_name is not None
    free_agent = next(row for row in rows if row.player_uid == PLAYER_D_UID)
    assert (free_agent.club_uid, free_agent.club_name, free_agent.team_slot) == (None, None, None)


def test_the_table_is_read_once_and_the_player_s_name_is_filled(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        first = career_save.player_season_stats()
        assert career_save.player_season_stats() is first
        assert all(row.player_name for row in first)


def test_a_save_without_the_section_raises_a_reader_check_error(tmp_path: Path) -> None:
    save_path = career_fragment(season_stats_section=b"").write(tmp_path / "no stats.fm")
    with (
        fmsave.open(save_path) as career_save,
        pytest.raises(fmsave.ReaderCheckError) as error_info,
    ):
        career_save.player_season_stats()
    assert "season statistics" in str(error_info.value)


def test_validate_reports_the_reader_with_its_record_count(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        report = validate_save(career_save)
    validation = next(item for item in report.readers if item.reader == "player_season_stats")
    assert (validation.status, validation.record_count) == ("ok", 7)
    assert dict(validation.anomalies) == {
        "records_without_a_player": 1,
        "records_repeating_a_key": 0,
        "unresolved_teams": 2,
    }


def healthy_season_stats() -> SeasonStatsStats:
    return SeasonStatsStats(
        records=129_817,
        records_keyed_to_players=129_817,
        players=129_817,
        players_with_record=129_817,
        records_with_overall=97_768,
        overall_sums_competitions=97_768,
        lines=398_715,
        minutes_in_range=398_715,
        rows=398_715,
        teams_resolved=370_388,
        repeated_keys=0,
    )


SEASON_GATE_NAMES = (
    "season_stats_records_keyed_to_players",
    "season_stats_players_with_record",
    "season_stats_overall_sums_competitions",
    "season_stats_minutes_in_range",
)


def test_healthy_season_stats_pass_every_gate_and_a_small_save_applies_none() -> None:
    results = evaluate_season_stats(healthy_season_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert tuple(result.name for result in results) == SEASON_GATE_NAMES
    assert all(result.applied and result.passed for result in results)
    small = evaluate_season_stats(healthy_season_stats(), BOUNDS, 1024)
    assert all(not result.applied for result in small)


@pytest.mark.parametrize(
    ("changes", "failing"),
    [
        pytest.param(
            {"records_keyed_to_players": 120_000},
            "season_stats_records_keyed_to_players",
            id="keys",
        ),
        pytest.param(
            {"players_with_record": 120_000}, "season_stats_players_with_record", id="players"
        ),
        pytest.param(
            {"overall_sums_competitions": 90_000},
            "season_stats_overall_sums_competitions",
            id="sums",
        ),
        pytest.param({"minutes_in_range": 390_000}, "season_stats_minutes_in_range", id="minutes"),
    ],
)
def test_each_season_gate_fails_on_its_own(changes: dict[str, int], failing: str) -> None:
    stats = dataclasses.replace(healthy_season_stats(), **changes)
    results = evaluate_season_stats(stats, BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert [result.name for result in results if not result.passed] == [failing]
    with pytest.raises(fmsave.ReaderCheckError, match=failing):
        enforce("player_season_stats", results, strict=True)


def test_the_reader_check_counts_rows_and_anomalies() -> None:
    check = check_season_stats(healthy_season_stats(), BOUNDS, FULL_SIZE_GAME_DB_BYTES)
    assert (check.reader, check.record_count) == ("player_season_stats", 398_715)
    assert dict(check.anomalies) == {
        "records_without_a_player": 0,
        "records_repeating_a_key": 0,
        "unresolved_teams": 28_327,
    }


def test_an_average_rating_is_the_rating_sum_divided_once_so_it_prints_cleanly() -> None:
    record = ExampleRecord(
        key=OUTFIELD_PINDEX + 1,
        own_slots=own_slots(overall=stat_line(minutes=900, rated_appearances=25, rating_sum=1876)),
    )
    body = season_stats_body([record])
    players = {OUTFIELD_PINDEX: SeasonPlayer(OUTFIELD_UID, None, OWN_TEAM, False)}
    rows, _ = build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, players, {}, {}, LAYOUT
    )
    assert repr(rows[0].average_rating) == "7.504"


def record_with_counts(
    other_teams: int = 0, rating_items: int = 1, form_entries: int = 16
) -> bytes:
    """One record's bytes with its three counts set as given, however large."""
    record = ExampleRecord(key=1, rating_items=0, form_entries=0).to_bytes()
    # Own slots are all absent, so the record is: marker, key, header, 8 zero slots, block,
    # then the three counts with nothing after them.
    head = record[: 1 + 4 + 16 + 8 + 20]
    return (
        head
        + other_teams.to_bytes(4, "little")
        + rating_items.to_bytes(4, "little")
        + bytes(8 * min(rating_items, 1))
        + bytes([form_entries])
    )


@pytest.mark.parametrize(
    ("record", "expected_text"),
    [
        pytest.param(record_with_counts(other_teams=17), "other teams", id="other-teams"),
        pytest.param(record_with_counts(rating_items=257), "rating items", id="rating-items"),
        pytest.param(record_with_counts(form_entries=17), "form list", id="form-entries"),
    ],
)
def test_a_count_above_its_maximum_raises(record: bytes, expected_text: str) -> None:
    body = section_body_bytes(record + b"\x00" + bytes(FOOTER_BYTES))
    with pytest.raises(fmsave.ReaderCheckError, match=expected_text):
        walk_season_stats(body, LAYOUT, FILE_NAME)


def section_body_bytes(payload: bytes) -> bytes:
    return season_stats_body([])[: -1 - FOOTER_BYTES] + payload


@pytest.mark.parametrize(
    "cut",
    [
        pytest.param(8 + 5 + 16 + 3, id="inside-own-slots"),
        pytest.param(8 + 5 + 16 + 139 + 20 + 2, id="inside-other-team-count"),
        pytest.param(8 + 5 + 16 + 139 + 20 + 4 + 3, id="inside-other-team"),
    ],
)
def test_a_body_cut_short_anywhere_raises_a_reader_check_error(cut: int) -> None:
    record = ExampleRecord(
        key=1,
        own_slots=own_slots(league=stat_line(minutes=90)),
        other_teams=((OTHER_TEAM, (None,) * OTHER_TEAM_SLOTS),),
    )
    with pytest.raises(fmsave.ReaderCheckError):
        walk_season_stats(season_stats_body([record])[:cut], LAYOUT, FILE_NAME)


def test_a_repeated_key_builds_rows_once_and_is_counted() -> None:
    line = own_slots(overall=stat_line(minutes=90, starts=1))
    body = season_stats_body([ExampleRecord(key=OUTFIELD_PINDEX + 1, own_slots=line)] * 2)
    players = {OUTFIELD_PINDEX: SeasonPlayer(OUTFIELD_UID, None, OWN_TEAM, False)}
    rows, stats = build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, players, {}, {}, LAYOUT
    )
    assert len(rows) == 1
    assert (stats.records, stats.repeated_keys) == (2, 1)


def span_index(tmp_path: Path, *bodies: bytes) -> ContainerIndex:
    """A container whose span holds one frame per body, after the default span frames."""
    sections = [
        SectionFrame(
            section.name,
            section.body,
            section.extension,
            (*section.unlisted_frames_after, *span_frames(list(bodies)))
            if section.name == SPAN_SECTION_NAME
            else section.unlisted_frames_after,
        )
        for section in default_sections()
    ]
    return read_index(build_container_fragment(sections).write(tmp_path / "span.fm"))


def test_the_one_frame_that_walks_is_read_when_another_carries_the_header(
    tmp_path: Path,
) -> None:
    good = example_body()
    broken = good[:-1]
    body, walk = read_season_stats_section(span_index(tmp_path, broken, good), LAYOUT)
    assert body == good
    assert len(walk.records) == 2


def test_two_frames_that_both_walk_raise(tmp_path: Path) -> None:
    with pytest.raises(fmsave.ReaderCheckError, match="2 frames"):
        read_season_stats_section(span_index(tmp_path, example_body(), example_body()), LAYOUT)


def test_a_lone_frame_that_does_not_walk_raises_its_own_error(tmp_path: Path) -> None:
    with pytest.raises(fmsave.ReaderCheckError, match="footer"):
        read_season_stats_section(span_index(tmp_path, example_body()[:-1]), LAYOUT)


def test_frames_that_carry_the_header_count_against_the_total_cap(tmp_path: Path) -> None:
    frame_bytes = 64 * 1024
    broken = example_body()[:-1]
    padded = broken + bytes(frame_bytes - len(broken))
    path = span_index(tmp_path, *[padded] * 4).path
    declared_total = sum(entry.decompressed_size for entry in read_index(path).entries)
    index = read_index(
        path, ContainerLimits(total_decompressed_cap=declared_total + 2 * frame_bytes)
    )
    with pytest.raises(fmsave.CorruptSaveError, match="total decompression cap"):
        read_season_stats_section(index, LAYOUT)


def overall_row(**values: float) -> PlayerSeasonStats:
    record = ExampleRecord(
        key=OUTFIELD_PINDEX + 1, own_slots=own_slots(overall=stat_line(**values))
    )
    body = season_stats_body([record])
    players = {OUTFIELD_PINDEX: SeasonPlayer(OUTFIELD_UID, None, OWN_TEAM, False)}
    rows, _ = build_season_stats(
        walk_season_stats(body, LAYOUT, FILE_NAME), body, players, {}, {}, LAYOUT
    )
    return rows[0]


def test_rates_are_worked_out_from_the_counts_on_access() -> None:
    row = overall_row(
        minutes=1800,
        goals=10,
        shots=40,
        shots_on_target=16,
        passes_attempted=800,
        passes_completed=680,
        tackles_attempted=50,
        tackles_completed=40,
        expected_goals=8.0,
        word_35=60,
        word_37=45,
    )
    assert row.goals_per_90 == 0.5
    assert row.expected_goals_per_90 == 0.4
    assert row.pass_completion_percent == 85.0
    assert row.shots_on_target_percent == 40.0
    assert row.tackle_completion_percent == 80.0
    assert row.tackles_completed_per_90 == 2.0
    assert row.headers_won_percent == 75.0
    assert row.headers_lost_per_90 == 0.75
    assert row.expected_goals_per_shot == 0.2


def test_possession_lost_and_non_penalty_xg_decode_with_their_rates() -> None:
    row = overall_row(
        minutes=1350,
        possession_lost=180,
        possession_won=120,
        expected_goals=6.4,
        non_penalty_expected_goals=4.8,
        penalties_taken=2,
    )
    assert (row.possession_lost, row.possession_won) == (180, 120)
    assert (row.expected_goals, row.non_penalty_expected_goals) == (6.4, 4.8)
    assert row.possession_lost_per_90 == 12.0
    assert row.possession_won_per_90 == 8.0
    assert row.non_penalty_expected_goals_per_90 == pytest.approx(0.32)


def test_a_rate_with_nothing_to_divide_by_is_none() -> None:
    row = overall_row(minutes=0, goals=0)
    assert row.goals_per_90 is None
    assert row.possession_lost_per_90 is None
    assert row.non_penalty_expected_goals_per_90 is None
    assert row.pass_completion_percent is None
    assert row.save_percent is None


def test_a_goalkeeper_gets_save_rates_and_no_outfield_rates() -> None:
    rows, _ = example_rows()
    keeper = rows_by_kind(rows, KEEPER_UID)[SeasonStatsKind.OVERALL]
    assert keeper.save_percent == pytest.approx(100 * 44 / 57)
    assert keeper.blocks_per_90 is None
    assert keeper.headers_won_percent is None


def test_every_rate_is_exported_and_has_a_status() -> None:
    names = column_names(PlayerSeasonStats)
    assert names[-len(PlayerSeasonStats.COMPUTED_FIELDS) :] == PlayerSeasonStats.COMPUTED_FIELDS
    assert len(PlayerSeasonStats.COMPUTED_FIELDS) == 46
    for name in PlayerSeasonStats.COMPUTED_FIELDS:
        assert fmsave.field_status(PlayerSeasonStats, name) in ("verified", "unconfirmed")
