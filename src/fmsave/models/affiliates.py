"""Affiliate groups: the sets of clubs the save stores together.

**What groups a set of clubs is not established.** The save stores these groups in a section of
their own, with nothing in them that says what the grouping means. Two readings fit what has
been measured: the affiliates a club's own Club Site lists, or the clubs of one owner. The
largest group of every save measured is recognisably a multi-club ownership group, and many
two-member groups pair a club with its own lower side, which suits either reading; against the
first, two clubs whose Club Site names an affiliate belong to no group at all. Until a club
screen settles it, every club field here is `unconfirmed`.

This is **not** the parent link `Club.parent_club_uid` carries. That link comes from the
affiliated-team lists inside the club records, and not one of its thousand-odd pairs is a pair
these groups hold: the two describe different relations and neither is derived from the other.
"""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class AffiliateGroup:
    """One stored group of clubs, with its members resolved to clubs where they resolve.

    Attributes:
        group_index: The group's own place in the section, counting from zero in stored
            order. It is fmsave's own index and not a value the save keeps: the groups carry
            no id of their own.
        club_uids: Uid of each member, in stored order, None for a member whose stored club
            index no club record claims, which is about one member in sixty (unconfirmed).
        club_names: Denormalised full name of each entry of `club_uids`, aligned with it and
            None wherever that uid is (unconfirmed).
    """

    group_index: int
    club_uids: tuple[int | None, ...]
    club_names: tuple[str | None, ...]


# The index is fmsave's own position in the section, which is structural. What the group means
# is not, so its members and their names stay unconfirmed until a club screen names one group.
register_field_statuses(
    AffiliateGroup,
    verified=("group_index",),
    unconfirmed=("club_uids", "club_names"),
)
