"""Decoding player records in `game_db` into `Player`.

`readers/player_scan.py` locates player records (the marker and completeness scans,
acceptance, and the private `PlayerRecords` index); this module turns one located record
into a public `Player`. A `PlayerDecoder`, built once per `players()` call from the save's
layout and its `ClubIndex`, holds everything a single record's decode needs, so decoding
never repeats a layout lookup, a team-to-club join, or a struct-layout computation.
"""

from __future__ import annotations

import functools
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from fmsave._layouts import ContractLayout, PersonBlockLayout, PlayerRecordLayout
from fmsave._scan import decode_date
from fmsave.models.common import TransferValueState
from fmsave.models.contracts import Contract
from fmsave.models.players import Ability, Attributes, Player, Positions, Reputation
from fmsave.readers._common import MISSING_REFERENCE
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.contracts import decode_contract
from fmsave.readers.names import NamePools
from fmsave.readers.persons import PersonBlockDecoder, build_person_block_decoder
from fmsave.readers.player_scan import HeaderLayout, build_header_layout, indexed_struct

_TeamFields = tuple[
    int, "str | None", "str | None", "int | None", "int | None", "int | None", "int | None", int
]

_DATE_CACHE_MISS = object()

_SCALE_TABLE = bytes(max(1, (raw_value + 2) // 5) for raw_value in range(256))

# The None/empty value for every person field, used when no person block validates.
_EMPTY_PERSON_TUPLE: tuple[
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    tuple[()],
    tuple[()],
    tuple[()],
    tuple[()],
    None,
    None,
    tuple[()],
] = (None, None, None, None, None, None, None, None, None, (), (), (), (), None, None, ())


def _new_date_cache() -> dict[int, date | None]:
    return {}


def _derived_positions(
    ratings: bytes, position_codes: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(natural_positions, accomplished_positions): best rating first, ties in array order."""
    qualifying = [(rating, index) for index, rating in enumerate(ratings) if rating >= 15]
    qualifying.sort(key=lambda item: -item[0])
    natural_positions = tuple(position_codes[index] for rating, index in qualifying if rating >= 18)
    accomplished_positions = tuple(
        position_codes[index] for rating, index in qualifying if rating < 18
    )
    return natural_positions, accomplished_positions


def _transfer_value(raw_value: int, placeholder: int) -> tuple[int | None, TransferValueState]:
    if raw_value == MISSING_REFERENCE:
        return None, TransferValueState.UNSET
    if raw_value == placeholder:
        return None, TransferValueState.PLACEHOLDER
    if raw_value == 0:
        return None, TransferValueState.ZERO
    return raw_value, TransferValueState.OK


@dataclass(frozen=True, slots=True)
class _TailLayout:
    """A struct spanning transfer_value_offset..height_offset+1, and each field's index."""

    struct_object: struct.Struct
    start_offset: int
    transfer_value_index: int
    club_join_date_index: int
    match_sharpness_index: int
    condition_index: int
    height_index: int


_TAIL_FIELD_SPECS: tuple[tuple[str, str], ...] = (
    ("transfer_value_offset", "I"),
    ("club_join_date_offset", "I"),
    ("match_sharpness_offset", "H"),
    ("condition_offset", "H"),
    ("height_offset", "B"),
)


@functools.cache
def _tail_layout(layout: PlayerRecordLayout) -> _TailLayout:
    tail_struct, start_offset, index_by_field = indexed_struct(layout, _TAIL_FIELD_SPECS)
    return _TailLayout(
        struct_object=tail_struct,
        start_offset=start_offset,
        transfer_value_index=index_by_field["transfer_value_offset"],
        club_join_date_index=index_by_field["club_join_date_offset"],
        match_sharpness_index=index_by_field["match_sharpness_offset"],
        condition_index=index_by_field["condition_offset"],
        height_index=index_by_field["height_offset"],
    )


@functools.cache
def _attribute_struct_without_feet(layout: PlayerRecordLayout) -> struct.Struct:
    """Unpacks the 54-byte attribute slice, skipping the two foot-strength bytes."""
    first_index, second_index = sorted((layout.left_foot_index, layout.right_foot_index))
    before_count = first_index
    between_count = second_index - first_index - 1
    after_count = layout.attribute_count - second_index - 1
    return struct.Struct(f"<{before_count}Bx{between_count}Bx{after_count}B")


@dataclass(slots=True)
class PlayerDecoder:
    """Decodes player records for one save; built once per `players()` call.

    Holds every layout- and club-derived value a record decode needs, so a single record
    never repeats a layout lookup, a team-to-club join, or a date decode already seen.
    """

    layout: PlayerRecordLayout
    person_decoder: PersonBlockDecoder
    person_window_start_offset: int
    header_layout: HeaderLayout
    tail_layout: _TailLayout
    attribute_struct: struct.Struct
    scale_table: bytes
    team_fields: Mapping[int, _TeamFields]
    contract_layout: ContractLayout
    club_index: ClubIndex
    clock: date
    date_cache: dict[int, date | None] = field(default_factory=_new_date_cache)

    def decode(
        self, game_db: bytes, record_offset: int, record_window_end: int, *, is_last_record: bool
    ) -> tuple[Player, Contract | None]:
        """Decode one player record's public fields, including its person block and contract.

        `record_window_end` bounds the person-block and contract-chain search: the next
        record's offset, or `len(game_db)` for the last record (see `player_scan.window_end`).
        `is_last_record` tells the contract chain search and fallback reader whether
        `record_window_end` is that last-record `len(game_db)` case.
        """
        layout = self.layout
        header_layout = self.header_layout
        header_values = header_layout.struct_object.unpack_from(
            game_db, record_offset + header_layout.start_offset
        )
        uid: int = header_values[header_layout.uid_index]
        pindex: int = header_values[header_layout.pindex_index]
        home_reputation: int = header_values[header_layout.home_reputation_index]
        current_reputation: int = header_values[header_layout.current_reputation_index]
        world_reputation: int = header_values[header_layout.world_reputation_index]
        current_ability: int = header_values[header_layout.current_ability_index]
        potential_ability_raw: int = header_values[header_layout.potential_ability_index]
        reputation_bucket: int = header_values[header_layout.reputation_bucket_index]
        stored_team_id: int = header_values[header_layout.team_id_index]

        reputation = Reputation(
            reputation_bucket, home_reputation, current_reputation, world_reputation
        )
        if potential_ability_raw < 0:
            ability = Ability(current_ability, None, potential_ability_raw)
        else:
            ability = Ability(current_ability, potential_ability_raw, None)

        team_id = None if stored_team_id == MISSING_REFERENCE else stored_team_id
        team_fields = self.team_fields.get(team_id) if team_id is not None else None
        if team_fields is None:
            club_uid = club_name = club_short_name = None
            club_nation_id = club_fa_nation_id = None
            club_reputation = club_last_league_position = None
            team_slot = None
        else:
            (
                club_uid,
                club_name,
                club_short_name,
                club_nation_id,
                club_fa_nation_id,
                club_reputation,
                club_last_league_position,
                team_slot,
            ) = team_fields

        ratings_start = record_offset + layout.ratings_offset
        ratings = game_db[ratings_start : ratings_start + layout.ratings_count]
        positions = Positions(*ratings)
        natural_positions, accomplished_positions = _derived_positions(
            ratings, layout.position_codes
        )

        attributes_start = record_offset + layout.attributes_offset
        raw_attribute_bytes = game_db[attributes_start : attributes_start + layout.attribute_count]
        scaled_attribute_bytes = raw_attribute_bytes.translate(self.scale_table)
        raw_attributes = Attributes(*self.attribute_struct.unpack(raw_attribute_bytes))
        attributes = Attributes(*self.attribute_struct.unpack(scaled_attribute_bytes))
        raw_left_foot = raw_attribute_bytes[layout.left_foot_index]
        raw_right_foot = raw_attribute_bytes[layout.right_foot_index]
        left_foot = scaled_attribute_bytes[layout.left_foot_index]
        right_foot = scaled_attribute_bytes[layout.right_foot_index]

        tail_layout = self.tail_layout
        tail_values = tail_layout.struct_object.unpack_from(
            game_db, record_offset + tail_layout.start_offset
        )
        transfer_value_raw: int = tail_values[tail_layout.transfer_value_index]
        club_join_date_raw: int = tail_values[tail_layout.club_join_date_index]
        match_sharpness: int = tail_values[tail_layout.match_sharpness_index]
        condition: int = tail_values[tail_layout.condition_index]
        height_cm: int = tail_values[tail_layout.height_index]

        transfer_value, transfer_value_state = _transfer_value(
            transfer_value_raw, layout.transfer_value_placeholder
        )
        club_join_date = self._cached_date(
            game_db, record_offset + layout.club_join_date_offset, club_join_date_raw
        )

        person_window_start = record_offset + self.person_window_start_offset
        person = self.person_decoder.decode(game_db, person_window_start, record_window_end)
        (
            name,
            first_name,
            last_name,
            common_name,
            full_name,
            legal_name,
            birth_date,
            age,
            nation_id,
            second_nation_ids,
            home_grown_nation_ids,
            home_grown_club_uids,
            home_grown_club_names,
            personality,
            trait_bits,
            traits,
        ) = _EMPTY_PERSON_TUPLE if person is None else person

        contract, on_loan, loan_parent_club_uid, loan_parent_club_name = decode_contract(
            game_db,
            record_offset,
            record_window_end,
            is_last_record,
            pindex,
            uid,
            name,
            team_id,
            self.club_index,
            self.clock,
            self.contract_layout,
        )

        # Positional, matching Player's field order in models/players.py.
        player = Player(
            uid,
            name,
            first_name,
            last_name,
            common_name,
            full_name,
            legal_name,
            birth_date,
            age,
            nation_id,
            second_nation_ids,
            home_grown_nation_ids,
            home_grown_club_uids,
            home_grown_club_names,
            height_cm,
            ability,
            reputation,
            club_uid,
            club_name,
            club_short_name,
            club_nation_id,
            club_fa_nation_id,
            club_reputation,
            club_last_league_position,
            team_id,
            team_slot,
            club_join_date,
            natural_positions,
            accomplished_positions,
            personality,
            attributes,
            raw_attributes,
            left_foot,
            right_foot,
            raw_left_foot,
            raw_right_foot,
            positions,
            transfer_value,
            transfer_value_state,
            condition,
            match_sharpness,
            traits,
            trait_bits,
            on_loan,
            loan_parent_club_uid,
            loan_parent_club_name,
            contract,
        )
        return player, contract

    def _cached_date(self, game_db: bytes, date_offset: int, raw_date: int) -> date | None:
        """The date at date_offset, decoded by fmsave._scan.decode_date on a cache miss."""
        cache = self.date_cache
        cached = cache.get(raw_date, _DATE_CACHE_MISS)
        if cached is not _DATE_CACHE_MISS:
            return cached  # type: ignore[return-value]
        decoded = decode_date(game_db, date_offset)
        cache[raw_date] = decoded
        return decoded


def build_player_decoder(
    layout: PlayerRecordLayout,
    club_index: ClubIndex,
    name_pools: NamePools,
    clock: date,
    person_layout: PersonBlockLayout,
    contract_layout: ContractLayout,
    file_name: str,
) -> PlayerDecoder:
    """Build the per-save decoder from the save's layout, its ClubIndex, name pools and clock."""
    team_fields: dict[int, _TeamFields] = {}
    for team_id, (club_uid, team_slot) in club_index.team_to_club.items():
        club = club_index.club_by_uid[club_uid]
        team_fields[team_id] = (
            club_uid,
            club.name,
            club.short_name,
            club.nation_id,
            club.fa_nation_id,
            club.reputation,
            club.last_league_position,
            team_slot,
        )
    person_decoder = build_person_block_decoder(
        person_layout, name_pools, club_index, clock, file_name
    )
    return PlayerDecoder(
        layout=layout,
        person_decoder=person_decoder,
        person_window_start_offset=person_layout.window_start_offset,
        header_layout=build_header_layout(layout),
        tail_layout=_tail_layout(layout),
        attribute_struct=_attribute_struct_without_feet(layout),
        scale_table=_SCALE_TABLE,
        team_fields=team_fields,
        contract_layout=contract_layout,
        club_index=club_index,
        clock=clock,
    )
