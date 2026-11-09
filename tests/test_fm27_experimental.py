"""Fictional fragments exercise the explicitly bounded FM27 experiment."""

from __future__ import annotations

import struct
from datetime import date
from pathlib import Path

import pytest

import fmsave
from fmsave._errors import UnsupportedGameError
from fmsave._layouts import GameInfoLayout, TrainingLayout, find_layout, known_builds
from fmsave.cli import main
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    length_prefixed,
    packed_date,
    section_body,
    zstd,
)
from tests.fixtures.nations import nation_table_bytes

BUILD = "27.0.0+2486695"


def fm27_fragment(
    tmp_path: Path,
    *,
    build: str = BUILD,
    info_schema: int = 47,
    game_db: bytes = bytes(64),
    game_db_schema: int = 4000,
    summary_schema: int = 31,
    summary_date: bytes = packed_date(190, 2032),
    extra_sections: tuple[SectionFrame, ...] = (),
) -> Path:
    # Independent synthetic metadata: no save bytes, derived identities or real text.
    base = 8 + len(length_prefixed("27.0.0+0"))
    info = bytearray(section_body(".dat", info_schema, length_prefixed("27.0.0+0")))
    info.extend(bytes(base + 390 - len(info)))
    number = int(build.split("+")[1])
    struct.pack_into("<I", info, base + 38, number)
    struct.pack_into("<I", info, base + 167, 0)
    info[base + 174 : base + 178] = packed_date(1, 1900)
    struct.pack_into("<II", info, base + 382, number, 0)
    summary = length_prefixed("EXAMPLE,SETUP") + length_prefixed(build)
    summary += struct.pack("<I", 1) + length_prefixed("Example Division")
    summary += bytes(8) + length_prefixed("Alex Example") + length_prefixed("Northbridge FC")
    summary += struct.pack("<I", 5001) + summary_date
    return build_container_fragment(
        [
            SectionFrame("game_info", bytes(info)),
            SectionFrame("save_game_summary", section_body(".dat", summary_schema, summary)),
            SectionFrame("game_db", section_body(".dat", game_db_schema, game_db)),
            *extra_sections,
        ]
    ).write(tmp_path / "example.bin")


def test_fm27_is_read_by_default(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="FM27"), fmsave.open(fm27_fragment(tmp_path)) as save:
        assert save.info.game == "FM27"


def test_fm27_exact_experiment_reads_structured_metadata(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="FM27"):
        save = fmsave.open(fm27_fragment(tmp_path))
    with save:
        assert save.info.game == "FM27"
        assert save.info.build == BUILD
        assert save.info.game_date == date(2032, 7, 8)
        assert save.info.db_version == "27.0.0+0"
        assert save.info.known_build
    assert BUILD in known_builds()


@pytest.mark.parametrize("build,schema", [("27.0.1+3000001", 48), (BUILD, 48), ("0" + BUILD, 47)])
def test_fm27_unknown_metadata_schema_or_version_fails_closed(
    tmp_path: Path, build: str, schema: int
) -> None:
    with pytest.raises(UnsupportedGameError):
        fmsave.open(fm27_fragment(tmp_path, build=build, info_schema=schema))


UNREGISTERED_BUILD = "27.1.0+3000001"


def test_an_unregistered_fm27_build_opens_and_reads_a_region_whose_schema_matches(
    tmp_path: Path,
) -> None:
    path = fm27_fragment(tmp_path, build=UNREGISTERED_BUILD, game_db=nation_table_bytes())
    with pytest.warns(fmsave.UnknownBuildWarning) as record:
        save = fmsave.open(path)
    with save:
        assert save.info.game == "FM27"
        assert save.info.build == UNREGISTERED_BUILD
        assert not save.info.known_build
        assert save.info.game_date == date(2032, 7, 8)
        rows = save.nations()
        assert len(rows) == 251
        assert rows[-1].database_id == 900_250
    messages = [str(warning.message) for warning in record]
    # One warning carries both the borrowing notice and the FM27 coverage notice.
    assert len(messages) == 1
    assert f"FM27 build {UNREGISTERED_BUILD}, an unverified build" in messages[0]
    assert f"borrows the {BUILD} layouts for each section whose schema matches" in messages[0]
    assert "Please report problems at" in messages[0]
    assert "FM27 field statuses" in messages[0]


def test_the_registered_fm27_build_warns_only_about_coverage(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning) as record:
        fmsave.open(fm27_fragment(tmp_path)).close()
    assert [str(warning.message).startswith("FM27 coverage") for warning in record] == [True]


def test_an_unregistered_fm27_reader_whose_schema_changed_fails_by_itself(
    tmp_path: Path,
) -> None:
    feeder = SectionFrame("feeder_man", section_body(".dat", 6, bytes(16)))
    path = fm27_fragment(
        tmp_path,
        build=UNREGISTERED_BUILD,
        game_db=nation_table_bytes(),
        extra_sections=(feeder,),
    )
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save:
        with pytest.raises(UnsupportedGameError) as error_info:
            save.affiliates()
        message = str(error_info.value)
        assert "'feeder_man'" in message
        assert UNREGISTERED_BUILD in message
        assert "schema 6 differs from the schema 5 registered for build" in message
        assert len(save.nations()) == 251
        report = fmsave.validate_save(save)
    statuses = {reader.reader: reader.status for reader in report.readers}
    assert statuses["nations"] == "ok"
    assert statuses["affiliates"] != "ok"
    assert not report.known_build


def test_an_unregistered_fm27_game_db_schema_refuses_its_readers_not_the_save(
    tmp_path: Path,
) -> None:
    path = fm27_fragment(
        tmp_path, build=UNREGISTERED_BUILD, game_db=nation_table_bytes(), game_db_schema=4001
    )
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save, pytest.raises(UnsupportedGameError, match="'game_db'.*schema 4001 differs"):
        save.nations()


@pytest.mark.parametrize(
    "info_schema,summary_schema", [(48, 31), (47, 32)], ids=("game_info", "summary")
)
def test_an_unregistered_fm27_build_with_other_metadata_schemas_is_refused(
    tmp_path: Path, info_schema: int, summary_schema: int
) -> None:
    path = fm27_fragment(
        tmp_path,
        build=UNREGISTERED_BUILD,
        info_schema=info_schema,
        summary_schema=summary_schema,
    )
    with pytest.raises(UnsupportedGameError, match="FM27"):
        fmsave.open(path)


def test_an_unregistered_fm27_build_metadata_takes_the_checked_path(tmp_path: Path) -> None:
    # A clock no structured layout accepts is refused rather than guessed.
    path = fm27_fragment(tmp_path, build=UNREGISTERED_BUILD, summary_date=packed_date(0, 2032))
    with pytest.raises(fmsave.ReaderCheckError):
        fmsave.open(path)


@pytest.mark.parametrize("build", ["28.0.0+3000001", "28.1.0+2486695", "99.0.0+1"])
def test_builds_after_fm27_are_still_refused(tmp_path: Path, build: str) -> None:
    with pytest.raises(UnsupportedGameError, match="is not supported"):
        fmsave.open(fm27_fragment(tmp_path, build=build))


def test_unknown_fm26_builds_still_read_fm26_layouts_only() -> None:
    from fmsave._layouts import ClubTableLayout
    from fmsave._layouts import fm26_26_3_2 as fm26
    from fmsave._layouts import fm27_27_0_0 as fm27

    match = find_layout(ClubTableLayout, "game_db", 4000, "26.9.0+1234567")
    assert match.layout is fm26.CLUB_TABLE
    assert match.layout != fm27.CLUB_TABLE
    borrowed = find_layout(ClubTableLayout, "game_db", 4000, UNREGISTERED_BUILD)
    assert borrowed.layout is fm27.CLUB_TABLE
    assert not borrowed.exact


def test_fm27_regions_registered_without_a_schema_are_borrowed() -> None:
    from fmsave._layouts import FixtureCalendarLayout, InjuryTypeTableLayout

    for layout_type, region in (
        (FixtureCalendarLayout, "unlisted_after_non_pl_hist_ls"),
        (InjuryTypeTableLayout, "match_file"),
    ):
        registered = find_layout(layout_type, region, None, BUILD)
        borrowed = find_layout(layout_type, region, None, UNREGISTERED_BUILD)
        assert borrowed.layout is registered.layout
        assert registered.exact and not borrowed.exact


def test_fm27_info_marks_an_unregistered_build_as_unverified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["info", str(fm27_fragment(tmp_path, build=UNREGISTERED_BUILD))]) == 0
    captured = capsys.readouterr()
    assert f"{UNREGISTERED_BUILD} (unverified build, partial coverage)" in captured.out
    assert "unverified build" in captured.err
    assert main(["info", str(fm27_fragment(tmp_path)), "--json"]) == 0
    assert '"known_build": true' in capsys.readouterr().out
    assert main(["info", str(fm27_fragment(tmp_path, build=UNREGISTERED_BUILD)), "--json"]) == 0
    assert '"known_build": false' in capsys.readouterr().out


def test_fm27_layouts_never_borrow_across_game_editions() -> None:
    # FM26 registers training_man 31 and game_info 46; no FM27 build borrows either.
    for build in (BUILD, "27.9.0+1"):
        with pytest.raises(UnsupportedGameError):
            find_layout(TrainingLayout, "training_man", 31, build)
        with pytest.raises(UnsupportedGameError):
            find_layout(GameInfoLayout, "game_info", 46, build)


def test_fm27_info_cli_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(fm27_fragment(tmp_path)), "--json"]) == 0
    captured = capsys.readouterr()
    assert '"game": "FM27"' in captured.out
    assert "Alex Example" not in captured.out
    assert "FM27" in captured.err


def test_fm27_nations_walk_whole_table_and_cache(tmp_path: Path) -> None:
    path = fm27_fragment(tmp_path, game_db=nation_table_bytes())
    with pytest.warns(UserWarning, match="FM27"):
        save = fmsave.open(path)
    with save:
        rows = save.nations()
        assert len(rows) == 251
        assert rows[0].nation_id == 0
        assert rows[-1].database_id == 900_250
        assert save.nations() is rows
        with pytest.raises((UnsupportedGameError, fmsave.ReaderCheckError)):
            save.players()
    assert rows[0].database_id == 900_000


@pytest.mark.parametrize(
    "data",
    [
        b"",
        nation_table_bytes()[:-1],
        nation_table_bytes() * 2,
        nation_table_bytes().replace(struct.pack("<I", 900_001), struct.pack("<I", 900_000)),
    ],
    ids=("missing", "truncated", "ambiguous", "duplicate-identity"),
)
def test_fm27_nations_fail_closed_even_without_strict(tmp_path: Path, data: bytes) -> None:
    with pytest.warns(UserWarning, match="FM27"):
        save = fmsave.open(fm27_fragment(tmp_path, game_db=data))
    with save, pytest.raises(fmsave.ReaderCheckError):
        save.nations()


def test_fm27_unrecognized_summary_clock_is_not_silently_accepted(tmp_path: Path) -> None:
    with pytest.raises(fmsave.ReaderCheckError):
        fmsave.open(fm27_fragment(tmp_path, summary_date=packed_date(0, 2032)))


@pytest.mark.parametrize("build", [BUILD, UNREGISTERED_BUILD])
def test_fm27_validation_reports_only_fm27_field_verification(tmp_path: Path, build: str) -> None:
    with pytest.warns(UserWarning, match="FM27"):
        save = fmsave.open(fm27_fragment(tmp_path, build=build, game_db=nation_table_bytes()))
    with save:
        report = fmsave.validate_save(save)
    field_statuses = report.to_json_dict()["field_statuses"]
    assert isinstance(field_statuses, dict)
    verified = {
        "Staff.age",
        "Staff.birth_date",
        "Staff.contract_end",
        "StaffAttributes.analysing_data",
        "StaffAttributes.attacking",
        "StaffAttributes.authority",
        "StaffAttributes.defending",
        "StaffAttributes.determination",
        "StaffAttributes.fitness",
        "StaffAttributes.goalkeeping",
        "StaffAttributes.judging_player_ability",
        "StaffAttributes.judging_player_potential",
        "StaffAttributes.judging_staff_ability",
        "StaffAttributes.motivating",
        "StaffAttributes.negotiating",
        "StaffAttributes.people_management",
        "StaffAttributes.physiotherapy",
        "StaffAttributes.possession",
        "StaffAttributes.set_pieces",
        "StaffAttributes.sports_science",
        "StaffAttributes.tactical",
        "StaffAttributes.tactical_knowledge",
        "StaffAttributes.technical",
        "StaffAttributes.working_with_youngsters",
    }
    if build == BUILD:
        verified.update({"Fixture.referee_id", "Official.referee_id"})
    assert {name for name, status in field_statuses.items() if status == "verified"} == verified
    assert set(field_statuses.values()) == {"verified", "unconfirmed"}
    assert fmsave.field_status(fmsave.Staff, "age") == "unconfirmed"
    statuses = {reader.reader: reader.status for reader in report.readers}
    assert statuses["nations"] == "ok"
    assert statuses["players"] != "ok"


def fm27_fragment_declaring(
    tmp_path: Path, sizes: dict[str, int], *extra: str, padding: dict[str, int] | None = None
) -> Path:
    """An FM27 fragment whose directory declares `sizes` for some sections, plus `extra` ones.

    `padding` gives a section that many compressed bytes on disk (as a skippable frame after
    its frame), so its declared size can sit at a plausible ratio.
    """
    from fmsave._container import read_index, read_section

    index = read_index(fm27_fragment(tmp_path))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    sections.extend(SectionFrame(name, section_body(".dat", 1, bytes(4))) for name in extra)
    paddings = padding or {}
    return build_container_fragment(
        sections,
        declared_sizes={
            section.name + section.extension: (
                len(zstd.compress(section.body)) + paddings.get(section.name, 0),
                sizes[section.name],
            )
            for section in sections
            if section.name in sizes
        },
        padding_after={name + ".dat": size for name, size in paddings.items()},
    ).write(tmp_path / "declared.bin")


def test_fm27_opens_a_large_database_part_at_a_plausible_ratio(tmp_path: Path) -> None:
    from fmsave._container import ContainerLimits

    # Past the old FM27-only 256 MiB cap and the 64 MiB allowance, at 25 times its 12 MiB.
    path = fm27_fragment_declaring(
        tmp_path, {"game_db": 300 * 1024**2}, padding={"game_db": 12 * 1024**2}
    )
    # Opening reads bounded metadata, not the deliberately oversized fictional database.
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save:
        assert save.info.game == "FM27"
        assert save._container_index.limits == ContainerLimits()


def test_fm27_refuses_a_bomb_shaped_part_before_reading_it(tmp_path: Path) -> None:
    path = fm27_fragment_declaring(tmp_path, {"game_db": 65 * 1024**2})
    with pytest.raises(
        fmsave.CorruptSaveError, match="game_db.dat claims 68,157,440 bytes"
    ) as error:
        fmsave.open(path)
    message = str(error.value)
    assert "fmsave allows up to 64 times" in message
    assert "expand at most about 41 times" in message
    assert "please report it at" in message


def test_fm27_checks_the_whole_save_bound_before_payloads(tmp_path: Path) -> None:
    # Each part sits under the 64 MiB allowance; together they claim far more than the file.
    extra = ("extra_a", "extra_b", "extra_c", "extra_d")
    path = fm27_fragment_declaring(
        tmp_path, dict.fromkeys(("game_db", *extra), 60 * 1024**2), *extra
    )
    with pytest.raises(fmsave.CorruptSaveError, match="the save claims .* bytes in all") as error:
        fmsave.open(path)
    assert "real saves stay under 5 times" in str(error.value)


def test_unknown_fm26_metadata_never_tries_an_fm27_layout(tmp_path: Path) -> None:
    path = fm27_fragment(tmp_path, build="26.9.0+1234567")
    with pytest.warns(fmsave.UnknownBuildWarning), pytest.raises(fmsave.ReaderCheckError):
        fmsave.open(path)
