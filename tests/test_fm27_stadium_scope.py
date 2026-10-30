"""Unknown home-ground links cannot be silently treated as known empty scope membership."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import fmsave
from fmsave import cli
from fmsave._errors import UnsupportedGameError
from fmsave.readers.stadiums import build_stadiums
from tests.test_fm27_stadiums import LAYOUT, fictional_indexes


def test_unknown_stadium_links_reject_club_scope_but_allow_all_rows(tmp_path: Path) -> None:
    index, clubs = fictional_indexes(tmp_path)
    rows, _ = build_stadiums(index, clubs, None, LAYOUT)
    save = cast(fmsave.Save, SimpleNamespace(stadiums=lambda: rows))
    with pytest.raises(UnsupportedGameError, match="home-ground"):
        list(cli._stadium_rows(save, cli._ExportScope(club_uids=frozenset({9999999}))))
    assert tuple(cli._stadium_rows(save, cli._ExportScope())) == rows
