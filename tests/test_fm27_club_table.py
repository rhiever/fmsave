"""Independent fictional fragments for the FM27 counted club walk."""

from __future__ import annotations

import struct
import warnings
from pathlib import Path

import pytest

import fmsave
from fmsave._layouts import ClubTableLayout, find_layout
from fmsave.readers.club_table import walk_club_table
from tests.fixtures.career import career_finance_rows
from tests.fixtures.container import SectionFrame, length_prefixed, packed_date, section_body
from tests.fixtures.finances import (
    chain_gap_bytes,
    finance_chain_bytes,
    sponsor_chain_bytes,
    sponsor_row_bytes,
)
from tests.test_fm27_experimental import fm27_fragment

BUILD = "27.0.0+2486695"
PATCH_BUILD = "27.1.0+2505117"
UNKNOWN_BUILD = "27.2.0+3000001"
FINANCE_EXTENSION = b"\x02" + packed_date(1, 1900)
BALANCE = -123_456


def club_body(
    *,
    finance: int,
    extended: bool = False,
    team_id: int = 71001,
    finance_details: bytes = bytes(4 + 72 + 67 + 1),
) -> bytes:
    prefix = bytes((12 if extended else 0,))
    prefix += struct.pack("<4I", 3, 0xFFFFFFFF, 3, 3) + struct.pack("<I", 77) + bytes(6)
    prefix += bytes(4 if extended else 0)
    names = length_prefixed("Northbridge FC") + length_prefixed("Northbridge")
    if finance == 0:
        money = bytes(45) + sponsor_chain_bytes(())
    elif finance == 1:
        money = bytes(66) + (bytes(235) + bytes(2)) * 4 + bytes(67) + bytes(1)
        money += finance_details
    else:
        money = sponsor_chain_bytes(())
    tail = bytes(1) + bytes(9)
    tail += bytes((1,)) + struct.pack("<I", team_id) + bytes(1)
    # Exercise a widened count above the u8 range, not merely zero padding.
    tail += struct.pack("<H", 260) + bytes(260 * 4)
    tail += struct.pack("<H", 1) + bytes(4) + struct.pack("<H", 0)
    tail += bytes(1) + bytes(2)
    return prefix + names + bytes(8) + bytes(1) + bytes((finance,)) + money + tail


@pytest.mark.parametrize("finance", (0, 1, 2))
@pytest.mark.parametrize("extended", (False, True))
def test_fm27_counted_club_records_consume_their_own_footer(finance: int, extended: bool) -> None:
    layout = find_layout(ClubTableLayout, "game_db", 4000, BUILD).layout
    body = club_body(finance=finance, extended=extended)
    data = struct.pack("<IB", 2, 0)
    for ordinal, uid in enumerate((6100, 6200)):
        data += body + struct.pack("<III", ordinal, uid, uid)
    rows = walk_club_table(data, 0, layout)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0].unique_id == 6100
    assert rows[-1].footer_start + 12 == len(data)
    assert walk_club_table(data[:-1], 0, layout) is None
    assert (
        walk_club_table(data.replace(struct.pack("<I", 6200), struct.pack("<I", 6100)), 0, layout)
        is None
    )


def _club_table(finance_extension: bytes, finance_types: tuple[int, ...] = (0, 1, 2)) -> bytes:
    sponsor = sponsor_row_bytes(
        sponsor_type=1,
        start=packed_date(200, 2031),
        end=packed_date(200, 2032),
        flag10=0,
        total=100_000,
        u15=0,
        b17=0,
        enum18=0,
        b19=0,
        annual=100_000,
    )
    finance_details = (
        finance_chain_bytes(career_finance_rows())
        + chain_gap_bytes(balance=BALANCE, finance_extension=finance_extension)
        + sponsor_chain_bytes((sponsor,))
    )
    data = struct.pack("<IB", len(finance_types), 0)
    for ordinal, finance in enumerate(finance_types):
        uid = 6100 + ordinal * 100
        data += club_body(finance=finance, team_id=71001 + ordinal, finance_details=finance_details)
        data += struct.pack("<III", ordinal, uid, uid)
    return data


@pytest.mark.parametrize(
    ("build", "finance_extension", "fallback", "strict"),
    [
        (BUILD, b"", False, False),
        (PATCH_BUILD, FINANCE_EXTENSION, False, False),
        (UNKNOWN_BUILD, b"", False, False),
        (UNKNOWN_BUILD, FINANCE_EXTENSION, True, False),
        (UNKNOWN_BUILD, FINANCE_EXTENSION, True, True),
    ],
)
def test_fm27_club_table_and_finance_readers_share_the_validated_layout(
    tmp_path: Path, build: str, finance_extension: bytes, fallback: bool, strict: bool
) -> None:
    humans = SectionFrame("humans", section_body(".dat", 24, struct.pack("<HI", 1, 0) + bytes(32)))
    path = fm27_fragment(
        tmp_path,
        build=build,
        game_db=_club_table(finance_extension),
        managed_club=("Northbridge", 6101),
        extra_sections=(humans,),
    )
    with pytest.warns(UserWarning, match="FM27"):
        save = fmsave.open(path, strict=strict)
    with save, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert save.info.known_build is (build == BUILD)
        (managed_club,) = save.managed_clubs()
        assert (managed_club.club_uid, managed_club.balance) == (6101, BALANCE)
        rows = save.clubs()
        assert [row.uid for row in rows] == [0, 6101, 6201]
        assert [row.unique_id for row in rows] == [6100, 6200, 6300]
        assert [row.teams[0].team_id for row in rows] == [71001, 71002, 71003]
        assert [row.club_uid for row in save.finances()] == [6101] * len(career_finance_rows())
        assert [(row.club_uid, row.annual_value) for row in save.sponsorships()] == [
            (6101, 100_000)
        ]
        assert [(row.club_uid, row.corporate_facilities.raw) for row in save.facilities()] == [
            (6101, 17)
        ]
    fallback_warnings = [
        str(item.message) for item in caught if isinstance(item.message, fmsave.UnknownBuildWarning)
    ]
    assert len(fallback_warnings) == int(fallback)
    if fallback:
        assert PATCH_BUILD in fallback_warnings[0]


@pytest.mark.parametrize(("build", "corrupt_footer"), [(UNKNOWN_BUILD, True), (BUILD, False)])
def test_fm27_fallback_requires_an_unknown_build_and_a_complete_table(
    tmp_path: Path, build: str, corrupt_footer: bool
) -> None:
    data = _club_table(FINANCE_EXTENSION)
    if corrupt_footer:
        data = data[:-1]
    path = fm27_fragment(tmp_path, build=build, game_db=data)
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save, pytest.raises(fmsave.ReaderCheckError, match="club table framing"):
        save.clubs()


def test_fm27_fallback_can_find_a_header_when_the_first_club_has_full_finances(
    tmp_path: Path,
) -> None:
    data = _club_table(FINANCE_EXTENSION, (1, 0, 2))
    path = fm27_fragment(tmp_path, build=UNKNOWN_BUILD, game_db=data)
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save, pytest.warns(fmsave.UnknownBuildWarning, match="uses the club and finance layouts"):
        assert [row.unique_id for row in save.clubs()] == [6100, 6200, 6300]


def test_fm27_keeps_the_default_when_both_layouts_fit(tmp_path: Path) -> None:
    # Without a full finance block, the counted table has the same shape in both layouts.
    data = _club_table(b"", (0, 2))
    path = fm27_fragment(tmp_path, build=UNKNOWN_BUILD, game_db=data)
    with pytest.warns(fmsave.UnknownBuildWarning):
        save = fmsave.open(path)
    with save, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert [row.unique_id for row in save.clubs()] == [6100, 6200]
    assert not any(isinstance(item.message, fmsave.UnknownBuildWarning) for item in caught)
