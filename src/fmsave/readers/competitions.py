"""Competitions, collected from the stage table.

The save has no competition table: a competition exists here because stages name it. One
`Competition` is built per distinct competition id the stage table carries, in ascending id.

Two fields are filled by later work and are None until then: the editor database id, which is
read from `game_db` elsewhere, and the name, which no save stores and which only a
user-supplied name map can give. `CompetitionIndex.name_for` is the single lookup every other
reader uses to denormalise a `competition_name`, so no reader repeats the rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fmsave._reader_stats import CompetitionStats
from fmsave.models.competitions import Competition
from fmsave.readers.stages import StageIndex


@dataclass(frozen=True, slots=True, repr=False)
class CompetitionIndex:
    """Every competition the stage table names, with the lookups other readers join through.

    One index is cached and shared by every reader of a save: never mutate its mappings.

    Attributes:
        competitions: Every competition, in ascending competition id.
        competition_by_id: The competition for each competition id.
        database_id_by_competition_id: The editor database id of each competition that has
            one, which is empty until the database ids are read.
        stats: What the index counted, for the competition checks.
    """

    competitions: tuple[Competition, ...]
    competition_by_id: Mapping[int, Competition]
    database_id_by_competition_id: Mapping[int, int]
    stats: CompetitionStats

    def name_for(self, competition_id: int | None) -> str | None:
        """The name of a competition, or None for an unknown id, no id, or an unnamed one."""
        if competition_id is None:
            return None
        competition = self.competition_by_id.get(competition_id)
        return None if competition is None else competition.name

    def __repr__(self) -> str:
        return (
            f"<fmsave CompetitionIndex {len(self.competitions)} competitions, "
            f"{len(self.database_id_by_competition_id)} with a database id>"
        )


def build_competition_index(
    stage_index: StageIndex,
    database_ids: Mapping[int, int],
    competition_names: Mapping[int, str],
) -> CompetitionIndex:
    """Collect one competition per distinct competition id in the stage table.

    Args:
        stage_index: The walked stage table.
        database_ids: The editor database id of each competition id, where one is known.
        competition_names: Names keyed by **database** id, as a user-supplied name map is,
            so a competition is named only once its database id resolves.
    """
    competitions: list[Competition] = []
    competition_by_id: dict[int, Competition] = {}
    database_id_by_competition_id: dict[int, int] = {}
    competitions_per_database_id: dict[int, int] = {}
    named_count = 0
    for competition_id in sorted(stage_index.stage_ids_by_competition_id):
        database_id = database_ids.get(competition_id)
        name = None if database_id is None else competition_names.get(database_id)
        if database_id is not None:
            database_id_by_competition_id[competition_id] = database_id
            competitions_per_database_id[database_id] = (
                competitions_per_database_id.get(database_id, 0) + 1
            )
        if name is not None:
            named_count += 1
        competition = Competition(
            id=competition_id,
            database_id=database_id,
            name=name,
            stage_ids=stage_index.stage_ids_by_competition_id[competition_id],
        )
        competitions.append(competition)
        competition_by_id[competition_id] = competition
    stats = CompetitionStats(
        competitions=len(competitions),
        with_database_id=len(database_id_by_competition_id),
        database_id_conflicts=sum(
            1 for claims in competitions_per_database_id.values() if claims > 1
        ),
        with_name=named_count,
    )
    return CompetitionIndex(
        competitions=tuple(competitions),
        competition_by_id=competition_by_id,
        database_id_by_competition_id=database_id_by_competition_id,
        stats=stats,
    )
