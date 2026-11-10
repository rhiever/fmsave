"""Per-match team statistics: what each side did in one match whose report the save keeps.

The game keeps reports for some matches only, mostly recent ones, so a played fixture can have
no rows. Rows join to `fixtures()` on `competition_id`, `home_team_id`, `away_team_id` and
`date`, all in the same id spaces `fixtures()` uses.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class TeamMatchStats:
    """One team's statistics in one match, as the game's match stats screen shows them.

    A match gives two rows, one per team. Counts are summed over the team's matchday squad.
    The game truncates distance and percentages of completed passes, crosses and tackles on
    screen; the stored values are kept here.

    Attributes:
        competition_id: Id of the competition, as `Fixture.competition_id`.
        home_team_id: The home side's team id, as `Fixture.home_team_id`.
        away_team_id: The away side's team id, as `Fixture.away_team_id`.
        date: The kick-off date, as `Fixture.date`.
        kick_off_time: The kick-off time of day, as `Fixture.kick_off_time`.
        team_id: The team this row describes, one of the two above.
        is_home: Whether the row describes the home side.
        detailed_report: Whether the game kept the longer report format for this match. Only
            that format carries progressive passes (unconfirmed).
        players: Player records in the team's matchday squad, starters and substitutes
            (unconfirmed).
        shots: Shots.
        shots_on_target: Shots on target.
        blocked_shots: The team's shots that were blocked.
        shots_outside_box: Shots from outside the box, which the screen calls long shots.
        clear_cut_chances: Clear-cut chances the team had.
        woodwork: Shots that hit the woodwork.
        fouls_made: Fouls committed.
        offsides: Offsides.
        yellow_cards: Yellow cards.
        red_cards: Red cards.
        crosses_attempted: Crosses attempted.
        crosses_completed: Crosses completed.
        tackles_attempted: Tackles attempted.
        tackles_completed: Tackles won.
        aerial_challenges_attempted: Aerial challenges attempted.
        headers_won: Aerial challenges won.
        distance_km: Distance covered by the squad, in kilometres.
        expected_goals: Expected goals (xG).
        non_penalty_expected_goals: Expected goals from shots other than penalties (npxG).
        corners: Corners.
        passes_attempted: Passes attempted.
        passes_completed: Passes completed. A few rows store more than were attempted, and the
            game shows them the same way.
        final_third_passes: Passes into the final third.
        progressive_passes: Progressive passes, or None when the report is not detailed,
            because the game shows them only for detailed reports.
        possession_percent: The team's share of both sides' completed passes, in whole percent.
            The home share is rounded and the away share is the rest, so a pair sums to 100.
        ball_distribution_percent: The screen's ball distribution between players, in whole
            percent. Each side is rounded half up on its own, so a pair can sum to 101.
    """

    competition_id: int
    home_team_id: int
    away_team_id: int
    date: datetime.date
    kick_off_time: datetime.time
    team_id: int
    is_home: bool
    detailed_report: bool
    players: int
    shots: int
    shots_on_target: int
    blocked_shots: int
    shots_outside_box: int
    clear_cut_chances: int
    woodwork: int
    fouls_made: int
    offsides: int
    yellow_cards: int
    red_cards: int
    crosses_attempted: int
    crosses_completed: int
    tackles_attempted: int
    tackles_completed: int
    aerial_challenges_attempted: int
    headers_won: int
    distance_km: float
    expected_goals: float
    non_penalty_expected_goals: float
    corners: int
    passes_attempted: int
    passes_completed: int
    final_third_passes: int
    progressive_passes: int | None
    possession_percent: int
    ball_distribution_percent: int


register_field_statuses(
    TeamMatchStats,
    verified=(
        "competition_id",
        "home_team_id",
        "away_team_id",
        "date",
        "kick_off_time",
        "team_id",
        "is_home",
        "shots",
        "shots_on_target",
        "blocked_shots",
        "shots_outside_box",
        "clear_cut_chances",
        "woodwork",
        "fouls_made",
        "offsides",
        "yellow_cards",
        "red_cards",
        "crosses_attempted",
        "crosses_completed",
        "tackles_attempted",
        "tackles_completed",
        "aerial_challenges_attempted",
        "headers_won",
        "distance_km",
        "expected_goals",
        "non_penalty_expected_goals",
        "corners",
        "passes_attempted",
        "passes_completed",
        "final_third_passes",
        "progressive_passes",
        "possession_percent",
        "ball_distribution_percent",
    ),
    unconfirmed=("detailed_report", "players"),
)
