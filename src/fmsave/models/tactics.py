"""The manager's tactics, set-piece routines and selections, as the save stores them per team.

**A tactic belongs to a team, not to a club.** The save keeps a separate copy of each tactic
for each team that uses it, so a manager with two tactics and two teams using them has four
records, and the copies are not byte-identical. A row here is one stored copy, keyed on the
team and the tactic's place in that team's own list, and the same tactic name appears once per
team.

The seven mentality codes carry the words the game shows, and labels cover 12 position
bits. The remaining position bits read `UNKNOWN`. Some roles have labels based on the
position and the final setting unit in each phase. The 19 team instruction bytes and the
24-byte setting units are available as raw numbers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


class Mentality(IntEnum):
    """How attacking a tactic's mentality is, in the game's own words.

    The seven codes are the seven mentalities the game offers, in the order it lists them, and
    the manager of the save they were read from confirmed the list against his own tactics: the
    tactic showing Attacking stores 6 and the two showing Balanced store 4. A code outside the
    seven is UNKNOWN and keeps its raw number.
    """

    UNKNOWN = -1
    VERY_DEFENSIVE = 1
    DEFENSIVE = 2
    CAUTIOUS = 3
    BALANCED = 4
    POSITIVE = 5
    ATTACKING = 6
    VERY_ATTACKING = 7


class TacticPosition(IntEnum):
    """One position of a tactic's formation.

    A member's value is the bit number set in a slot's position mask, counting from zero. This
    is deliberately **not** the same enum as `fmsave.models.matches.MatchPosition`, whose codes
    come from a different field and are ordinals rather than bit numbers.

    The named bits match the position labels shown for players on FM27 tactics screens in
    and out of possession. In member order they are GK, D (R), D (L), D (C), DM, M (R), M (L),
    M (C), AM (R), AM (L), AM (C), and ST (C). The enum excludes the column flags that distinguish
    paired slots. Bits 1, 5, and 6 still read UNKNOWN. FM26 stores the same field.
    """

    UNKNOWN = -1
    GOALKEEPER = 0  # GK
    DEFENDER_RIGHT = 2  # D (R)
    DEFENDER_LEFT = 3  # D (L)
    DEFENDER_CENTRE = 4  # D (C)
    DEFENSIVE_MIDFIELDER = 7  # DM
    MIDFIELDER_RIGHT = 8  # M (R)
    MIDFIELDER_LEFT = 9  # M (L)
    MIDFIELDER_CENTRE = 10  # M (C)
    ATTACKING_MIDFIELDER_RIGHT = 11  # AM (R)
    ATTACKING_MIDFIELDER_LEFT = 12  # AM (L)
    ATTACKING_MIDFIELDER_CENTRE = 13  # AM (C)
    STRIKER_CENTRE = 14  # ST (C)


@dataclass(frozen=True, slots=True)
class TacticSettingUnit:
    """One 24-byte setting unit of a tactic slot, as two bit fields.

    A slot holds between none and about twenty of these, and they are what the player
    instructions of that position most likely are, but the save stores no name for either
    field, so both ship as the numbers they are. Every field is unconfirmed. The byte between
    the two fields is the same on every unit of the signatures fmsave lists and is not shipped;
    on a record stored under another signature it can differ, and validation counts those units.

    Attributes:
        head_byte: The byte after the unit's lead bytes, which is 0 on most units and 2 or 10
            on the rest (unconfirmed).
        first_bits: The unit's seven-byte bit field as one little-endian int; between none and
            four of its bits are set (unconfirmed).
        second_bits_low: Bits 0 to 31 of the unit's twelve-byte bit field (unconfirmed).
        second_bits_middle: Bits 32 to 63 of that field (unconfirmed).
        second_bits_high: Bits 64 to 95 of that field. The field is wider than 64 bits, so it
            ships as three words rather than one int no column type could hold; one or two of
            its 96 bits are set, always above bit 32 (unconfirmed).
    """

    head_byte: int
    first_bits: int
    second_bits_low: int
    second_bits_middle: int
    second_bits_high: int


@dataclass(frozen=True, slots=True)
class TacticSlot:
    """One position of a tactic, in possession and out of possession.

    A tactic holds eleven of these in stored order. The mask is the field the positions come
    from: its low bits are positions and its two high bits flag which of a pair of central or
    wide slots is on which side, so the flags are in `*_mask` but never in `*_positions`.

    Attributes:
        number: The slot's place in the tactic, 0 for the first.
        in_possession_positions: The positions the in-possession mask sets, in ascending bit
            number; a bit no screen has shown reads UNKNOWN, and the raw value is always
            the bit number.
        in_possession_mask: The whole in-possession mask, column flags included.
        in_possession_setting_count: How many setting units the in-possession block holds
            (unconfirmed).
        in_possession_settings: Those units, in stored order (unconfirmed).
        out_of_possession_positions: The positions stored for this slot in the defending
            formation. Use `out_of_possession_position_index` to look up where the player in
            this slot defends.
        out_of_possession_mask: The whole out-of-possession mask.
        out_of_possession_setting_count: How many setting units that block holds
            (unconfirmed).
        out_of_possession_settings: Those units, in stored order (unconfirmed).
        unknown: The role and trail bits for each phase (unconfirmed). The role bits can be
            identical for different roles. The defending slot index also appears here for
            compatibility.
        in_possession_role: Role label for this slot's attacking position, or None when
            the position and stored code have no matching label (unconfirmed).
        out_of_possession_role: Role label for this slot's defending position, or None when
            the position and stored code have no matching label (unconfirmed). Use
            `out_of_possession_position_index` to find this player's defending slot.
    """

    number: int
    in_possession_positions: tuple[CodedValue[TacticPosition], ...]
    in_possession_mask: int
    in_possession_setting_count: int
    in_possession_settings: tuple[TacticSettingUnit, ...]
    out_of_possession_positions: tuple[CodedValue[TacticPosition], ...]
    out_of_possession_mask: int
    out_of_possession_setting_count: int
    out_of_possession_settings: tuple[TacticSettingUnit, ...]
    unknown: Mapping[str, int]
    in_possession_role: str | None = None
    out_of_possession_role: str | None = None

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = (
        "in_possession_role_bits",
        "in_possession_trail_bits",
        "out_of_possession_role_bits",
        "out_of_possession_trail_bits",
        "out_of_possession_position_index",
    )

    @property
    def out_of_possession_position_index(self) -> int | None:
        """The raw defending slot index, counting from 0, or None if the index is absent.

        Follow the index when the tactic has 11 slots and their indexes include every value
        from 0 through 10 exactly once.
        """
        return self.unknown.get("out_of_possession_position_index")


@dataclass(frozen=True, slots=True)
class Tactic:
    """One stored copy of one tactic, belonging to one team.

    Attributes:
        club_uid: Uid of the club the team plays for, None for a team no club lists
            (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        team_id: The team the copy belongs to, as the save stores it (unconfirmed).
        team_slot: The team's place in that club's own team list, 0 for its first team; None
            when the team resolves to no club (unconfirmed).
        index: The copy's place among the team's own tactics, counting from zero in stored
            order. Nothing stored says which of them is selected (unconfirmed).
        name: Stored tactic name (unconfirmed).
        style_name: The tactical style shown with the tactic, as stored text. No screen has
            confirmed that this label is the style (unconfirmed).
        mentality: The mentality the tactic is set to; the seven codes the game offers each
            carry the word it shows for them, and any other code reads UNKNOWN.
        slots: The eleven positions, in stored order.
        unknown: The 19 team-instruction bytes, one int per byte, and the tactic's four-byte
            style code as one little-endian int. Byte 2 of the instructions is the mentality
            and is shipped as `mentality` as well; bytes 0, 3, 4, 5, 7, 17 and 18 are the same
            on every record measured, and bytes 11 to 15 look bit-packed rather than numeric
            (unconfirmed).
    """

    club_uid: int | None
    club_name: str | None
    team_id: int
    team_slot: int | None
    index: int
    name: str
    style_name: str
    mentality: CodedValue[Mentality]
    slots: tuple[TacticSlot, ...]
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = tuple(
        f"team_instruction_{position:02d}" for position in range(19)
    ) + ("style_code",)


@dataclass(frozen=True, slots=True)
class SetPieceRoutine:
    """One set-piece routine slot of one team, named or unnamed.

    Attributes:
        club_uid: Uid of the club the team plays for, None for a team no club lists
            (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        team_id: The team the slot belongs to, as the save stores it (unconfirmed).
        team_slot: The team's place in that club's own team list, 0 for its first team; None
            when the team resolves to no club (unconfirmed).
        slot: The routine's place in the team's stored routines, counting from zero in stored
            order. Which set-piece situation a slot is for is not stored as text, so the slot
            number is all there is to go on (unconfirmed).
        name: Stored routine name, or None when unnamed. A team may store more than 20
            routines.
    """

    club_uid: int | None
    club_name: str | None
    team_id: int
    team_slot: int | None
    slot: int
    name: str | None


@dataclass(frozen=True, slots=True)
class Selection:
    """One player picked in one team's stored selection: a starter or a substitute.

    A team stores one selection of eleven starter places and fifteen substitute places. A row
    is one place that holds a pick; an empty place has no row, so a team with nothing picked
    has no rows at all. Only the manager's own teams store a selection in this form.

    In the team's selected tactic, a starter's `slot` matches `TacticSlot.number` for the
    in-possession position. In a complete tactic with valid indexes, follow that slot's
    `out_of_possession_position_index` to find the defending position. The selected tactic
    is unknown.

    **The substitutes are the stored list, not the next match's bench.** On one FM27 career
    the stored starters and the first thirteen substitutes matched the tactics screen in its
    order. The substitute places can keep players past the bench size of the next match, so
    compare their count with the competition's bench size before treating them all as picks.

    Attributes:
        club_uid: Uid of the club the team plays for, None for a team no club lists
            (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        team_id: The team the selection belongs to, as the save stores it (unconfirmed).
        team_slot: The team's place in that club's own team list, 0 for its first team; None
            when the team resolves to no club (unconfirmed).
        substitute: False for a starter, True for a substitute (unconfirmed).
        slot: The place within the starters or within the substitutes, counting from zero in
            stored order; a starter's is the tactic slot it fills, and a substitute's 0 is the
            first substitute the game lists (unconfirmed).
        player_uid: Uid of the picked player, None when the stored pick names no player record
            (unconfirmed).
        player_name: Denormalised name of player_uid (unconfirmed).
    """

    club_uid: int | None
    club_name: str | None
    team_id: int
    team_slot: int | None
    substitute: bool
    slot: int
    player_uid: int | None
    player_name: str | None


register_field_statuses(
    TacticSettingUnit,
    unconfirmed=(
        "head_byte",
        "first_bits",
        "second_bits_low",
        "second_bits_middle",
        "second_bits_high",
    ),
)
# The mask, the positions it sets and the slot's own number come from offsets a strict walk of
# every slot block on every save measured lands on exactly. What a setting unit is, and what
# the two bit fields beside the units mean, is not stored anywhere in the save.
register_field_statuses(
    TacticSlot,
    verified=(
        "number",
        "in_possession_positions",
        "in_possession_mask",
        "out_of_possession_positions",
        "out_of_possession_mask",
    ),
    unconfirmed=(
        "in_possession_setting_count",
        "in_possession_settings",
        "out_of_possession_setting_count",
        "out_of_possession_settings",
        "unknown",
        "in_possession_role",
        "out_of_possession_role",
    ),
)
# The mentality byte and the slots are read from a record the walk consumes exactly, and the
# mentality's own words come off a manager's tactics screen; position bits no screen has shown
# stay UNKNOWN, which is about the labels rather than the field. Everything else is either a join
# fmsave makes (the club and team fields), a number the save keeps with no name for it, or text
# no screen has confirmed the meaning of.
register_field_statuses(
    Tactic,
    verified=("mentality", "slots"),
    unconfirmed=(
        "club_uid",
        "club_name",
        "team_id",
        "team_slot",
        "index",
        "name",
        "style_name",
        "unknown",
    ),
)
register_field_statuses(
    SetPieceRoutine,
    verified=("name",),
    unconfirmed=("club_uid", "club_name", "team_id", "team_slot", "slot"),
)
# One FM27 tactics screen matched the picks; field statuses describe FM26, where no screen has
# been compared and the picks only fit the positions of the slots they fill.
register_field_statuses(
    Selection,
    unconfirmed=(
        "club_uid",
        "club_name",
        "team_id",
        "team_slot",
        "substitute",
        "slot",
        "player_uid",
        "player_name",
    ),
)
