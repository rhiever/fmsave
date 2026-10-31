"""The corporate facilities rating a club's own record carries.

One row per club that keeps a monthly finance series, which is the clubs of the one or two
league nations a save tracks rather than every club it holds. The value is the rating the
game's Facilities screen shows as a word on its Corporate line, and the save keeps it as a
small number with no text beside it.

**Every code from 0 to 20 has a word.** Nineteen were read off a club's own Facilities
screen, one club per code, and the words rise with the number: several numbers share a word,
which is what a rating shown as a word rather than a number looks like. Two more are named
because they are bracketed, not because a pattern was extrapolated. A code outside that range
is `UNKNOWN` and keeps its raw number: a word nobody has seen displayed is silently wrong where
a raw number is plainly incomplete.

The screen's other facility lines -- the stadium, the pitch, the training and youth grounds,
the academy -- have no candidate byte anywhere near this one, so nothing here reads them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue


class CorporateFacilities(IntEnum):
    """How good a club's corporate facilities are, in the game's own words.

    A member's value is one code its word was displayed against; every code the word covers
    reads as that member and keeps its own raw number.

    **Nineteen codes are named by a screen.** One club's Facilities screen per code displayed
    that word against that exact stored number. FM26 screens named fifteen: 1 and 2 Basic, 5
    Fairly Basic, 6, 7 and 9 Adequate, 10, 11 and 12 Average, 13 and 15 Good, and 17, 18, 19
    and 20 Excellent. FM27 screens named four more: 0 None, 3 and 4 Fairly Basic, and 16
    Excellent. Those four fit the order the FM26 words rise in, but no FM26 screen has shown
    them, and no FM27 screen has yet shown the other fifteen.

    **Two more are named by bracketing, which is not band inference.** Code 8 sits between 7
    and 9, both displayed Adequate, and code 14 between 13 and 15, both displayed Good, so on
    a scale whose words rise with the number each of those can only be the word its
    neighbours carry. Nothing else is filled in that way.

    **NONE is 0.** The club whose screen showed None stores a zero in an otherwise empty block,
    which is how a club that has no corporate facilities at all reads.
    """

    UNKNOWN = -1
    NONE = 0
    BASIC = 1
    FAIRLY_BASIC = 5
    ADEQUATE = 6
    AVERAGE = 10
    GOOD = 13
    EXCELLENT = 17

    @classmethod
    def _missing_(cls, value: object) -> CorporateFacilities | None:
        """The further codes each word covers, and no other code."""
        return _FURTHER_CODES.get(value) if isinstance(value, int) else None


# Every code other than a word's own member value that the same word covers: those a screen
# displayed that word against, and the two the clubs either side of them bracket.
_FURTHER_CODES: Mapping[int, CorporateFacilities] = MappingProxyType(
    {
        2: CorporateFacilities.BASIC,
        3: CorporateFacilities.FAIRLY_BASIC,
        4: CorporateFacilities.FAIRLY_BASIC,
        7: CorporateFacilities.ADEQUATE,
        8: CorporateFacilities.ADEQUATE,
        9: CorporateFacilities.ADEQUATE,
        11: CorporateFacilities.AVERAGE,
        12: CorporateFacilities.AVERAGE,
        14: CorporateFacilities.GOOD,
        15: CorporateFacilities.GOOD,
        16: CorporateFacilities.EXCELLENT,
        18: CorporateFacilities.EXCELLENT,
        19: CorporateFacilities.EXCELLENT,
        20: CorporateFacilities.EXCELLENT,
    }
)


@dataclass(frozen=True, slots=True)
class ClubFacilities:
    """One club's facility ratings, as its own record stores them.

    Attributes:
        club_uid: Uid of the club (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        corporate_facilities: How good the club's corporate facilities are. Every code from 0
            to 20 carries a word, and a code outside that range is UNKNOWN with the raw number
            kept. A club that stores no rating reads NONE with raw 0, as its screen shows.
    """

    club_uid: int
    club_name: str
    corporate_facilities: CodedValue[CorporateFacilities]


# The rating is read from a fixed offset past the end of the club's own finance chain, and a
# club's screen named what the field is, so the field is verified even where a label is not.
# The club key and its name are the finance reader's, and carry that reader's status.
register_field_statuses(
    ClubFacilities,
    verified=("corporate_facilities",),
    unconfirmed=("club_uid", "club_name"),
)
