"""The user-supplied competition name map, and the names it fills in across the readers.

Every name here is fictional. fmsave ships no competition name, and no test may introduce one.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

import fmsave
import fmsave._context as context_module
from fmsave._container import ContainerIndex
from fmsave._frozen import FrozenMapping
from fmsave.name_maps import normalize_competition_names, read_competition_names
from fmsave.readers._common import GAME_DB_SECTION
from tests.fixtures.career import (
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    SECOND_COMPETITION_DATABASE_ID,
    SECOND_COMPETITION_ID,
)

FIRST_COMPETITION_NAME = "Example League"
SECOND_COMPETITION_NAME = "Example Cup"
NAME_FILE_NAME = "names.csv"
PRIVATE_FOLDER_NAME = "Private Folder"
# Stage 1 belongs to the first competition and stage 3 to the second, which the map never names.
NAMED_COMPETITION_STAGE_ID = 1
UNNAMED_COMPETITION_STAGE_ID = 3
FIRST_COMPETITION_ONLY = {FIRST_COMPETITION_DATABASE_ID: FIRST_COMPETITION_NAME}


def write_names_csv(folder: Path, csv_text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / NAME_FILE_NAME
    csv_path.write_text(csv_text, encoding="utf-8")
    return csv_path


@pytest.mark.parametrize(
    ("csv_text", "expected_names"),
    [
        pytest.param(
            "12345,Example League\n12346,Example Cup\n",
            {12345: "Example League", 12346: "Example Cup"},
            id="two-rows",
        ),
        pytest.param(
            "database_id,name\n12345,Example League\n",
            {12345: "Example League"},
            id="header-row-skipped",
        ),
        pytest.param(
            "  12345  ,  Example League  \n",
            {12345: "Example League"},
            id="surrounding-whitespace-stripped",
        ),
        pytest.param(
            "12345,Example League\n\n12346,Example Cup\n",
            {12345: "Example League", 12346: "Example Cup"},
            id="blank-line-skipped",
        ),
        pytest.param("12345,Ligue Éxample\n", {12345: "Ligue Éxample"}, id="utf-8-name"),
        # One id twice under one name says the same thing twice, which contradicts nothing.
        pytest.param(
            "12345,Example League\n12345,Example League\n",
            {12345: "Example League"},
            id="one-id-twice-under-one-name",
        ),
    ],
)
def test_a_two_column_file_reads_into_a_name_map(
    tmp_path: Path, csv_text: str, expected_names: dict[int, str]
) -> None:
    assert read_competition_names(write_names_csv(tmp_path, csv_text)) == expected_names


@pytest.mark.parametrize(
    ("csv_text", "expected_fragments"),
    [
        pytest.param(
            "12345,Example League\n12346\n",
            ("line 2", "expected 2 columns, found 1"),
            id="one-column-row",
        ),
        # The header rule only ever skips the first row, so a text id below one is a fault.
        pytest.param(
            "12345,Example League\nabc,Example Cup\n",
            ("line 2", "'abc' is not a competition database id"),
            id="id-that-is-not-a-number",
        ),
        pytest.param("12345,\n", ("line 1", "the name is empty"), id="empty-name"),
        pytest.param(
            "12345,Example League\n12345,Example Cup\n",
            ("line 2", "database id 12345 is listed twice"),
            id="one-id-under-two-names",
        ),
    ],
)
def test_a_malformed_row_names_its_line_and_its_fault(
    tmp_path: Path, csv_text: str, expected_fragments: tuple[str, ...]
) -> None:
    csv_path = write_names_csv(tmp_path, csv_text)

    with pytest.raises(ValueError) as error_info:
        read_competition_names(csv_path)

    message = str(error_info.value)
    assert message.startswith(NAME_FILE_NAME)
    for expected_fragment in expected_fragments:
        assert expected_fragment in message


def test_an_error_names_the_file_but_never_its_folder(tmp_path: Path) -> None:
    """A message pasted into a bug report must carry no part of the reader's folder layout."""
    csv_path = write_names_csv(tmp_path / PRIVATE_FOLDER_NAME, "12345,\n")

    with pytest.raises(ValueError) as error_info:
        read_competition_names(csv_path)

    message = str(error_info.value)
    assert NAME_FILE_NAME in message
    assert PRIVATE_FOLDER_NAME not in message
    assert str(tmp_path) not in message


def test_normalize_accepts_nothing_a_mapping_and_a_path(tmp_path: Path) -> None:
    csv_path = write_names_csv(
        tmp_path, f"{FIRST_COMPETITION_DATABASE_ID},{FIRST_COMPETITION_NAME}\n"
    )

    from_nothing = normalize_competition_names(None)
    from_mapping = normalize_competition_names(FIRST_COMPETITION_ONLY)
    from_path = normalize_competition_names(csv_path)
    from_path_text = normalize_competition_names(str(csv_path))

    assert isinstance(from_nothing, FrozenMapping)
    assert isinstance(from_mapping, FrozenMapping)
    assert from_nothing == {}
    assert from_mapping == from_path == from_path_text == FIRST_COMPETITION_ONLY


@pytest.mark.parametrize(
    ("names", "expected_error"),
    [
        pytest.param({"1": "Example League"}, TypeError, id="key-that-is-not-an-int"),
        pytest.param({1: 2}, TypeError, id="name-that-is-not-a-string"),
        pytest.param({1: ""}, ValueError, id="empty-name"),
    ],
)
def test_normalize_rejects_a_wrong_key_or_name(
    names: Mapping[int, str], expected_error: type[Exception]
) -> None:
    with pytest.raises(expected_error) as error_info:
        normalize_competition_names(names)

    assert "1" in str(error_info.value)


def test_the_normalized_map_is_immutable() -> None:
    competition_names = normalize_competition_names(FIRST_COMPETITION_ONLY)

    with pytest.raises(TypeError):
        competition_names[SECOND_COMPETITION_DATABASE_ID] = (  # pyright: ignore[reportIndexIssue]
            SECOND_COMPETITION_NAME
        )


def test_a_competition_is_named_through_its_database_id(career_save_path: Path) -> None:
    """Only the competition whose database id the map lists is named; the other stays None."""
    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as career_save:
        named_competition = career_save.competitions().where(id=FIRST_COMPETITION_ID)[0]
        unnamed_competition = career_save.competitions().where(id=SECOND_COMPETITION_ID)[0]

    assert named_competition.database_id == FIRST_COMPETITION_DATABASE_ID
    assert named_competition.name == FIRST_COMPETITION_NAME
    assert unnamed_competition.database_id == SECOND_COMPETITION_DATABASE_ID
    assert unnamed_competition.name is None


def test_a_stage_carries_the_name_of_its_competition(career_save_path: Path) -> None:
    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as career_save:
        named_stage = career_save.stages().where(id=NAMED_COMPETITION_STAGE_ID)[0]
        unnamed_stage = career_save.stages().where(id=UNNAMED_COMPETITION_STAGE_ID)[0]

    assert named_stage.competition_id == FIRST_COMPETITION_ID
    assert named_stage.competition_name == FIRST_COMPETITION_NAME
    assert unnamed_stage.competition_id == SECOND_COMPETITION_ID
    assert unnamed_stage.competition_name is None


def test_a_save_opened_without_a_map_names_nothing(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as career_save:
        competitions_table = career_save.competitions()
        stages_table = career_save.stages()

    assert all(competition.name is None for competition in competitions_table)
    assert all(stage.competition_name is None for stage in stages_table)


def test_a_csv_path_and_a_mapping_name_the_same_competitions(
    career_save_path: Path, tmp_path: Path
) -> None:
    csv_path = write_names_csv(
        tmp_path,
        f"database_id,name\n{FIRST_COMPETITION_DATABASE_ID},{FIRST_COMPETITION_NAME}\n",
    )

    with fmsave.open(career_save_path, competition_names=str(csv_path)) as from_file:
        names_from_file = [competition.name for competition in from_file.competitions()]
    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as from_mapping:
        names_from_mapping = [competition.name for competition in from_mapping.competitions()]

    assert names_from_file == names_from_mapping == [FIRST_COMPETITION_NAME, None, None]


def test_names_keep_working_after_the_save_is_closed(career_save_path: Path) -> None:
    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as career_save:
        competitions_table = career_save.competitions()
        stages_table = career_save.stages()

    assert career_save.closed
    assert competitions_table.where(id=FIRST_COMPETITION_ID)[0].name == FIRST_COMPETITION_NAME
    named_stage = stages_table.where(id=NAMED_COMPETITION_STAGE_ID)[0]
    assert named_stage.competition_name == FIRST_COMPETITION_NAME


def test_the_exported_columns_hold_the_mapped_names(career_save_path: Path, tmp_path: Path) -> None:
    """A name reaches CSV as its text and JSON as a string, and is empty and null without a map."""
    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as named_save:
        named_save.competitions().write_csv(tmp_path / "named.csv")
        named_save.stages().write_json(tmp_path / "named.json")
    with fmsave.open(career_save_path) as unnamed_save:
        unnamed_save.competitions().write_csv(tmp_path / "unnamed.csv")
        unnamed_save.stages().write_json(tmp_path / "unnamed.json")

    named_rows = list(
        csv.DictReader((tmp_path / "named.csv").read_text(encoding="utf-8").splitlines())
    )
    unnamed_rows = list(
        csv.DictReader((tmp_path / "unnamed.csv").read_text(encoding="utf-8").splitlines())
    )
    named_stage_rows = json.loads((tmp_path / "named.json").read_text(encoding="utf-8"))
    unnamed_stage_rows = json.loads((tmp_path / "unnamed.json").read_text(encoding="utf-8"))

    assert named_rows[0]["name"] == FIRST_COMPETITION_NAME
    assert unnamed_rows[0]["name"] == ""
    assert named_stage_rows[0]["competition_name"] == FIRST_COMPETITION_NAME
    assert unnamed_stage_rows[0]["competition_name"] is None


def test_a_cold_stages_read_with_a_name_map_decompresses_game_db_once(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming stages needs the competition index, and that index builds the stage index inside
    its own borrow, so the two come out of one decompression rather than one each.

    The section is decompressed where a loan starts, so counting the reads counts the
    decompressions.
    """
    sections_read: list[str] = []
    read_section = context_module.read_section

    def counting_read_section(container_index: ContainerIndex, name: str) -> bytes:
        sections_read.append(name)
        return read_section(container_index, name)

    monkeypatch.setattr(context_module, "read_section", counting_read_section)

    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as career_save:
        stages_table = career_save.stages()

    named_stage = stages_table.where(id=NAMED_COMPETITION_STAGE_ID)[0]
    assert named_stage.competition_name == FIRST_COMPETITION_NAME
    assert sections_read.count(GAME_DB_SECTION) == 1
