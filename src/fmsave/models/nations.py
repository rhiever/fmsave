"""Nations and their game database ids.

Nation fields in other tables hold save-local ids. Join them to `Nation.nation_id`, then use
`Nation.database_id` with an external name map. The save stores no nation names.
"""

from __future__ import annotations

from dataclasses import dataclass

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class Nation:
    """One row of the save's nation table.

    Attributes:
        nation_id: Save-local nation id, counted from 0. Other tables' nation fields join
            to this value (unconfirmed).
        database_id: The nation's id in the game's installed database, used to join external
            name maps (unconfirmed).
    """

    nation_id: int
    database_id: int


register_field_statuses(Nation, unconfirmed=("nation_id", "database_id"))
