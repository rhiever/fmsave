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
from fmsave import checks
from fmsave._container import ContainerIndex
from fmsave._frozen import FrozenMapping
from fmsave.models.suspensions import SuspensionScope
from fmsave.name_maps import normalize_competition_names, read_competition_names
from fmsave.readers._common import GAME_DB_SECTION
from tests.fixtures.career import (
    FIRST_COMPETITION_DATABASE_ID,
    FIRST_COMPETITION_ID,
    PLAYER_A_UID,
    SECOND_COMPETITION_DATABASE_ID,
    SECOND_COMPETITION_ID,
    THIRD_COMPETITION_DATABASE_ID,
    THIRD_COMPETITION_ID,
)

FIRST_COMPETITION_NAME = "Example League"
SECOND_COMPETITION_NAME = "Example Cup"
THIRD_COMPETITION_NAME = "Example Shield"
NAME_FILE_NAME = "names.csv"
PRIVATE_FOLDER_NAME = "Private Folder"
# Stage 1 belongs to the first competition and stage 3 to the second, which the map never names.
NAMED_COMPETITION_STAGE_ID = 1
UNNAMED_COMPETITION_STAGE_ID = 3
FIRST_COMPETITION_ONLY = {FIRST_COMPETITION_DATABASE_ID: FIRST_COMPETITION_NAME}
# The name of the gate a broken competition decode is made to fail on.
BROKEN_GATE_NAME = "fictional_competition_gate"


def failing_competition_gates(*_arguments: object) -> tuple[checks.GateResult, ...]:
    """One competition check that fails, standing in for a decode that came out wrong."""
    return (checks.GateResult(BROKEN_GATE_NAME, 0.0, 1.0, None, passed=False, applied=True),)


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
        # A database id is plain digits, so a first cell that is signed is no more an id than
        # a word is, and the header rule takes it for the heading it looks like.
        pytest.param(
            "-1,Example League\n12345,Example Cup\n",
            {12345: "Example Cup"},
            id="signed-first-cell-read-as-a-header",
        ),
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
        # `int` reads all four of these, and a database id is none of them: a negative id is
        # nonsense, and the rest let one id be written several ways, each looking up a key
        # none of the others would.
        pytest.param(
            "12345,Example League\n-5,Example Cup\n",
            ("line 2", "'-5' is not a competition database id"),
            id="negative-id",
        ),
        pytest.param(
            "12345,Example League\n12_345,Example Cup\n",
            ("line 2", "'12_345' is not a competition database id"),
            id="underscored-id",
        ),
        pytest.param(
            "12345,Example League\n١٢٣,Example Cup\n",
            ("line 2", "is not a competition database id"),
            id="id-in-another-script",
        ),
        # An extra column leaves the row ambiguous, so it is refused as firmly as a missing
        # one, and the message says how to write a name that holds a comma.
        pytest.param(
            "12345,Example League,Example Cup\n",
            ("line 1", "expected 2 columns, found 3", "put quotes around a name"),
            id="three-column-row",
        ),
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
        # A name of nothing but spaces is as empty as one of nothing, and the CSV path has
        # always said so; a mapping that took it would break the two forms' equivalence.
        pytest.param({1: "   "}, ValueError, id="name-of-nothing-but-spaces"),
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
        suspensions_table = career_save.suspensions()

    assert all(competition.name is None for competition in competitions_table)
    assert all(stage.competition_name is None for stage in stages_table)
    assert all(suspension.competition_name is None for suspension in suspensions_table)


def test_a_ban_is_named_only_when_it_covers_one_competition(career_save_path: Path) -> None:
    """The nation-wide ban stores the third competition's id as its nation id. Naming it would
    put that competition's name on a ban that has nothing to do with it, so the scope decides
    whether a lookup happens at all.
    """
    names = {
        FIRST_COMPETITION_DATABASE_ID: FIRST_COMPETITION_NAME,
        THIRD_COMPETITION_DATABASE_ID: THIRD_COMPETITION_NAME,
    }
    with fmsave.open(career_save_path, competition_names=names) as career_save:
        suspensions_table = career_save.suspensions()
        player = career_save.players().by_uid(PLAYER_A_UID)

    competition_ban, nation_ban = suspensions_table
    assert competition_ban.scope is SuspensionScope.COMPETITION
    assert competition_ban.competition_id == FIRST_COMPETITION_ID
    assert competition_ban.competition_name == FIRST_COMPETITION_NAME
    assert nation_ban.scope is SuspensionScope.NATION
    assert nation_ban.nation_id == THIRD_COMPETITION_ID
    assert nation_ban.competition_id is None
    assert nation_ban.competition_name is None
    # The player's own copy of each ban is named by the same lookup.
    assert [ban.competition_name for ban in player.suspensions] == [FIRST_COMPETITION_NAME, None]


def test_a_ban_on_a_competition_the_map_does_not_list_stays_unnamed(
    career_save_path: Path,
) -> None:
    """A competition the game itself created carries a database id no outside name source
    holds, and this is what a reader sees for one: an id, and no name.
    """
    with fmsave.open(
        career_save_path, competition_names={THIRD_COMPETITION_DATABASE_ID: THIRD_COMPETITION_NAME}
    ) as career_save:
        competition_ban = career_save.suspensions()[0]

    assert competition_ban.competition_id == FIRST_COMPETITION_ID
    assert competition_ban.competition_name is None


def test_a_csv_path_and_a_mapping_name_the_same_competitions(
    career_save_path: Path, tmp_path: Path
) -> None:
    """The same text names the same competitions whichever form it arrives in.

    Both sides are padded, because padding is where the two forms could most easily drift
    apart: a reader who pastes ids and names out of a spreadsheet into a dict literal carries
    the spreadsheet's trailing spaces with them, and a map whose names kept them would put the
    padding into every exported name column while the file form quietly stripped it.
    """
    csv_path = write_names_csv(
        tmp_path,
        f"database_id,name\n  {FIRST_COMPETITION_DATABASE_ID}  ,  {FIRST_COMPETITION_NAME}  \n",
    )
    padded_mapping = {FIRST_COMPETITION_DATABASE_ID: f"  {FIRST_COMPETITION_NAME}  "}

    with fmsave.open(career_save_path, competition_names=str(csv_path)) as from_file:
        names_from_file = [competition.name for competition in from_file.competitions()]
    with fmsave.open(career_save_path, competition_names=padded_mapping) as from_mapping:
        names_from_mapping = [competition.name for competition in from_mapping.competitions()]

    assert names_from_file == names_from_mapping == [FIRST_COMPETITION_NAME, None, None]


def test_a_failing_competition_check_leaves_stages_unable_to_name_anything(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competition decode that fails its checks must stop `stages()` as surely as it stops
    `competitions()`.

    Every name a stage row carries is read out of the competition index, so a stage table
    named from an index whose checks never ran would be the broken-decode rule with a hole in
    it: a build that mis-paired entity ids with database ids would put another competition's
    name on every stage row, and a reader who called only `stages()` would see no error at all.
    """

    monkeypatch.setattr(checks, "evaluate_competitions", failing_competition_gates)

    with fmsave.open(career_save_path, competition_names=FIRST_COMPETITION_ONLY) as career_save:
        with pytest.raises(checks.GateCheckError) as stages_error:
            career_save.stages()
        with pytest.raises(checks.GateCheckError):
            career_save.competitions()

    message = str(stages_error.value)
    assert "competitions failed checks" in message
    assert BROKEN_GATE_NAME in message


def test_a_failing_competition_check_leaves_an_unnamed_save_reading_stages(
    career_save_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a map the stage table names nothing, so it needs no competition index and the
    competition checks are none of its business."""

    monkeypatch.setattr(checks, "evaluate_competitions", failing_competition_gates)

    with fmsave.open(career_save_path) as career_save:
        stages_table = career_save.stages()

    assert all(stage.competition_name is None for stage in stages_table)


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
