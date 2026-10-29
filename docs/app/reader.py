"""The save reader behind the fmsave web app.

The app's worker runs this module in Pyodide, next to fmsave installed from PyPI. It uses
only fmsave's public API, so it works with any released fmsave that has these readers. The
worker calls open_save, read_players, read_stats and close_save in that order, then
player_detail, stats_columns and write_csv on demand while the page is open.

Numbers cross to the page as packed little-endian float32 (or float64 for uids), one buffer
per column, with NaN for a missing value. Dates cross as days since 1970-01-01. Text crosses
as plain lists.
"""

from __future__ import annotations

import dataclasses
import math
import time
from array import array
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from operator import attrgetter
from typing import Any

import fmsave
from fmsave import export

# fmsave's own models name the fields, so a field added to them reaches the page too.
ATTRIBUTES = tuple(field.name for field in dataclasses.fields(fmsave.Attributes))
POSITIONS = tuple(field.name for field in dataclasses.fields(fmsave.Positions))
PERSONALITY = tuple(field.name for field in dataclasses.fields(fmsave.Personality))
# Every season-stats column that holds a number about the player's play.
STAT_SKIP = frozenset(
    {"player_uid", "player_name", "kind", "team_id", "club_uid", "club_name", "club_short_name"}
)
STAT_KINDS = ("overall", "league", "cup", "continental", "international")
STAT_ROLLUP_COLUMNS = ("team_slot",)

_EPOCH = date(1970, 1, 1)
_state: dict[str, Any] = {}


class AppError(Exception):
    """An error with a message that is safe to show: it never holds text from the save."""


def friendly_error(error: BaseException) -> str:
    """The message the page shows for an error, which never echoes save content."""
    if isinstance(error, AppError):
        return str(error)
    if isinstance(error, fmsave.NotAFmSaveError):
        return "This file is not a Football Manager save. Pick a .fm file from your games folder."
    if isinstance(error, fmsave.UnsupportedGameError):
        return (
            "This save comes from a game or build fmsave cannot read yet. fmsave reads "
            "Football Manager 26 saves."
        )
    if isinstance(error, fmsave.CorruptSaveError):
        return "This save looks damaged or incomplete. Try a fresh copy of the save file."
    if isinstance(error, fmsave.SaveChangedError):
        return "The save changed while it was being read. Wait for the game to finish saving."
    if isinstance(error, fmsave.FmsaveError):
        return f"fmsave could not read this save ({type(error).__name__})."
    if isinstance(error, MemoryError):
        return "The browser ran out of memory reading this save. Close other tabs and try again."
    return f"Something went wrong reading this save ({type(error).__name__})."


def _day(value: date | None) -> float:
    return math.nan if value is None else float((value - _EPOCH).days)


def _number(value: object) -> float:
    if value is None:
        return math.nan
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, date):
        return _day(value)
    return float(value)  # pyright: ignore[reportArgumentType]


def _pack(values: Iterable[object], code: str = "f") -> bytes:
    return array(code, map(_number, values)).tobytes()


def _label(coded: object) -> str | None:
    """The snake_case label of a coded value, or None when the code is not named."""
    if coded is None:
        return None
    label = getattr(coded, "label", None)
    if label is None or label.name == "UNKNOWN":
        return None
    return label.name.lower()


def _getter(*paths: str) -> Callable[[object], tuple[object, ...]]:
    get = attrgetter(*paths)
    if len(paths) == 1:
        return lambda record: (get(record),)
    return get


def _columns(records: Sequence[Any], names: Sequence[str], *paths: str) -> dict[str, list[object]]:
    get = _getter(*paths)
    rows = [get(record) for record in records]
    return {name: [row[index] for row in rows] if rows else [] for index, name in enumerate(names)}


def _optional_columns(
    records: Sequence[Any], group: str, fields: Sequence[str], prefix: str
) -> dict[str, list[object]]:
    get = _getter(*fields)
    blank = (None,) * len(fields)
    rows = [blank if (part := getattr(record, group)) is None else get(part) for record in records]
    return {f"{prefix}{field}": [row[index] for row in rows] for index, field in enumerate(fields)}


def player_numbers(players: Sequence[Any]) -> dict[str, list[object]]:
    """The numeric player columns the page shows, keyed by fmsave's export column names."""
    columns = _columns(
        players,
        (
            "uid",
            "club_uid",
            "age",
            "birth_date",
            "height_cm",
            "nation_id",
            "left_foot",
            "right_foot",
            "transfer_value",
            "raw_condition",
            "raw_match_sharpness",
            "on_loan",
            "loan_end",
            "club_join_date",
        ),
        "uid",
        "club_uid",
        "age",
        "birth_date",
        "height_cm",
        "nation_id",
        "left_foot",
        "right_foot",
        "transfer_value",
        "raw_condition",
        "raw_match_sharpness",
        "on_loan",
        "loan_end",
        "club_join_date",
    )
    columns |= _columns(
        players,
        ("ability_current", "ability_potential"),
        "ability.current",
        "ability.potential",
    )
    columns |= _columns(
        players,
        ("reputation_current", "reputation_home", "reputation_world"),
        "reputation.current",
        "reputation.home",
        "reputation.world",
    )
    columns |= _columns(
        players,
        [f"attributes_{name}" for name in ATTRIBUTES],
        *(f"attributes.{name}" for name in ATTRIBUTES),
    )
    columns |= _columns(
        players,
        [f"positions_{name}" for name in POSITIONS],
        *(f"positions.{name}" for name in POSITIONS),
    )
    columns |= _optional_columns(players, "personality", PERSONALITY, "personality_")
    columns |= _optional_columns(players, "contract", ("wage", "start", "end"), "contract_")
    return columns


def player_text(players: Sequence[Any]) -> dict[str, list[str | None]]:
    """The text player columns the page shows, keyed by fmsave's export column names."""
    contracts = [player.contract for player in players]
    return {
        "name": [player.name for player in players],
        "club_name": [player.club_name for player in players],
        "natural_positions": [" ".join(player.natural_positions) for player in players],
        "accomplished_positions": [" ".join(player.accomplished_positions) for player in players],
        "loan_parent_club_name": [player.loan_parent_club_name for player in players],
        "contract_squad_status": [
            None if contract is None else _label(contract.squad_status) for contract in contracts
        ],
        "contract_kind": [
            None if contract is None else _label(contract.kind) for contract in contracts
        ],
    }


def stat_names() -> list[str]:
    """The numeric season-stats columns, in fmsave's export order."""
    return [
        name
        for name in export.column_names(fmsave.PlayerSeasonStats)
        if name not in STAT_SKIP and name not in STAT_ROLLUP_COLUMNS
    ]


def stats_columns(kind: str) -> dict[str, bytes]:
    """One packed column per stat for one competition kind, aligned to the player order.

    A player with rows for more than one team in that kind gets the row with the most minutes,
    which is the team they played for most this season. A player with no row gets NaN.
    """
    if kind not in STAT_KINDS:
        raise AppError("Unknown competition.")
    stats = _state["stats"]
    order: dict[int, int] = _state["order"]
    chosen: dict[int, Any] = {}
    for row in stats:
        if row.kind != kind:
            continue
        index = order.get(row.player_uid)
        if index is None:
            continue
        best = chosen.get(index)
        if best is None or (row.minutes or 0) > (best.minutes or 0):
            chosen[index] = row
    names = stat_names()
    blank = (None,) * len(names)
    get = _getter(*names)
    rows = [get(chosen[index]) if index in chosen else blank for index in range(len(order))]
    return {name: _pack(row[position] for row in rows) for position, name in enumerate(names)}


def open_save(path: str) -> dict[str, object]:
    """Open the save at path and return what the page shows while the players load."""
    close_save()
    started = time.monotonic()
    career_save = fmsave.open(path)
    _state["save"] = career_save
    _state["started"] = started
    info = career_save.info
    managed = career_save.managed_clubs()
    club = managed[0] if managed else None
    _state["club_uid"] = None if club is None else club.club_uid
    return {
        "save": info.save_name,
        "date": None if info.game_date is None else info.game_date.isoformat(),
        "club": None if club is None else club.club_name,
        "club_uid": _state["club_uid"],
        "fmsave": fmsave.__version__,
    }


def read_players() -> dict[str, object]:
    """Read every named player and return the page's columns."""
    players = _state["save"].players().filter(lambda player: bool(player.name))
    _state["players"] = players
    _state["order"] = {player.uid: index for index, player in enumerate(players)}
    numbers = player_numbers(players)
    packed = {
        name: _pack(values, "d" if name in ("uid", "club_uid") else "f")
        for name, values in numbers.items()
    }
    return {
        "count": len(players),
        "numbers": packed,
        "text": player_text(players),
        "seconds": round(time.monotonic() - _state["started"], 1),
    }


def read_stats() -> dict[str, object]:
    """Read this season's stats, then close the save, and return the overall columns."""
    stats = _state["save"].player_season_stats()
    close_save()
    _state["stats"] = stats
    by_player: dict[int, list[Any]] = {}
    for row in stats:
        by_player.setdefault(row.player_uid, []).append(row)
    _state["stats_by_player"] = by_player
    return {
        "kind": "overall",
        "numbers": stats_columns("overall"),
        "seconds": round(time.monotonic() - _state["started"], 1),
    }


def close_save() -> None:
    """Close the open save, if any. The players and stats already read stay in memory."""
    career_save = _state.pop("save", None)
    if career_save is not None:
        career_save.close()


def player_detail(uid: int) -> dict[str, object]:
    """Everything fmsave reads about one player, plus their season-stats rows."""
    players = _state["players"]
    player = players.get_by_uid(uid)
    if player is None:
        raise AppError("That player is not in this save.")
    rows = [
        export.record_to_dict(row, json_ready=True)
        for row in _state.get("stats_by_player", {}).get(uid, ())
    ]
    return {"player": export.record_to_dict(player, json_ready=True), "stats": rows}


def write_csv(name: str, path: str) -> int:
    """Write one of the page's CSV downloads to path and return its row count."""
    players = _state["players"]
    if name == "players":
        table = players
    elif name == "squad":
        table = players.where(club_uid=_state["club_uid"])
    elif name == "season-stats":
        table = _state["stats"]
    else:
        raise AppError("Unknown download.")
    table.write_csv(path)
    return len(table)


ENTRY_POINTS: dict[str, Callable[..., object]] = {
    "open_save": open_save,
    "read_players": read_players,
    "read_stats": read_stats,
    "stats_columns": stats_columns,
    "player_detail": player_detail,
    "write_csv": write_csv,
}


def call(name: str, *args: object) -> dict[str, object]:
    """Run one entry point for the worker; an error comes back as a message safe to show."""
    try:
        return {"ok": ENTRY_POINTS[name](*args)}
    except Exception as error:  # noqa: BLE001 - every error reaches the page as a message
        close_save()
        return {"error": friendly_error(error)}
