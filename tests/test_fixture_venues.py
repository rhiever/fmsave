"""Neutral-venue votes when a club fields more than one team."""

from __future__ import annotations

from pathlib import Path

import fmsave
from tests.fixtures.career import (
    CUP_FIXTURE_STAGE_ID,
    FIXTURE_STAGE_ID,
    HOME_STADIUM_ORDINAL,
    LEAGUE_KICK_OFF_SLOT,
    NORTHBRIDGE_TEAM_A,
    NORTHBRIDGE_TEAM_B,
    SOUTHPORT_TEAM,
    ExampleFixture,
    career_fragment,
)

# Northbridge's reserve side plays more home matches at its own ground than the first team plays
# at the stadium, and once at the stadium itself.
RESERVE_GROUND_ORDINAL = 30
RESERVE_HOME_MATCHES = 6
RESERVE_FIXTURES = (
    *(
        ExampleFixture(
            FIXTURE_STAGE_ID,
            NORTHBRIDGE_TEAM_B,
            SOUTHPORT_TEAM,
            140 + 7 * index,
            LEAGUE_KICK_OFF_SLOT,
            20 + index,
            True,
            RESERVE_GROUND_ORDINAL,
        )
        for index in range(RESERVE_HOME_MATCHES)
    ),
    ExampleFixture(
        FIXTURE_STAGE_ID,
        NORTHBRIDGE_TEAM_B,
        SOUTHPORT_TEAM,
        190,
        LEAGUE_KICK_OFF_SLOT,
        30,
        True,
        HOME_STADIUM_ORDINAL,
    ),
)


def test_a_reserve_sides_ground_does_not_outvote_the_first_teams(tmp_path: Path) -> None:
    """Each team has its own usual ground, and any of the club's usual grounds is a home one."""
    career_path = career_fragment(extra_fixtures=RESERVE_FIXTURES).write(
        tmp_path / "Private Folder" / "career example.fm"
    )

    with fmsave.open(career_path) as career_save:
        fixtures_table = career_save.fixtures()

    reserves = fixtures_table.where(home_team_id=NORTHBRIDGE_TEAM_B)
    assert len(reserves) == RESERVE_HOME_MATCHES + 1
    assert all(fixture.is_neutral_venue is False for fixture in reserves)
    # Only the cup tie at a third ground is neutral; the league matches at the stadium are not.
    first_team = fixtures_table.where(home_team_id=NORTHBRIDGE_TEAM_A)
    assert [fixture.is_neutral_venue for fixture in first_team] == [
        fixture.stage_id == CUP_FIXTURE_STAGE_ID for fixture in first_team
    ]
    assert any(fixture.is_neutral_venue for fixture in first_team)
