"""The corporate facilities rating a club's own record carries.

One row per club that keeps a monthly finance series, which is the clubs of the one or two
league nations a save tracks rather than every club it holds. The value is the rating the
game's Facilities screen shows as a word on its Corporate line, and the save keeps it as a
small number with no text beside it.

**Four of the twenty codes have a word.** Each of those was read off a club's own Facilities
screen: the words rise with the number and the same word can sit on two numbers. Every other
code is `UNKNOWN` and keeps its raw number, including the codes either side of a named one: a
scale whose ends nobody has seen cannot be filled in from the middle, and a wrong word is
silently wrong while a raw number is plainly incomplete.

The screen's other facility lines -- the stadium, the pitch, the training and youth grounds,
the academy -- have no candidate byte anywhere near this one, so nothing here reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from fmsave._status import register_field_statuses
from fmsave.models.common import CodedValue

# The second code the word "Excellent" was displayed for. Two clubs' screens read the same
# word at two different numbers, so the word cannot be keyed on the number alone.
_SECOND_EXCELLENT_CODE = 20


class CorporateFacilities(IntEnum):
    """How good a club's corporate facilities are, in the game's own words.

    A code is named only where a club's Facilities screen displayed that word against that
    exact stored number. Four did: 9 reads Adequate, 15 Good, and both 19 and 20 read
    Excellent, with the numbers and the words in the same order. Every other code of the 1 to
    20 the save uses is UNKNOWN and keeps its raw number.
    """

    UNKNOWN = -1
    ADEQUATE = 9
    GOOD = 15
    EXCELLENT = 19

    @classmethod
    def _missing_(cls, value: object) -> CorporateFacilities | None:
        """Label the second code the same word was displayed for, and no other code."""
        return cls.EXCELLENT if value == _SECOND_EXCELLENT_CODE else None


@dataclass(frozen=True, slots=True)
class ClubFacilities:
    """One club's facility ratings, as its own record stores them.

    Attributes:
        club_uid: Uid of the club (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        corporate_facilities: How good the club's corporate facilities are. Four codes carry
            the word a screen displayed for them and every other code is UNKNOWN with its raw
            number kept.
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
