"""Position-specific scouting scores from player attributes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from functools import cache
from importlib.resources import files
from operator import attrgetter
from typing import ClassVar, TypedDict, cast

from fmsave._status import register_field_statuses
from fmsave.models.players import Player
from fmsave.table import Table

_POSITION_CODES = {
    "GK": ("GK",),
    "CB": ("DC", "SW"),
    "FB/WB": ("DL", "DR", "WBL", "WBR"),
    "DM": ("DM",),
    "CM": ("MC",),
    "AM": ("AMC",),
    "WIDE": ("ML", "MR", "AML", "AMR"),
    "ST": ("ST", "STC"),
}
#: Position codes accepted by the scouting scorer and exports.
SCOUTING_POSITIONS = tuple(_POSITION_CODES)
_PLAYER_FIELDS = tuple(field.name for field in fields(Player))


class _Formula(TypedDict):
    intercept: float
    weights: list[tuple[str, float]]


@cache
def _models() -> dict[str, dict[str, _Formula]]:
    return json.loads(files("fmsave").joinpath("_scouting_v1.json").read_text(encoding="utf-8"))[
        "models"
    ]


def _position_code(position: str) -> str:
    code = position.strip().upper()
    if code not in _POSITION_CODES:
        raise ValueError(f"Unknown scouting position. Use {', '.join(SCOUTING_POSITIONS)}.")
    return code


@cache
def _formula(
    position: str, model: str
) -> tuple[float, tuple[tuple[attrgetter[int | None], int, float], ...]]:
    models = _models()
    if model not in models:
        raise ValueError("Unknown scouting model. Use 'full' or 'visible'.")
    fit = models[model][position]
    inputs = tuple(
        (
            cast(
                "attrgetter[int | None]",
                attrgetter("ability.current" if name == "ca" else f"attributes.{name}"),
            ),
            200 if name == "ca" else 20,
            weight,
        )
        for name, weight in fit["weights"]
    )
    return fit["intercept"], inputs


def scouting_score(player: Player, position: str, *, model: str = "full") -> float | None:
    """Rank a player at a natural position by expected future league match rating.

    The full model uses visible attributes, current ability, and hidden performance attributes.
    Pass `model="visible"` to use visible attributes only. The scores are a research preview.

    Returns:
        A score in match-rating units, or None when the player cannot be scored at this
        position or a required input is missing or outside its range.

    Raises:
        ValueError: The scouting position or model is unknown.
    """
    code = _position_code(position)
    score, inputs = _formula(code, model)
    if not any(slot in _POSITION_CODES[code] for slot in player.natural_positions):
        return None
    for get, upper, weight in inputs:
        value = get(player)
        if value is None or not 1 <= value <= upper:
            return None
        score += value * weight
    return score


@dataclass(frozen=True, slots=True)
class ScoutedPlayer(Player):
    """A player prepared for export with scores for a selected scouting position."""

    COMPUTED_FIELDS: ClassVar[tuple[str, ...]] = ("scouting_score_full", "scouting_score_visible")

    scouting_position: str

    @property
    def scouting_score_full(self) -> float | None:
        """The full scouting score, when its inputs are available."""
        return scouting_score(self, self.scouting_position)

    @property
    def scouting_score_visible(self) -> float | None:
        """The scouting score using visible attributes, when available."""
        return scouting_score(self, self.scouting_position, model="visible")


register_field_statuses(
    ScoutedPlayer,
    verified=("scouting_position",),
    unconfirmed=ScoutedPlayer.COMPUTED_FIELDS,
)


def _scouted_players(players: Iterable[Player], position: str) -> Iterator[ScoutedPlayer]:
    code = _position_code(position)
    for player in players:
        yield ScoutedPlayer(
            *(getattr(player, name) for name in _PLAYER_FIELDS), scouting_position=code
        )


def scout_players(players: Iterable[Player], position: str) -> Table[ScoutedPlayer]:
    """Add scouting columns to a player table for the selected position.

    Use the result with the ordinary table export methods. Players outside the selected
    position stay in the table with blank scores.

    Raises:
        ValueError: The scouting position is unknown.
    """
    return Table(_scouted_players(players, position), ScoutedPlayer)
