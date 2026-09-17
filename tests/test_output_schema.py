"""The flat output schema, recorded one column plan per table.

The output schema is stable and versioned, so every table's columns are recorded in a
snapshot here. Adding, removing, renaming or reordering a column changes the snapshot and
fails this test, which is the point: such a change has to be made deliberately, and a rename
or a removal also bumps `fmsave.OUTPUT_SCHEMA_VERSION` and goes in the CHANGELOG. The version
is recorded beside the columns, so the two can never drift apart unnoticed. Record an
intended change with `pytest tests/test_output_schema.py --snapshot-update`.
"""

from __future__ import annotations

from syrupy.assertion import SnapshotAssertion

import fmsave
from fmsave.export import column_names

TABLE_RECORD_TYPES = (
    fmsave.Player,
    fmsave.Contract,
    fmsave.Suspension,
    fmsave.Club,
    fmsave.ManagedClub,
    fmsave.Stage,
    fmsave.Competition,
    fmsave.Fixture,
    fmsave.LeagueTable,
    fmsave.TransferWindow,
    fmsave.CompetitionRules,
    fmsave.PlayerMatchStats,
    fmsave.Stadium,
    fmsave.FinanceMonth,
    fmsave.Sponsorship,
    fmsave.AffiliateGroup,
    fmsave.JobVacancy,
    fmsave.Staff,
    fmsave.StaffList,
    fmsave.InjuryType,
    fmsave.InjuryRecord,
    fmsave.TeamTraining,
    fmsave.MentoringGroup,
    fmsave.Tactic,
    fmsave.SetPieceRoutine,
)


def test_the_output_schema_matches_its_recorded_columns(snapshot: SnapshotAssertion) -> None:
    recorded_schema = {
        "output_schema_version": fmsave.OUTPUT_SCHEMA_VERSION,
        "tables": {
            record_type.__name__: list(column_names(record_type))
            for record_type in TABLE_RECORD_TYPES
        },
    }

    assert recorded_schema == snapshot
