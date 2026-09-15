"""Decoding one player's person block: names, birth date, nations, relations, traits and
personality.

A person block sits somewhere in the player record's window, found by searching for the
8-byte personality run and validating backwards from it. `readers/players.py` calls
`PersonBlockDecoder.decode` once per player record and merges the result into `Player`.
"""

from __future__ import annotations

import functools
import re
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from fmsave._errors import CorruptSaveError
from fmsave._layouts import PersonBlockLayout
from fmsave._scan import decode_date
from fmsave.models.common import CodedValue
from fmsave.models.players import Personality, Trait
from fmsave.readers._common import MISSING_REFERENCE, section_label
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.names import NamePools

_DATE4_STRUCT = struct.Struct("<HH")
_UINT32_STRUCT = struct.Struct("<I")
_UINT64_STRUCT = struct.Struct("<Q")
_UINT16_STRUCT = struct.Struct("<H")
_RELATION_STRUCT = struct.Struct("<I6xBBB3x")
_TRAIT_BIT_COUNT = 64
_TIME_SLOT_MASK = 0x1FF


@dataclass(frozen=True, slots=True)
class PersonFields:
    """One player's decoded person block; merged into `Player` once, never replaced piecewise.

    Attributes:
        name: Display name.
        first_name: First name.
        last_name: Last name.
        common_name: Common (nickname) name, when the save stores one.
        full_name: First name plus last name, or None when either is missing.
        legal_name: Legal name, when it differs from the display name.
        birth_date: Date of birth.
        age: Age at the save's in-game clock date.
        nation_id: Id of the player's primary nation.
        second_nation_ids: Ids of the player's other eligible nations.
        home_grown_nation_ids: Ids of nations the player is considered home grown for.
        home_grown_club_uids: Uids of clubs the player is considered home grown for, in
            relation-list order; an entry is None when its club index does not resolve, but
            still keeps its position.
        home_grown_club_names: Denormalised names for home_grown_club_uids, in the same
            order; None wherever home_grown_club_uids is None.
        personality: Personality profile.
        trait_bits: The raw trait bitmask.
        traits: Named player traits; an unnamed bit is Trait.UNKNOWN with raw set to the bit
            number.
    """

    name: str | None
    first_name: str | None
    last_name: str | None
    common_name: str | None
    full_name: str | None
    legal_name: str | None
    birth_date: date | None
    age: int | None
    nation_id: int
    second_nation_ids: tuple[int, ...]
    home_grown_nation_ids: tuple[int, ...]
    home_grown_club_uids: tuple[int | None, ...]
    home_grown_club_names: tuple[str | None, ...]
    personality: Personality
    trait_bits: int
    traits: tuple[CodedValue[Trait], ...]


def _personality_pattern(layout: PersonBlockLayout) -> re.Pattern[bytes]:
    """A zero-width lookahead over every start position, so overlapping runs are all found."""
    lowest, highest = layout.personality_range
    byte_class = b"[" + bytes((lowest,)) + b"-" + bytes((highest,)) + b"]"
    return re.compile(rb"(?=" + byte_class + b"{" + str(layout.personality_count).encode() + b"})")


def _trait_codes() -> tuple[CodedValue[Trait], ...]:
    return tuple(CodedValue.from_raw(Trait, bit) for bit in range(_TRAIT_BIT_COUNT))


@functools.cache
def _personality_flag_table(personality_range: tuple[int, int]) -> bytes:
    """256-byte translate table: 1 for a byte inside personality_range, 0 outside it."""
    lowest, highest = personality_range
    return bytes(1 if lowest <= value <= highest else 0 for value in range(256))


@functools.cache
def _personality_run_needle(personality_count: int) -> bytes:
    return b"\x01" * personality_count


def _flagged_runs(
    personality_flags: bytes, window_start: int, window_end: int, layout: PersonBlockLayout
) -> Iterator[tuple[int, int]]:
    """Yield (run_start, run_end) for each maximal run, inside the window, of at least
    personality_count consecutive bytes in personality_range.

    `personality_flags` is `game_db` translated through `_personality_flag_table` once per
    save (never per player, never a window slice); `bytes.find` (C-speed) then bounds the
    exact regex search to the rare stretches that could possibly hold a personality run, the
    same technique `readers/player_scan.py` uses for its completeness pattern.
    """
    run_needle = _personality_run_needle(layout.personality_count)
    find_in_flags = personality_flags.find
    position = window_start
    while True:
        run_start = find_in_flags(run_needle, position, window_end)
        if run_start < 0:
            break
        run_end = find_in_flags(b"\x00", run_start + layout.personality_count, window_end)
        if run_end < 0:
            run_end = window_end
        yield run_start, run_end
        position = run_end


@dataclass(slots=True)
class PersonBlockDecoder:
    """Decodes person blocks for one save; built once per `players()` call.

    `personality_flags` is a whole-`game_db`-length byte-flag buffer, built once from
    `game_db` so every player's window search is bounded by cheap `bytes.find` calls instead
    of a Python-level regex pass over the whole window.
    """

    layout: PersonBlockLayout
    name_pools: NamePools
    club_index: ClubIndex
    clock: date
    personality_pattern: re.Pattern[bytes]
    personality_flags: bytes
    trait_codes: tuple[CodedValue[Trait], ...]
    file_name: str

    def decode(self, game_db: bytes, window_start: int, window_end: int) -> PersonFields | None:
        """The first validated person block in `[window_start, window_end)`, or None.

        Raises:
            CorruptSaveError: A validated block's relation header or entry list runs past
                window_end, or its legal name is not valid UTF-8.
        """
        layout = self.layout
        for run_start, run_end in _flagged_runs(
            self.personality_flags, window_start, window_end, layout
        ):
            for match in self.personality_pattern.finditer(game_db, run_start, run_end):
                personality_run_offset = match.start()
                birth_date_offset = personality_run_offset - layout.personality_offset_from_birth
                if birth_date_offset < window_start:
                    continue
                person_fields = self._try_candidate(
                    game_db, birth_date_offset, window_start, window_end
                )
                if person_fields is not None:
                    return person_fields
        return None

    def _try_candidate(
        self, game_db: bytes, birth_date_offset: int, window_start: int, window_end: int
    ) -> PersonFields | None:
        layout = self.layout
        raw_checks_passed, birth_date = self._validate_birth_date(game_db, birth_date_offset)
        if not raw_checks_passed:
            return None
        zero_bytes_start = birth_date_offset + layout.date_zero_bytes_offset_from_birth
        zero_bytes = game_db[zero_bytes_start : zero_bytes_start + layout.date_zero_bytes_count]
        if zero_bytes != bytes(layout.date_zero_bytes_count):
            return None
        legal_name_length = self._find_legal_name_length(game_db, birth_date_offset)
        if legal_name_length is None:
            return None
        block_start_offset = (
            birth_date_offset - layout.legal_name_offset_from_block_start - legal_name_length
        )
        trait_bits_offset = block_start_offset + layout.trait_bits_offset_from_block_start
        if trait_bits_offset < 0:
            return None
        name_ids = self._read_name_ids(game_db, block_start_offset)
        if name_ids is None:
            return None
        first_name_id, surname_id, common_name_id = name_ids
        trait_bits: int = _UINT64_STRUCT.unpack_from(game_db, trait_bits_offset)[0]
        legal_name_start = block_start_offset + layout.legal_name_offset_from_block_start
        legal_name = self._decode_legal_name(game_db, legal_name_start, legal_name_length)
        nation_id_offset = birth_date_offset + layout.nation_id_offset_from_birth
        nation_id: int = _UINT16_STRUCT.unpack_from(game_db, nation_id_offset)[0]
        personality_start = birth_date_offset + layout.personality_offset_from_birth
        personality = Personality(
            *game_db[personality_start : personality_start + layout.personality_count]
        )
        (
            second_nation_ids,
            home_grown_nation_ids,
            home_grown_club_uids,
            home_grown_club_names,
        ) = self._read_relations(game_db, birth_date_offset, window_end)

        first_name = self.name_pools.first_names.name_at(game_db, first_name_id)
        last_name = self.name_pools.surnames.name_at(game_db, surname_id)
        common_name = self._resolve_common_name(game_db, common_name_id)
        full_name = None if first_name is None or last_name is None else f"{first_name} {last_name}"
        joined_parts = [part for part in (first_name, last_name) if part is not None]
        joined_name = " ".join(joined_parts) if joined_parts else None
        name = common_name if common_name is not None else joined_name
        if name is None:
            name = legal_name
        age = (
            None
            if birth_date is None
            else self.clock.year
            - birth_date.year
            - ((self.clock.month, self.clock.day) < (birth_date.month, birth_date.day))
        )
        traits = (
            ()
            if trait_bits == 0
            else tuple(
                self.trait_codes[bit] for bit in range(_TRAIT_BIT_COUNT) if trait_bits & (1 << bit)
            )
        )
        return PersonFields(
            name=name,
            first_name=first_name,
            last_name=last_name,
            common_name=common_name,
            full_name=full_name,
            legal_name=legal_name,
            birth_date=birth_date,
            age=age,
            nation_id=nation_id,
            second_nation_ids=second_nation_ids,
            home_grown_nation_ids=home_grown_nation_ids,
            home_grown_club_uids=home_grown_club_uids,
            home_grown_club_names=home_grown_club_names,
            personality=personality,
            trait_bits=trait_bits,
            traits=traits,
        )

    def _validate_birth_date(
        self, game_db: bytes, birth_date_offset: int
    ) -> tuple[bool, date | None]:
        """(raw_checks_passed, birth_date). A candidate whose raw checks pass but whose day
        does not exist in its (non-leap) year is still accepted, with birth_date None.
        """
        packed, year = _DATE4_STRUCT.unpack_from(game_db, birth_date_offset)
        time_slot = packed >> 9
        day_of_year = packed & _TIME_SLOT_MASK
        if time_slot != 0:
            return False, None
        if not 1 <= day_of_year <= 366:
            return False, None
        if not 1901 <= year <= self.clock.year:
            return False, None
        return True, decode_date(game_db, birth_date_offset)

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

    def _read_name_ids(
        self, game_db: bytes, block_start_offset: int
    ) -> tuple[int, int, int] | None:
        layout = self.layout
        zero_offsets = (
            block_start_offset + layout.first_name_id_offset_from_block_start + 4,
            block_start_offset + layout.surname_id_offset_from_block_start + 4,
            block_start_offset + layout.common_name_id_offset_from_block_start + 4,
        )
        for zero_offset in zero_offsets:
            if game_db[zero_offset] != 0:
                return None
        name_id_offsets = (
            block_start_offset + layout.first_name_id_offset_from_block_start,
            block_start_offset + layout.surname_id_offset_from_block_start,
            block_start_offset + layout.common_name_id_offset_from_block_start,
        )
        name_ids: list[int] = []
        for name_id_offset in name_id_offsets:
            name_id: int = _UINT32_STRUCT.unpack_from(game_db, name_id_offset)[0]
            if name_id != MISSING_REFERENCE and name_id >= layout.name_id_limit:
                return None
            name_ids.append(name_id)
        first_name_id, surname_id, common_name_id = name_ids
        return first_name_id, surname_id, common_name_id

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
        present = game_db[present_offset]
        empty_relations = (), (), (), ()
        if present == 0:
            return empty_relations

        count_offset = birth_date_offset + layout.relation_count_offset_from_birth
        count_header_end = count_offset + 1
        if count_header_end > window_end:
            raise self._relation_overrun_error(count_header_end, window_end)
        relation_count: int = game_db[count_offset]
        if relation_count == 0:
            return empty_relations
        entries_start = birth_date_offset + layout.relation_entries_offset_from_birth
        entries_end = entries_start + layout.relation_entry_bytes * relation_count
        if entries_end > window_end:
            raise self._relation_overrun_error(entries_end, window_end)

        second_nation_ids: list[int] = []
        home_grown_nation_ids: list[int] = []
        home_grown_club_uids: list[int | None] = []
        home_grown_club_names: list[str | None] = []
        seen_second_nation: set[int] = set()
        seen_home_grown_nation: set[int] = set()
        seen_home_grown_club: set[int] = set()

        for entry_index in range(relation_count):
            entry_offset = entries_start + layout.relation_entry_bytes * entry_index
            referenced, kind, role, _qualifier = _RELATION_STRUCT.unpack_from(game_db, entry_offset)
            pair = (kind, role)
            if pair == layout.second_nation_pair:
                if referenced not in seen_second_nation:
                    seen_second_nation.add(referenced)
                    second_nation_ids.append(referenced)
            elif pair == layout.home_grown_nation_pair:
                if referenced not in seen_home_grown_nation:
                    seen_home_grown_nation.add(referenced)
                    home_grown_nation_ids.append(referenced)
            elif pair == layout.home_grown_club_pair and referenced not in seen_home_grown_club:
                seen_home_grown_club.add(referenced)
                club_uid = self.club_index.uid_by_club_index.get(referenced)
                club = None if club_uid is None else self.club_index.club_by_uid.get(club_uid)
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
    game_db: bytes,
) -> PersonBlockDecoder:
    """Build the per-save person-block decoder from the save's layout, indexes and clock.

    `game_db` is translated once here into `personality_flags` (see `PersonBlockDecoder`);
    the decoder does not otherwise keep a reference to `game_db` itself.
    """
    personality_flags = game_db.translate(_personality_flag_table(layout.personality_range))
    return PersonBlockDecoder(
        layout=layout,
        name_pools=name_pools,
        club_index=club_index,
        clock=clock,
        personality_pattern=_personality_pattern(layout),
        personality_flags=personality_flags,
        trait_codes=_trait_codes(),
        file_name=file_name,
    )
