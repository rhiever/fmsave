from dataclasses import replace
from pathlib import Path

import pytest

import fmsave
from fmsave import export


def test_uses_the_selected_position_and_model(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as save:
        sample = next(iter(save.players()))
    player = replace(sample, natural_positions=("DC", "STC"))
    stronger = replace(
        player, attributes=replace(player.attributes, consistency=player.attributes.consistency + 1)
    )

    full = fmsave.scouting_score(player, "CB")
    visible = fmsave.scouting_score(player, "CB", model="visible")
    assert full is not None and visible is not None
    assert fmsave.scouting_score(player, "ST") != full
    assert fmsave.scouting_score(player, "GK") is None
    improved = fmsave.scouting_score(stronger, "CB")
    assert improved is not None and improved > full
    assert fmsave.scouting_score(stronger, "CB", model="visible") == visible


def test_missing_required_input_leaves_only_the_affected_score_blank(
    career_save_path: Path,
) -> None:
    with fmsave.open(career_save_path) as save:
        sample = next(iter(save.players()))
    player = replace(sample, natural_positions=("DC",), ability=replace(sample.ability, current=0))

    assert fmsave.scouting_score(player, "CB") is None
    assert fmsave.scouting_score(player, "CB", model="visible") is not None
    with pytest.raises(ValueError, match="position"):
        fmsave.scouting_score(player, "unknown")
    with pytest.raises(ValueError, match="model"):
        fmsave.scouting_score(player, "CB", model="unknown")


def test_table_adds_exportable_scores_and_keeps_unscored_players(career_save_path: Path) -> None:
    with fmsave.open(career_save_path) as save:
        sample = next(iter(save.players()))
    player = replace(sample, natural_positions=("DC",))
    another = replace(sample, uid=sample.uid + 1, natural_positions=("STC",))
    players = fmsave.Table((player, another), fmsave.Player)
    scored = fmsave.scout_players(players, "CB")
    columns = scored.to_columns()

    assert columns["uid"] == [player.uid, another.uid]
    assert columns["scouting_position"] == ["CB", "CB"]
    assert columns["scouting_score_full"] == [fmsave.scouting_score(player, "CB"), None]
    assert columns["scouting_score_visible"] == [
        fmsave.scouting_score(player, "CB", model="visible"),
        None,
    ]
    assert "scouting_position" not in players.to_columns()
    assert set(scored[:0].to_columns()) == set(export.column_names(fmsave.ScoutedPlayer))

    assert fmsave.field_status(fmsave.ScoutedPlayer, "name") == fmsave.field_status(
        fmsave.Player, "name"
    )
    assert fmsave.field_status(fmsave.ScoutedPlayer, "scouting_score_full") == "unconfirmed"
