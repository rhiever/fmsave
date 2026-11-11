from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import fmsave
from fmsave.cli import main
from fmsave.export import column_names
from tests.fixtures.career import career_fragment
from tests.fixtures.container import section_body, zstd

HOME_TEAM = 701
AWAY_TEAM = 702
COMPETITION = 31
KICK_OFF = datetime.datetime(2031, 3, 1, 15, 0)  # noqa: DTZ001 - the save stores naive local times
HOME_FIRST_ANCHOR = 600
SUMMARY_GAP = 535
DETAIL_MARKERS = (203, 199, 195, 191, 183)
PAGE_MARKER = b"\x00\x00\xf4\x01"


@dataclass(frozen=True)
class ExamplePlayer:
    shots: int = 0
    on_target: int = 0
    blocked: int = 0
    outside_box: int = 0
    clear_cut: int = 0
    fouls: int = 0
    offsides: int = 0
    yellow: int = 0
    red: int = 0
    crosses: tuple[int, int] = (0, 0)
    tackles: tuple[int, int] = (0, 0)
    aerials: tuple[int, int] = (0, 0)
    xg: float = 0.0
    npxg: float = 0.0
    distance: float = 0.0
    progressive: int = 0
    events: tuple[int, ...] = ()
    optional_block: bool = False

    def length(self, inserted: int = 0) -> int:
        events = sum(3 + 15 * count for count in self.events)
        return 214 + inserted + events + 11 * self.optional_block


@dataclass(frozen=True)
class ExampleTeam:
    players: tuple[ExamplePlayer, ...]
    woodwork: int = 0
    corners: int = 0
    passes: tuple[int, int] = (0, 0)
    final_third: int = 0
    ball_units: int = 0


@dataclass(frozen=True)
class ExampleReport:
    home: ExampleTeam
    away: ExampleTeam
    kick_off: datetime.datetime = KICK_OFF
    competition_id: int = COMPETITION
    home_team_id: int = HOME_TEAM
    away_team_id: int = AWAY_TEAM
    detailed: bool = False
    gap: int = SUMMARY_GAP
    trailing_walk: int = 0
    extra: dict[int, bytes] = field(default_factory=dict)
    # FM27 records hold this many bytes more, from 77 bytes past the anchor.
    inserted: int = 0


def squad(count: int = 11, **values: object) -> tuple[ExamplePlayer, ...]:
    return tuple(ExamplePlayer(**values) for _ in range(count))  # type: ignore[arg-type]


def _write_player(report: bytearray, anchor: int, player: ExamplePlayer, inserted: int = 0) -> None:
    report[anchor + 1 : anchor + 9] = b"\xff" * 8
    report[anchor + 9] = report[anchor + 22] = 0x02
    for offset, value in (
        (-59, player.shots),
        (-58, player.on_target),
        (-57, player.blocked),
        (-56, player.outside_box),
        (-55, player.clear_cut),
        (-40, player.fouls),
        (-38, player.offsides),
        (-37, player.yellow),
        (-36, player.red),
        (-11, player.crosses[0]),
        (-10, player.crosses[1]),
        (-8, player.tackles[0]),
        (-7, player.tackles[1]),
        (-5, player.aerials[0]),
        (-4, player.aerials[1]),
        (78 + inserted, player.progressive),
    ):
        report[anchor + offset] = value
    struct.pack_into("<f", report, anchor - 75, player.xg)
    struct.pack_into("<f", report, anchor + 103 + inserted, player.npxg)
    struct.pack_into("<f", report, anchor + 40, player.distance)
    at = anchor + 108 + inserted
    report[at] = len(player.events)
    at += 1
    for count in player.events:
        report[at + 2] = count
        at += 3 + 15 * count
    report[at + 4] = int(player.optional_block)


def _write_team(report: bytearray, first_anchor: int, team: ExampleTeam, inserted: int) -> int:
    report[first_anchor - 393] = team.woodwork
    report[first_anchor - 383] = team.corners
    struct.pack_into("<H", report, first_anchor - 364, team.passes[0])
    struct.pack_into("<H", report, first_anchor - 362, team.passes[1])
    struct.pack_into("<H", report, first_anchor - 348, team.ball_units)
    struct.pack_into("<H", report, first_anchor - 260, team.final_third)
    anchor = first_anchor
    for player in team.players:
        _write_player(report, anchor, player, inserted)
        anchor += player.length(inserted)
    return anchor


def report_bytes(example: ExampleReport) -> bytes:
    home_length = sum(player.length(example.inserted) for player in example.home.players)
    away_length = sum(player.length(example.inserted) for player in example.away.players)
    size = HOME_FIRST_ANCHOR + home_length + example.gap + away_length + 600
    report = bytearray(size)
    minutes = int((example.kick_off - datetime.datetime(1, 1, 1)).total_seconds()) // 60  # noqa: DTZ001
    struct.pack_into("<I", report, 11, minutes)
    report[37] = 0x02
    struct.pack_into("<I", report, 38, example.competition_id)
    report[100:106] = b"\x03\x02" + struct.pack("<I", example.home_team_id)
    report[123:129] = b"\x03\x02" + struct.pack("<I", example.away_team_id)
    if example.detailed:
        for back in DETAIL_MARKERS:
            report[HOME_FIRST_ANCHOR - back] = 0xFF
    home_end = _write_team(report, HOME_FIRST_ANCHOR, example.home, example.inserted)
    away_end = _write_team(report, home_end + example.gap, example.away, example.inserted)
    for index in range(example.trailing_walk):
        _write_player(report, away_end + 100 + 214 * index, ExamplePlayer())
    for at, value in example.extra.items():
        report[at : at + len(value)] = value
    return bytes(report)


def store(*pages: list[bytes], page_count: int | None = None) -> bytes:
    """A match report store whose pages each hold these frames, in order."""
    payload = struct.pack("<I", 9_000) + b"\x01\x01"
    payload += struct.pack("<I", len(pages) if page_count is None else page_count)
    for page, frames in enumerate(pages):
        if page:
            payload += b"\x01"
        name = f"pks_{page}".encode()
        entries = b""
        data = b""
        for index, frame in enumerate(frames):
            entries += struct.pack("<III", 100 * page + index, len(data), len(frame))
            data += frame
        payload += (
            struct.pack("<II", page, len(name))
            + name
            + PAGE_MARKER
            + b"\x01\x01"
            + struct.pack("<I", len(frames))
            + entries
            + PAGE_MARKER
            + struct.pack("<I", len(data))
            + b"\x03"
            + bytes(4)
            + data
        )
    return section_body(".dat", 6, payload)


def frame(example: ExampleReport) -> bytes:
    return zstd.compress(report_bytes(example))


def summary_match(**changes: object) -> ExampleReport:
    home = ExampleTeam(
        players=(
            ExamplePlayer(
                shots=3,
                on_target=2,
                blocked=1,
                outside_box=1,
                clear_cut=1,
                fouls=2,
                yellow=1,
                crosses=(4, 1),
                tackles=(3, 2),
                aerials=(5, 3),
                xg=0.5,
                npxg=0.25,
                distance=10.0,
                progressive=7,
            ),
            *squad(10, shots=1, xg=0.125, npxg=0.125, distance=8.5, offsides=1),
        ),
        woodwork=1,
        corners=6,
        passes=(500, 450),
        final_third=80,
        ball_units=5,
    )
    away = ExampleTeam(
        players=squad(12, shots=1, red=0, distance=9.0, tackles=(2, 1)),
        corners=2,
        passes=(400, 349),
        final_third=40,
        ball_units=3,
    )
    values: dict[str, object] = {"home": home, "away": away}
    values.update(changes)
    return ExampleReport(**values)  # type: ignore[arg-type]


def open_store(tmp_path: Path, section: bytes, *, strict: bool = False) -> fmsave.Save:
    path = career_fragment(match_stats_section=section).write(tmp_path / "example.fm")
    return fmsave.open(path, strict=strict)


def test_a_summary_report_gives_one_row_per_team(tmp_path: Path) -> None:
    with open_store(tmp_path, store([frame(summary_match())])) as save:
        rows = save.team_match_stats()
        assert rows is save.team_match_stats()

    home, away = rows
    assert (home.team_id, home.is_home, away.team_id, away.is_home) == (
        HOME_TEAM,
        True,
        AWAY_TEAM,
        False,
    )
    for row in rows:
        assert (row.competition_id, row.home_team_id, row.away_team_id) == (
            COMPETITION,
            HOME_TEAM,
            AWAY_TEAM,
        )
        assert (row.date, row.kick_off_time) == (KICK_OFF.date(), KICK_OFF.time())
        assert row.detailed_report is False
        assert row.progressive_passes is None
    assert home.players == 11
    assert (home.shots, home.shots_on_target, home.blocked_shots) == (13, 2, 1)
    assert (home.shots_outside_box, home.clear_cut_chances, home.woodwork) == (1, 1, 1)
    assert (home.fouls_made, home.offsides, home.yellow_cards, home.red_cards) == (2, 10, 1, 0)
    assert (home.crosses_attempted, home.crosses_completed) == (4, 1)
    assert (home.tackles_attempted, home.tackles_completed) == (3, 2)
    assert (home.aerial_challenges_attempted, home.headers_won) == (5, 3)
    assert home.expected_goals == pytest.approx(1.75)
    assert home.non_penalty_expected_goals == pytest.approx(1.5)
    assert home.distance_km == pytest.approx(95.0)
    assert (home.corners, home.passes_attempted, home.passes_completed) == (6, 500, 450)
    assert home.final_third_passes == 80
    assert away.players == 12
    assert (away.tackles_attempted, away.tackles_completed) == (24, 12)
    # 450 of 799 completed passes is 56.3%; the away share is the rest.
    assert (home.possession_percent, away.possession_percent) == (56, 44)
    # Each side is rounded half up on its own: 62.5% and 37.5%.
    assert (home.ball_distribution_percent, away.ball_distribution_percent) == (63, 38)


def test_rows_join_to_the_fixture_they_report(tmp_path: Path) -> None:
    plain = career_fragment().write(tmp_path / "plain.fm")
    with fmsave.open(plain) as save:
        fixture = next(f for f in save.fixtures() if f.date is not None and f.competition_id)
    assert fixture.date is not None and fixture.kick_off_time is not None
    assert fixture.competition_id is not None
    kick_off = datetime.datetime.combine(fixture.date, fixture.kick_off_time)
    example = summary_match(
        kick_off=kick_off,
        competition_id=fixture.competition_id,
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
    )
    with open_store(tmp_path, store([frame(example)])) as save:
        rows = save.team_match_stats()
        key = (fixture.competition_id, fixture.home_team_id, fixture.away_team_id, fixture.date)
        joined = [
            row
            for row in rows
            if (row.competition_id, row.home_team_id, row.away_team_id, row.date) == key
        ]
        assert len(joined) == 2
        assert {row.kick_off_time for row in joined} == {fixture.kick_off_time}


def test_a_detailed_report_carries_progressive_passes_and_metres(tmp_path: Path) -> None:
    home = ExampleTeam(players=squad(11, distance=9_500.0, progressive=4, events=(1, 2)))
    away = ExampleTeam(players=squad(11, distance=10_000.0, progressive=3, optional_block=True))
    example = ExampleReport(home=home, away=away, detailed=True, gap=1_400)
    with open_store(tmp_path, store([frame(example)])) as save:
        home_row, away_row = save.team_match_stats()

    assert home_row.detailed_report and away_row.detailed_report
    assert home_row.distance_km == pytest.approx(104.5)
    assert away_row.distance_km == pytest.approx(110.0)
    assert (home_row.progressive_passes, away_row.progressive_passes) == (44, 33)


def test_distance_adds_up_in_single_precision() -> None:
    players = (
        ExamplePlayer(distance=5.4),
        *squad(10, distance=8.66),
    )
    single = 0.0
    for player in players:
        single = struct.unpack(
            "<f",
            struct.pack("<f", single + struct.unpack("<f", struct.pack("<f", player.distance))[0]),
        )[0]
    example = ExampleReport(home=ExampleTeam(players), away=ExampleTeam(squad(11)))
    from fmsave._layouts.fm26_26_3_2 import MATCH_REPORTS
    from fmsave.readers.team_match_stats import read_team_match_stats

    rows, _ = read_team_match_stats(store([frame(example)]), MATCH_REPORTS, "example.fm")
    assert rows[0].distance_km == single


def test_fm27_records_read_past_their_8_extra_bytes() -> None:
    from fmsave._layouts.fm26_26_3_2 import MATCH_REPORTS as FM26_MATCH_REPORTS
    from fmsave._layouts.fm27_27_0_0 import BUILD as FM27_BUILD
    from fmsave.readers.team_match_stats import find_match_report_layout, read_team_match_stats

    layout = find_match_report_layout("FM27", 6, FM27_BUILD, known_build=True)
    home = ExampleTeam(
        players=squad(11, shots=1, npxg=0.25, progressive=4, events=(1, 2)), passes=(500, 450)
    )
    away = ExampleTeam(players=squad(11, npxg=0.125, progressive=3, optional_block=True))
    detailed = ExampleReport(
        home=home,
        away=away,
        kick_off=KICK_OFF + datetime.timedelta(days=7),
        detailed=True,
        gap=1_400,
        inserted=8,
    )
    section = store([frame(summary_match(inserted=8)), frame(detailed)])

    rows, stats = read_team_match_stats(section, layout, "example.fm")
    assert (stats.framed, stats.incomplete, stats.detailed) == (2, 0, 1)
    summary_home, _, detailed_home, detailed_away = rows
    assert (summary_home.shots, summary_home.non_penalty_expected_goals) == (13, 1.5)
    assert summary_home.passes_attempted == 500
    assert (detailed_home.progressive_passes, detailed_away.progressive_passes) == (44, 33)
    assert detailed_home.non_penalty_expected_goals == pytest.approx(2.75)
    assert detailed_away.non_penalty_expected_goals == pytest.approx(1.375)

    _, fm26_stats = read_team_match_stats(section, FM26_MATCH_REPORTS, "example.fm")
    assert (fm26_stats.framed, fm26_stats.incomplete) == (0, 2)


def test_an_fm27_build_without_a_layout_is_unsupported() -> None:
    from fmsave.readers.team_match_stats import find_match_report_layout

    with pytest.raises(fmsave.UnsupportedGameError):
        find_match_report_layout("FM27", 6, "27.1.0+1", known_build=False)


def test_team_marker_inside_venue_id_does_not_change_team_ids(tmp_path: Path) -> None:
    def team(team_id: int) -> bytes:
        return b"\x03\x02" + struct.pack("<I", team_id)

    # The venue ID includes the same bytes that introduce a team entry.
    venue = b"\x02" + struct.pack("<I", 0x010203) + bytes(15)
    example = summary_match(extra={100: venue + team(HOME_TEAM) + bytes(17) + team(AWAY_TEAM)})
    with open_store(tmp_path, store([frame(example)])) as save:
        home, away = save.team_match_stats()

    assert (home.home_team_id, home.away_team_id) == (HOME_TEAM, AWAY_TEAM)
    assert (home.team_id, home.shots, away.team_id, away.shots) == (HOME_TEAM, 13, AWAY_TEAM, 12)


def test_earlier_false_anchor_does_not_displace_the_first_player() -> None:
    from fmsave._layouts.fm27_27_0_0 import MATCH_REPORTS
    from fmsave.readers.team_match_stats import read_team_match_stats

    report = bytearray(report_bytes(summary_match(inserted=8)))
    # The false record has a variable part that lands on the second home player.
    false_anchor = HOME_FIRST_ANCHOR - 213
    report[false_anchor + 1 : false_anchor + 9] = b"\xff" * 8
    report[false_anchor + 9] = report[false_anchor + 22] = 2
    report[false_anchor + 116] = 1
    report[false_anchor + 119] = 14

    section = store([zstd.compress(bytes(report))])
    rows, stats = read_team_match_stats(section, MATCH_REPORTS, "example.fm")
    assert stats.incomplete == 0
    home, away = rows
    assert (home.players, home.shots, away.players, away.shots) == (11, 13, 12, 12)


def test_records_with_events_and_optional_blocks_stay_in_one_squad(tmp_path: Path) -> None:
    players = (
        ExamplePlayer(shots=1, events=(1,)),
        ExamplePlayer(shots=1, optional_block=True),
        ExamplePlayer(shots=1, events=(2, 1), optional_block=True),
        *squad(10, shots=1),
    )
    example = summary_match(home=ExampleTeam(players=players, passes=(10, 10)))
    with open_store(tmp_path, store([frame(example)])) as save:
        home, _ = save.team_match_stats()
    assert (home.players, home.shots) == (13, 13)


def test_reports_across_pages_are_all_read(tmp_path: Path) -> None:
    later = KICK_OFF + datetime.timedelta(days=7)
    section = store(
        [],
        [frame(summary_match())],
        [],
        [frame(summary_match(kick_off=later, home_team_id=AWAY_TEAM, away_team_id=HOME_TEAM))],
    )
    with open_store(tmp_path, section) as save:
        rows = save.team_match_stats()
    assert [(row.date, row.team_id) for row in rows] == [
        (KICK_OFF.date(), HOME_TEAM),
        (KICK_OFF.date(), AWAY_TEAM),
        (later.date(), AWAY_TEAM),
        (later.date(), HOME_TEAM),
    ]


def test_an_unframed_squad_gives_no_rows_and_is_counted(tmp_path: Path) -> None:
    short = summary_match(away=ExampleTeam(players=squad(10)))
    cut = summary_match(kick_off=KICK_OFF + datetime.timedelta(days=1), trailing_walk=2)
    wide = summary_match(kick_off=KICK_OFF + datetime.timedelta(days=2), gap=SUMMARY_GAP + 214)
    section = store(
        [frame(summary_match(kick_off=KICK_OFF - datetime.timedelta(days=1)))]
        + [frame(short), frame(cut), frame(wide)]
    )
    with open_store(tmp_path, section) as save:
        with pytest.warns(fmsave.ReaderCheckWarning, match="match_reports_framed"):
            rows = save.team_match_stats()
        report = fmsave.validate_save(save)
    assert len(rows) == 2
    (validation,) = [r for r in report.readers if r.reader == "team_match_stats"]
    assert validation.status == "ok"
    assert validation.anomalies["incomplete_reports"] == 3
    (framed,) = [gate for gate in validation.gates if gate.name == "match_reports_framed"]
    assert framed.advisory and not framed.passed


def test_reports_sharing_a_key_are_both_left_out(tmp_path: Path) -> None:
    section = store([frame(summary_match()), frame(summary_match())])
    with open_store(tmp_path, section) as save:
        assert len(save.team_match_stats()) == 0
        report = fmsave.validate_save(save)
    (validation,) = [r for r in report.readers if r.reader == "team_match_stats"]
    assert validation.anomalies["duplicate_keys"] == 1


def test_a_frame_that_does_not_decompress_fails_the_index_check(tmp_path: Path) -> None:
    section = store([frame(summary_match()), b"\x28\xb5\x2f\xfd" + bytes(20)])
    unread = "match_report_entries_decompressed"
    with (
        open_store(tmp_path, section) as save,
        pytest.warns(fmsave.ReaderCheckWarning, match=unread),
    ):
        assert len(save.team_match_stats()) == 2
    with (
        open_store(tmp_path, section, strict=True) as save,
        pytest.raises(fmsave.ReaderCheckError, match=unread),
    ):
        save.team_match_stats()


@pytest.mark.parametrize(
    ("section", "detail"),
    [
        (store([], page_count=2), "page 1 is missing"),
        (store([b"\x00" * 8])[:-4], "runs past the section"),
    ],
)
def test_an_index_that_does_not_walk_raises(tmp_path: Path, section: bytes, detail: str) -> None:
    with (
        open_store(tmp_path, section) as save,
        pytest.raises(fmsave.ReaderCheckError, match=detail),
    ):
        save.team_match_stats()


def test_an_empty_store_gives_an_empty_table(tmp_path: Path) -> None:
    with open_store(tmp_path, store([], [])) as save:
        assert len(save.team_match_stats()) == 0
        report = fmsave.validate_save(save)
    (validation,) = [r for r in report.readers if r.reader == "team_match_stats"]
    assert validation.status == "ok"
    assert all(not gate.applied for gate in validation.gates)


def test_a_save_without_a_store_skips_the_reader_in_validation(tmp_path: Path) -> None:
    path = career_fragment().write(tmp_path / "example.fm")
    with fmsave.open(path) as save:
        report = fmsave.validate_save(save)
        with pytest.raises(fmsave.UnsupportedGameError, match="team match stats"):
            save.team_match_stats()
    assert "team_match_stats" not in [r.reader for r in report.readers]


def test_export_writes_the_rows_and_scopes_them(tmp_path: Path) -> None:
    with fmsave.open(career_fragment().write(tmp_path / "plain.fm")) as save:
        competition_id = save.competitions()[0].id
        club = next(club for club in save.clubs() if club.teams)
    club_team = club.teams[0].team_id
    in_competition = summary_match(competition_id=competition_id)
    with_club = summary_match(
        kick_off=KICK_OFF + datetime.timedelta(days=1), away_team_id=club_team
    )
    section = store([frame(in_competition), frame(with_club)])
    path = career_fragment(match_stats_section=section).write(tmp_path / "example.fm")

    def export(*scope: str, table: str = "team-match-stats") -> list[str]:
        target = tmp_path / "team-match-stats.csv"
        assert main(["export", str(path), table, *scope, "-o", str(target)]) == 0
        return target.read_text().splitlines()

    every_row = export("--all")
    assert export("--all", table="team_match_stats") == every_row
    assert every_row[0] == ",".join(column_names(fmsave.TeamMatchStats))
    assert len(every_row) == 5
    assert len(export("--competition", str(competition_id))) == 3
    by_club = export("--club", str(club.uid))
    assert len(by_club) == 3
    assert all(f",{club_team}," in line for line in by_club[1:])


def test_every_field_has_a_status() -> None:
    for name in column_names(fmsave.TeamMatchStats):
        assert fmsave.field_status(fmsave.TeamMatchStats, name) in ("verified", "unconfirmed")


def test_overlapping_reports_raise() -> None:
    from fmsave._layouts.fm26_26_3_2 import MATCH_REPORTS
    from fmsave.readers.team_match_stats import read_team_match_stats

    one = frame(summary_match())
    section = bytearray(store([one, one]))
    # Point the second entry back at the first frame.
    second_entry = section.index(struct.pack("<III", 1, len(one), len(one)))
    struct.pack_into("<I", section, second_entry + 4, 0)
    with pytest.raises(fmsave.ReaderCheckError, match="overlap"):
        read_team_match_stats(bytes(section), MATCH_REPORTS, "example.fm")


def test_a_team_id_cut_off_by_the_report_end_gives_no_header() -> None:
    from fmsave._layouts.fm26_26_3_2 import MATCH_REPORTS
    from fmsave.readers.team_match_stats import read_team_match_stats

    report = bytearray(200)
    report[37] = 0x02
    report[173:175] = b"\x03\x02"
    report[196:198] = b"\x03\x02"
    rows, stats = read_team_match_stats(
        store([zstd.compress(bytes(report))]), MATCH_REPORTS, "example.fm"
    )
    assert (rows, stats.without_header) == ([], 1)


def test_reports_that_expand_past_the_budget_raise() -> None:
    from dataclasses import replace

    from fmsave._layouts.fm26_26_3_2 import MATCH_REPORTS
    from fmsave.readers.team_match_stats import read_team_match_stats

    report = report_bytes(summary_match())
    later = frame(summary_match(kick_off=KICK_OFF + datetime.timedelta(days=1)))
    layout = replace(MATCH_REPORTS, maximum_expansion=1, maximum_report_bytes=len(report))
    with pytest.raises(fmsave.CorruptSaveError, match="decompresses to more than"):
        read_team_match_stats(store([zstd.compress(report), later]), layout, "example.fm")
