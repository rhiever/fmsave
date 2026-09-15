"""Decoding one player's person block: names, birth date, nations, relations, traits and
personality.

A person block sits somewhere in the player record's window, found by searching for a
maximal in-range personality run's start (a `\\x00` byte immediately followed by
`personality_count` in-range bytes) and validating backwards from it.
`readers/players.py` calls `PersonBlockDecoder.decode` once per player record and merges
the result into `Player`. `decode` returns a plain positional tuple, not a dataclass, so a
successful decode allocates only the `Personality` it builds and the tuples it returns.
"""

from __future__ import annotations

import functools
import re
import struct
from dataclasses import dataclass
from datetime import date

from fmsave._errors import CorruptSaveError
from fmsave._layouts import PersonBlockLayout
from fmsave._scan import DAY_OF_YEAR_MASK, EARLIEST_GAME_YEAR, TIME_SLOT_SHIFT, decode_date
from fmsave.models.common import CodedValue
from fmsave.models.players import Personality, Trait
from fmsave.readers._common import MISSING_REFERENCE, section_label
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.names import NamePools, PoolIndex

# One player's decoded person block, in `Player`'s person-field order:
# (name, first_name, last_name, common_name, full_name, legal_name, birth_date, age,
#  nation_id, second_nation_ids, home_grown_nation_ids, home_grown_club_uids,
#  home_grown_club_names, personality, trait_bits, traits)
type PersonTuple = tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    date | None,
    int | None,
    int,
    tuple[int, ...],
    tuple[int, ...],
    tuple[int | None, ...],
    tuple[str | None, ...],
    Personality,
    int,
    tuple[CodedValue[Trait], ...],
]

_BIRTH_WORD_STRUCT = struct.Struct("<I")  # day-of-year/slot (low 16 bits), year (high 16 bits)
_UINT32_STRUCT = struct.Struct("<I")
_UINT16_STRUCT = struct.Struct("<H")
# q-8 (trait bits), then the first-name, surname and common-name ids, each followed by its
# required zero byte: q+0/q+4, q+5/q+9, q+10/q+14.
_NAME_BLOCK_STRUCT = struct.Struct("<QIBIBIB")
_SEVEN_ZERO_BYTES = bytes(7)
_RELATION_ENTRY_FORMAT = "I6xBBB3x"
_TRAIT_BIT_COUNT = 64
_NAME_CACHE_MISS = object()


def _personality_run_start_pattern(layout: PersonBlockLayout) -> re.Pattern[bytes]:
    """`\\x00` then personality_count in-range bytes.

    A consuming (non-overlapping) search over this pattern is complete: personality_range
    excludes 0, so none of the personality_count matched in-range bytes can itself start
    another match, and no valid personality run's own `\\x00` byte can be hidden inside a
    previous match.
    """
    lowest, highest = layout.personality_range
    byte_class = b"[" + bytes((lowest,)) + b"-" + bytes((highest,)) + b"]"
    return re.compile(b"\x00" + byte_class + b"{" + str(layout.personality_count).encode() + b"}")


def _trait_codes() -> tuple[CodedValue[Trait], ...]:
    return tuple(CodedValue.from_raw(Trait, bit) for bit in range(_TRAIT_BIT_COUNT))


@functools.cache
def _relation_entries_struct(entry_count: int) -> struct.Struct:
    """One struct unpacking every relation entry field, for exactly entry_count entries."""
    return struct.Struct("<" + _RELATION_ENTRY_FORMAT * entry_count)


@dataclass(slots=True)
class PersonBlockDecoder:
    """Decodes person blocks for one save; built once per `players()` call.

    Every field here is either precomputed once from the layout (the search pattern, the
    zero-byte-position offset, the packed `(kind, role)` pair keys) or a per-save cache keyed
    by a raw stored value shared across many players (birth date/age by the raw birth word,
    first and last names by pool id). `Personality` objects are never cached: they are cheap
    to build and each one is genuinely distinct per player.
    """

    layout: PersonBlockLayout
    name_pools: NamePools
    club_index: ClubIndex
    clock: date
    clock_year: int
    run_start_pattern: re.Pattern[bytes]
    trait_codes: tuple[CodedValue[Trait], ...]
    file_name: str
    zero_offset_from_birth: int
    second_nation_key: int
    home_grown_nation_key: int
    home_grown_club_key: int
    birth_cache: dict[int, tuple[date | None, int | None]]
    first_name_cache: dict[int, str | None]
    surname_cache: dict[int, str | None]

    def decode(self, game_db: bytes, window_start: int, window_end: int) -> PersonTuple | None:
        """The first validated person block in `[window_start, window_end)`, or None.

        Raises:
            CorruptSaveError: A validated block's relation header or entry list runs past
                window_end, or its legal name is not valid UTF-8.
        """
        search_start = window_start + self.zero_offset_from_birth
        for match in self.run_start_pattern.finditer(game_db, search_start, window_end):
            birth_date_offset = match.start() - self.zero_offset_from_birth
            person = self._try_candidate(game_db, birth_date_offset, window_end)
            if person is not None:
                return person
        return None

    def _try_candidate(
        self, game_db: bytes, birth_date_offset: int, window_end: int
    ) -> PersonTuple | None:
        layout = self.layout
        raw_birth_word: int = _BIRTH_WORD_STRUCT.unpack_from(game_db, birth_date_offset)[0]
        packed = raw_birth_word & 0xFFFF
        year = raw_birth_word >> 16
        if packed >> TIME_SLOT_SHIFT != 0:
            return None
        day_of_year = packed & DAY_OF_YEAR_MASK
        if not 1 <= day_of_year <= 366:
            return None
        if not EARLIEST_GAME_YEAR <= year <= self.clock_year:
            return None

        zero_region_offset = birth_date_offset + layout.date_zero_bytes_offset_from_birth
        if not game_db.startswith(_SEVEN_ZERO_BYTES, zero_region_offset):
            return None

        legal_name_length = self._find_legal_name_length(game_db, birth_date_offset)
        if legal_name_length is None:
            return None
        block_start_offset = (
            birth_date_offset - layout.legal_name_offset_from_block_start - legal_name_length
        )
        name_block_offset = block_start_offset + layout.trait_bits_offset_from_block_start
        if name_block_offset < 0:
            return None
        (
            trait_bits,
            first_name_id,
            first_name_zero,
            surname_id,
            surname_zero,
            common_name_id,
            common_name_zero,
        ) = _NAME_BLOCK_STRUCT.unpack_from(game_db, name_block_offset)
        if first_name_zero or surname_zero or common_name_zero:
            return None
        name_id_limit = layout.name_id_limit
        if (
            (first_name_id != MISSING_REFERENCE and first_name_id >= name_id_limit)
            or (surname_id != MISSING_REFERENCE and surname_id >= name_id_limit)
            or (common_name_id != MISSING_REFERENCE and common_name_id >= name_id_limit)
        ):
            return None

        birth_date, age = self._birth_date_and_age(raw_birth_word, game_db, birth_date_offset)

        personality_start = birth_date_offset + layout.personality_offset_from_birth
        personality = Personality(
            *game_db[personality_start : personality_start + layout.personality_count]
        )
        nation_id_offset = birth_date_offset + layout.nation_id_offset_from_birth
        nation_id: int = _UINT16_STRUCT.unpack_from(game_db, nation_id_offset)[0]

        second_nation_ids, home_grown_nation_ids, home_grown_club_uids, home_grown_club_names = (
            self._read_relations(game_db, birth_date_offset, window_end)
        )

        first_name = self._pooled_name(
            self.first_name_cache, self.name_pools.first_names, game_db, first_name_id
        )
        last_name = self._pooled_name(
            self.surname_cache, self.name_pools.surnames, game_db, surname_id
        )
        common_name = (
            None
            if common_name_id == MISSING_REFERENCE
            else self._resolve_common_name(game_db, common_name_id)
        )
        legal_name_start = block_start_offset + layout.legal_name_offset_from_block_start
        legal_name = self._decode_legal_name(game_db, legal_name_start, legal_name_length)

        full_name = None if first_name is None or last_name is None else f"{first_name} {last_name}"
        if common_name is not None:
            name = common_name
        else:
            joined_parts = [part for part in (first_name, last_name) if part is not None]
            name = " ".join(joined_parts) if joined_parts else legal_name

        traits = self._traits_from_bits(trait_bits)

        return (
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
        )

    def _birth_date_and_age(
        self, raw_birth_word: int, game_db: bytes, birth_date_offset: int
    ) -> tuple[date | None, int | None]:
        cached = self.birth_cache.get(raw_birth_word)
        if cached is not None:
            return cached
        birth_date = decode_date(game_db, birth_date_offset)
        if birth_date is None:
            age = None
        else:
            clock = self.clock
            age = (
                clock.year
                - birth_date.year
                - ((clock.month, clock.day) < (birth_date.month, birth_date.day))
            )
        result = (birth_date, age)
        self.birth_cache[raw_birth_word] = result
        return result

    def _traits_from_bits(self, trait_bits: int) -> tuple[CodedValue[Trait], ...]:
        if trait_bits == 0:
            return ()
        trait_codes = self.trait_codes
        traits: list[CodedValue[Trait]] = []
        remaining = trait_bits
        while remaining:
            lowest_set_bit = remaining & -remaining
            traits.append(trait_codes[lowest_set_bit.bit_length() - 1])
            remaining ^= lowest_set_bit
        return tuple(traits)

    def _pooled_name(
        self, cache: dict[int, str | None], pool: PoolIndex, game_db: bytes, name_id: int
    ) -> str | None:
        cached = cache.get(name_id, _NAME_CACHE_MISS)
        if cached is not _NAME_CACHE_MISS:
            return cached  # type: ignore[return-value]
        resolved = pool.name_at(game_db, name_id)
        cache[name_id] = resolved
        return resolved

    def _find_legal_name_length(self, game_db: bytes, birth_date_offset: int) -> int | None:
        layout = self.layout
        zero_length_word_at = birth_date_offset - 4
        if zero_length_word_at < 0:
            return None
        if _UINT32_STRUCT.unpack_from(game_db, zero_length_word_at)[0] == 0:
            return 0
        for candidate_length in range(
            layout.legal_name_length_min, layout.legal_name_length_max + 1
        ):
            length_word_at = birth_date_offset - 4 - candidate_length
            if length_word_at < 0:
                return None
            stored_length: int = _UINT32_STRUCT.unpack_from(game_db, length_word_at)[0]
            if stored_length == candidate_length:
                return candidate_length
        return None

    def _decode_legal_name(
        self, game_db: bytes, legal_name_start: int, legal_name_length: int
    ) -> str | None:
        if legal_name_length == 0:
            return None
        raw_bytes = game_db[legal_name_start : legal_name_start + legal_name_length]
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CorruptSaveError(
                f"{section_label(self.file_name)}: a legal name at offset {legal_name_start} "
                "is not valid UTF-8"
            ) from error

    def _resolve_common_name(self, game_db: bytes, common_name_id: int) -> str | None:
        name_pools = self.name_pools
        for pool in (name_pools.common_names, name_pools.first_names, name_pools.surnames):
            resolved = pool.name_at(game_db, common_name_id)
            if resolved is not None:
                return resolved
        return None

    def _read_relations(
        self, game_db: bytes, birth_date_offset: int, window_end: int
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int | None, ...], tuple[str | None, ...]]:
        layout = self.layout
        present_offset = birth_date_offset + layout.relation_present_offset_from_birth
        present_header_end = present_offset + 1
        if present_header_end > window_end:
            raise self._relation_overrun_error(present_header_end, window_end)
        if game_db[present_offset] == 0:
            return (), (), (), ()

        count_offset = birth_date_offset + layout.relation_count_offset_from_birth
        count_header_end = count_offset + 1
        if count_header_end > window_end:
            raise self._relation_overrun_error(count_header_end, window_end)
        relation_count: int = game_db[count_offset]
        if relation_count == 0:
            return (), (), (), ()
        entries_start = birth_date_offset + layout.relation_entries_offset_from_birth
        entries_end = entries_start + layout.relation_entry_bytes * relation_count
        if entries_end > window_end:
            raise self._relation_overrun_error(entries_end, window_end)

        flat_entries = _relation_entries_struct(relation_count).unpack_from(game_db, entries_start)
        second_nation_ids: list[int] = []
        home_grown_nation_ids: list[int] = []
        home_grown_club_uids: list[int | None] = []
        home_grown_club_names: list[str | None] = []
        seen_home_grown_club_referenced: list[int] = []
        second_nation_key = self.second_nation_key
        home_grown_nation_key = self.home_grown_nation_key
        home_grown_club_key = self.home_grown_club_key
        club_index = self.club_index

        for entry_index in range(relation_count):
            field_offset = entry_index * 4
            referenced, kind, role, _qualifier = flat_entries[field_offset : field_offset + 4]
            pair_key = (kind << 8) | role
            if pair_key == second_nation_key:
                if referenced not in second_nation_ids:
                    second_nation_ids.append(referenced)
            elif pair_key == home_grown_nation_key:
                if referenced not in home_grown_nation_ids:
                    home_grown_nation_ids.append(referenced)
            elif (
                pair_key == home_grown_club_key
                and referenced not in seen_home_grown_club_referenced
            ):
                seen_home_grown_club_referenced.append(referenced)
                club_uid = club_index.uid_by_club_index.get(referenced)
                club = None if club_uid is None else club_index.club_by_uid.get(club_uid)
                home_grown_club_uids.append(club_uid)
                home_grown_club_names.append(None if club is None else club.name)
        return (
            tuple(second_nation_ids),
            tuple(home_grown_nation_ids),
            tuple(home_grown_club_uids),
            tuple(home_grown_club_names),
        )

    def _relation_overrun_error(self, needed_end: int, window_end: int) -> CorruptSaveError:
        return CorruptSaveError(
            f"{section_label(self.file_name)}: a player's relation list needs bytes up to "
            f"offset {needed_end}, past the record window ending at {window_end}"
        )


def build_person_block_decoder(
    layout: PersonBlockLayout,
    name_pools: NamePools,
    club_index: ClubIndex,
    clock: date,
    file_name: str,
) -> PersonBlockDecoder:
    """Build the per-save person-block decoder from the save's layout, indexes and clock."""
    second_nation_key = (layout.second_nation_pair[0] << 8) | layout.second_nation_pair[1]
    home_grown_nation_key = (layout.home_grown_nation_pair[0] << 8) | layout.home_grown_nation_pair[
        1
    ]
    home_grown_club_key = (layout.home_grown_club_pair[0] << 8) | layout.home_grown_club_pair[1]
    return PersonBlockDecoder(
        layout=layout,
        name_pools=name_pools,
        club_index=club_index,
        clock=clock,
        clock_year=clock.year,
        run_start_pattern=_personality_run_start_pattern(layout),
        trait_codes=_trait_codes(),
        file_name=file_name,
        zero_offset_from_birth=layout.personality_offset_from_birth - 1,
        second_nation_key=second_nation_key,
        home_grown_nation_key=home_grown_nation_key,
        home_grown_club_key=home_grown_club_key,
        birth_cache={},
        first_name_cache={},
        surname_cache={},
    )
