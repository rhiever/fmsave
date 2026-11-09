from __future__ import annotations

import struct
from pathlib import Path

import pytest

import fmsave
from fmsave._container import read_index, read_section
from fmsave.cli import main
from fmsave.export import column_names
from tests.fixtures.career import career_fragment, career_game_db
from tests.fixtures.container import (
    SectionFrame,
    build_container_fragment,
    packed_date,
    section_body,
    zstd,
)
from tests.fixtures.game_db import person_block_birth_offset, person_block_bytes
from tests.test_fm27_experimental import BUILD as FM27_BUILD
from tests.test_fm27_experimental import fm27_fragment
from tests.test_fm27_span_readers import calendar
from tests.test_match_summaries import summary_bytes

REFEREE_ID = 880_001
PERSON_UID = 1_234_567


def official_bytes(
    *, person_uid: int = PERSON_UID, gap: bytes = b"\x00", fm27: bool = False
) -> bytes:
    header = bytearray(summary_bytes())
    struct.pack_into("<III", header, 0, REFEREE_ID - 1, person_uid, person_uid)
    person = person_block_bytes(
        first_name_id=0xFFFFFFFF,
        surname_id=0xFFFFFFFF,
        common_name_id=0xFFFFFFFF,
        legal_name="Alex Example",
        birth=packed_date(42, 1986),
        nation_id=1,
        personality=(10,) * 8,
        trait_bits=0,
        relations=(),
        clutter=b"",
    )
    if fm27:
        after_birth = person_block_birth_offset("Alex Example", clutter=b"") + 4
        person = person[:after_birth] + b"\xa5" + person[after_birth:]
    # The attached name starts after the standard helper's date, flag, and traits.
    return bytes(header) + gap + person[13:]


def test_fixture_referee_joins_to_official_and_exports_the_same_key(tmp_path: Path) -> None:
    path = career_fragment(extra_staff=official_bytes()).write(tmp_path / "example.fm")
    with fmsave.open(path) as save:
        fixtures = save.fixtures()
        (official,) = save.officials()
        assert save.officials() is save.officials()
        assert official.referee_id == REFEREE_ID
        assert official.person_uid == PERSON_UID
        assert official.name == "Alex Example"
        assert len(fixtures.where(referee_id=official.referee_id)) == 1
        assert all(fixture.referee_id is None for fixture in fixtures.where(played=False))
        assert "match_record_id" not in column_names(fmsave.Fixture)

    target = tmp_path / "officials.csv"
    assert main(["export", str(path), "officials", "--all", "-o", str(target)]) == 0
    assert target.read_text().splitlines() == [
        "referee_id,person_uid,name",
        f"{REFEREE_ID},{PERSON_UID},Alex Example",
    ]


def fm27_officials_fragment(tmp_path: Path, build: str) -> Path:
    database = career_game_db(extra_staff=official_bytes(fm27=True))
    index = read_index(fm27_fragment(tmp_path, build=build, game_db=database[8:]))
    sections = [
        SectionFrame(name, read_section(index, name), entry.extension)
        for name, entry in index.sections.items()
    ]
    sections.append(
        SectionFrame(
            "non_pl_hist_ls",
            section_body(".dat", 4, bytes(4)),
            unlisted_frames_after=(zstd.compress(calendar()),),
        )
    )
    return build_container_fragment(sections).write(tmp_path / "example.fm")


def test_fm27_officials_use_the_fixture_reference_namespace(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(fm27_officials_fragment(tmp_path, FM27_BUILD))
    with save:
        (official,) = save.officials()
        assert official.referee_id == REFEREE_ID
        assert official.person_uid == PERSON_UID
        assert official.name == "Alex Example"
        fixtures = save.fixtures()
        assert len(fixtures.where(referee_id=REFEREE_ID)) == 2
        assert all(fixture.referee_id is None for fixture in fixtures.where(played=False))
        report = fmsave.validate_save(save)
        officials = next(reader for reader in report.readers if reader.reader == "officials")
        assert (officials.status, officials.record_count) == ("ok", 1)
        assert report.field_statuses["Fixture.referee_id"] == "verified"
        assert report.field_statuses["Official.referee_id"] == "verified"
        assert report.field_statuses["Official.name"] == "unconfirmed"


def test_borrowed_fm27_calendar_leaves_referee_ids_unknown(tmp_path: Path) -> None:
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(fm27_officials_fragment(tmp_path, "27.0.0+9999999"))
    with save:
        fixtures = save.fixtures()
        assert fixtures.where(played=True)
        assert all(fixture.referee_id is None for fixture in fixtures)
        with pytest.raises(fmsave.UnsupportedGameError):
            save.officials()
        report = fmsave.validate_save(save)
        assert report.field_statuses["Fixture.referee_id"] == "unconfirmed"


@pytest.mark.parametrize(
    "objects",
    [
        b"",
        official_bytes(gap=b"\x00\x00"),
        official_bytes() + official_bytes(person_uid=PERSON_UID + 1),
    ],
    ids=("absent", "misframed", "conflicting"),
)
def test_lookup_skips_absent_misframed_and_conflicting_officials(
    tmp_path: Path, objects: bytes
) -> None:
    path = career_fragment(extra_staff=objects).write(tmp_path / "example.fm")
    with fmsave.open(path, strict=True) as save:
        assert not save.officials()
        assert save.fixtures().where(referee_id=REFEREE_ID)
