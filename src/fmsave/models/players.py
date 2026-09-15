"""Player records: identity, ability, reputation, club, positions, attributes and traits.

Person fields (name, birth date, nationality, home-grown ids, personality and traits) are
filled by a later reader pass; this module's Player carries them from the start so later
tasks only need to fill values in, never change the field list. Adjusted and raw attributes
share one coverage row per attribute, so one Attributes class serves both `attributes` (the
1 to 20 display scale) and `raw_attributes` (the 1 to 100 raw scale).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import IntEnum

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue, TransferValueState


@dataclass(frozen=True, slots=True)
class Ability:
    """A player's current and potential ability.

    Attributes:
        current: Current ability (unconfirmed).
        potential: Potential ability, or None when the save stores a range code instead
            (unconfirmed).
        potential_range_code: The stored negative code when potential is unknown, else None
            (unconfirmed).
    """

    current: int
    potential: int | None
    potential_range_code: int | None


@dataclass(frozen=True, slots=True)
class Reputation:
    """A player's reputation figures.

    Never threshold on bucket: it is a coarse, lossy bucket that mis-orders players. Use
    current to rank players instead.

    Attributes:
        bucket: Coarse reputation bucket that loses precision (unconfirmed).
        home: Home reputation.
        current: Current reputation.
        world: World reputation.
    """

    bucket: int
    home: int
    current: int
    world: int


@dataclass(frozen=True, slots=True)
class Attributes:
    """52 non-foot player attributes, shared by the display and raw scales.

    Attributes:
        crossing: Crossing.
        dribbling: Dribbling.
        finishing: Finishing.
        heading: Heading.
        long_shots: Long shots.
        marking: Marking.
        off_the_ball: Off the ball movement.
        passing: Passing.
        penalty_taking: Penalty taking.
        tackling: Tackling.
        vision: Vision.
        one_on_ones: Goalkeeping one-on-ones.
        aerial_reach: Goalkeeping aerial reach.
        command_of_area: Goalkeeping command of area.
        communication: Goalkeeping communication.
        kicking: Goalkeeping kicking.
        throwing: Goalkeeping throwing.
        anticipation: Anticipation.
        decisions: Decisions.
        handling: Goalkeeping handling.
        positioning: Positioning (an attribute, not a position rating).
        reflexes: Goalkeeping reflexes.
        first_touch: First touch.
        technique: Technique.
        flair: Flair.
        corners: Corners.
        teamwork: Teamwork.
        work_rate: Work rate.
        long_throws: Long throws.
        eccentricity: Goalkeeping eccentricity.
        rushing_out: Goalkeeping tendency to rush out.
        punching: Goalkeeping tendency to punch crosses.
        acceleration: Acceleration.
        free_kick_taking: Free kick taking.
        strength: Strength.
        stamina: Stamina.
        pace: Pace.
        jumping_reach: Jumping reach.
        leadership: Leadership.
        dirtiness: Dirtiness, a hidden attribute.
        balance: Balance.
        bravery: Bravery.
        consistency: Consistency, a hidden attribute.
        aggression: Aggression.
        agility: Agility.
        important_matches: Big-match temperament, a hidden attribute.
        injury_proneness: Injury proneness, a hidden attribute.
        versatility: Versatility, a hidden attribute.
        natural_fitness: Natural fitness.
        determination: Determination.
        composure: Composure.
        concentration: Concentration.
    """

    crossing: int
    dribbling: int
    finishing: int
    heading: int
    long_shots: int
    marking: int
    off_the_ball: int
    passing: int
    penalty_taking: int
    tackling: int
    vision: int
    one_on_ones: int
    aerial_reach: int
    command_of_area: int
    communication: int
    kicking: int
    throwing: int
    anticipation: int
    decisions: int
    handling: int
    positioning: int
    reflexes: int
    first_touch: int
    technique: int
    flair: int
    corners: int
    teamwork: int
    work_rate: int
    long_throws: int
    eccentricity: int
    rushing_out: int
    punching: int
    acceleration: int
    free_kick_taking: int
    strength: int
    stamina: int
    pace: int
    jumping_reach: int
    leadership: int
    dirtiness: int
    balance: int
    bravery: int
    consistency: int
    aggression: int
    agility: int
    important_matches: int
    injury_proneness: int
    versatility: int
    natural_fitness: int
    determination: int
    composure: int
    concentration: int


@dataclass(frozen=True, slots=True)
class Positions:
    """The 15 position ratings, in the player rating array order.

    This is not the tactic or per-match position mask order.

    Attributes:
        gk: Goalkeeper.
        sw: Sweeper.
        dl: Left back.
        dc: Centre back.
        dr: Right back.
        dm: Defensive midfielder.
        ml: Left midfielder.
        mc: Central midfielder.
        mr: Right midfielder.
        aml: Attacking midfielder, left.
        amc: Attacking midfielder, centre.
        amr: Attacking midfielder, right.
        stc: Striker.
        wbl: Left wing back.
        wbr: Right wing back.
    """

    gk: int
    sw: int
    dl: int
    dc: int
    dr: int
    dm: int
    ml: int
    mc: int
    mr: int
    aml: int
    amc: int
    amr: int
    stc: int
    wbl: int
    wbr: int


@dataclass(frozen=True, slots=True)
class Personality:
    """A player's personality profile.

    Attributes:
        adaptability: Adaptability.
        ambition: Ambition.
        loyalty: Loyalty.
        pressure: Pressure.
        professionalism: Professionalism.
        sportsmanship: Sportsmanship.
        temperament: Temperament.
        controversy: Controversy.
    """

    adaptability: int
    ambition: int
    loyalty: int
    pressure: int
    professionalism: int
    sportsmanship: int
    temperament: int
    controversy: int


class Trait(IntEnum):
    """A named player trait; UNKNOWN keeps the bit number in CodedValue.raw."""

    UNKNOWN = -1
    RUNS_WITH_BALL_DOWN_LEFT = 0
    RUNS_WITH_BALL_DOWN_RIGHT = 1
    RUNS_WITH_BALL_THROUGH_CENTRE = 2
    MOVES_INTO_CHANNELS = 4
    GETS_FORWARD_WHENEVER_POSSIBLE = 5
    TRIES_KILLER_BALLS_OFTEN = 7
    LIKES_TO_TRY_TO_BEAT_OFFSIDE_TRAP = 13
    COMES_DEEP_TO_GET_BALL = 19
    DICTATES_TEMPO = 22
    KNOCKS_BALL_PAST_OPPONENT = 27
    DIVES_INTO_TACKLES = 37
    TRIES_LONG_RANGE_PASSES = 43
    RUNS_WITH_BALL_OFTEN = 51
    CROSSES_EARLY = 59


@dataclass(frozen=True, slots=True)
class Player:
    """A player record from the save's game database.

    Person fields (name, birth date, nationality, home-grown ids, personality and traits)
    come from the player's person block; they stay None or empty when no block validates.
    Contract and suspension fields are appended by later tasks.

    Attributes:
        uid: The player's id in the game database (unconfirmed).
        name: Display name: common name first, else first plus last name, else legal name
            (unconfirmed).
        first_name: First name (unconfirmed).
        last_name: Last name (unconfirmed).
        common_name: Common (nickname) name, when the save stores one (unconfirmed).
        full_name: First name plus last name, or None when either is missing (unconfirmed).
        legal_name: Legal name, when it differs from the display name (unconfirmed).
        birth_date: Date of birth (unconfirmed).
        age: Age at the save's in-game clock date, or None when birth_date or the clock
            date is unreadable (unconfirmed).
        nation_id: Id of the player's primary nation (unconfirmed).
        second_nation_ids: Ids of the player's other eligible nations.
        home_grown_nation_ids: Ids of nations the player is considered home grown for.
        home_grown_club_uids: Uids of clubs the player is considered home grown for, in
            relation-list order; an entry is None when its club index does not resolve, but
            still keeps its position.
        home_grown_club_names: Denormalised names for home_grown_club_uids, in the same
            order; None wherever home_grown_club_uids is None.
        height_cm: Height in centimetres (unconfirmed).
        ability: Current and potential ability.
        reputation: Reputation figures; never threshold on reputation.bucket.
        club_uid: Uid of the club fielding the player's registered team, or None for a free
            agent or an unresolved team (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        club_short_name: Denormalised short name of club_uid (unconfirmed).
        club_nation_id: Denormalised league nation id of club_uid (unconfirmed).
        club_fa_nation_id: Denormalised FA nation id of club_uid (unconfirmed).
        club_reputation: Denormalised reputation of club_uid.
        club_last_league_position: Denormalised last completed season league position of
            club_uid.
        team_id: Id of the player's registered team, or None for a free agent
            (unconfirmed).
        team_slot: The team's slot in its club's team list, or None when team_id does not
            resolve to a club (unconfirmed).
        club_join_date: Date the player joined his current club; it disagrees with the
            contract start date for about half of players, so it is not a substitute for it
            (unconfirmed).
        natural_positions: Position codes rated at least 18, best first.
        accomplished_positions: Position codes rated 15 to 17, best first. This is an
            fmsave classifier label, not text the game itself shows.
        personality: Personality profile, or None when no person block validates.
        attributes: The 52 non-foot attributes, on the 1 to 20 display scale.
        raw_attributes: The same 52 attributes, on the 1 to 100 raw scale.
        left_foot: Left foot strength, on the 1 to 20 display scale.
        right_foot: Right foot strength, on the 1 to 20 display scale.
        raw_left_foot: Left foot strength, on the 1 to 100 raw scale.
        raw_right_foot: Right foot strength, on the 1 to 100 raw scale.
        positions: The 15 position ratings.
        transfer_value: Transfer value in the save's base currency, set only when
            transfer_value_state is OK.
        transfer_value_state: How transfer_value was read from the save (unconfirmed).
        condition: Condition, on a 0 to 10000 raw scale.
        match_sharpness: Match sharpness, on a 0 to 10000 raw scale.
        traits: Named player traits; an unnamed bit is Trait.UNKNOWN with raw set to the
            bit number.
        trait_bits: The raw trait bitmask, or None when no person block validates.
    """

    uid: int
    name: str | None
    first_name: str | None
    last_name: str | None
    common_name: str | None
    full_name: str | None
    legal_name: str | None
    birth_date: date | None
    age: int | None
    nation_id: int | None
    second_nation_ids: tuple[int, ...]
    home_grown_nation_ids: tuple[int, ...]
    home_grown_club_uids: tuple[int | None, ...]
    home_grown_club_names: tuple[str | None, ...]
    height_cm: int
    ability: Ability
    reputation: Reputation
    club_uid: int | None
    club_name: str | None
    club_short_name: str | None
    club_nation_id: int | None
    club_fa_nation_id: int | None
    club_reputation: int | None
    club_last_league_position: int | None
    team_id: int | None
    team_slot: int | None
    club_join_date: date | None
    natural_positions: tuple[str, ...]
    accomplished_positions: tuple[str, ...]
    personality: Personality | None
    attributes: Attributes
    raw_attributes: Attributes
    left_foot: int
    right_foot: int
    raw_left_foot: int
    raw_right_foot: int
    positions: Positions
    transfer_value: int | None
    transfer_value_state: TransferValueState
    condition: int
    match_sharpness: int
    traits: tuple[CodedValue[Trait], ...]
    trait_bits: int | None


register_field_statuses(Ability, unconfirmed=("current", "potential", "potential_range_code"))
register_field_statuses(Reputation, verified=("home", "current", "world"), unconfirmed=("bucket",))
register_field_statuses(
    Attributes,
    verified=(
        "crossing",
        "dribbling",
        "finishing",
        "heading",
        "long_shots",
        "marking",
        "off_the_ball",
        "passing",
        "penalty_taking",
        "tackling",
        "vision",
        "one_on_ones",
        "aerial_reach",
        "command_of_area",
        "communication",
        "kicking",
        "throwing",
        "anticipation",
        "decisions",
        "handling",
        "positioning",
        "reflexes",
        "first_touch",
        "technique",
        "flair",
        "corners",
        "teamwork",
        "work_rate",
        "long_throws",
        "eccentricity",
        "rushing_out",
        "punching",
        "acceleration",
        "free_kick_taking",
        "strength",
        "stamina",
        "pace",
        "jumping_reach",
        "leadership",
        "dirtiness",
        "balance",
        "bravery",
        "consistency",
        "aggression",
        "agility",
        "important_matches",
        "injury_proneness",
        "versatility",
        "natural_fitness",
        "determination",
        "composure",
        "concentration",
    ),
)
register_field_statuses(
    Positions,
    verified=(
        "gk",
        "sw",
        "dl",
        "dc",
        "dr",
        "dm",
        "ml",
        "mc",
        "mr",
        "aml",
        "amc",
        "amr",
        "stc",
        "wbl",
        "wbr",
    ),
)
register_field_statuses(
    Personality,
    verified=(
        "adaptability",
        "ambition",
        "loyalty",
        "pressure",
        "professionalism",
        "sportsmanship",
        "temperament",
        "controversy",
    ),
)
register_field_statuses(
    Player,
    verified=(
        "second_nation_ids",
        "home_grown_nation_ids",
        "home_grown_club_uids",
        "home_grown_club_names",
        "club_reputation",
        "club_last_league_position",
        "natural_positions",
        "accomplished_positions",
        "left_foot",
        "right_foot",
        "raw_left_foot",
        "raw_right_foot",
        "transfer_value",
        "condition",
        "match_sharpness",
        "traits",
        "trait_bits",
    ),
    unconfirmed=(
        "uid",
        "name",
        "first_name",
        "last_name",
        "common_name",
        "full_name",
        "legal_name",
        "birth_date",
        "age",
        "nation_id",
        "height_cm",
        "club_uid",
        "club_name",
        "club_short_name",
        "club_nation_id",
        "club_fa_nation_id",
        "team_id",
        "team_slot",
        "club_join_date",
        "transfer_value_state",
    ),
)
