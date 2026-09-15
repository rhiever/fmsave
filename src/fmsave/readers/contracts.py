"""Decoding a player's contract chain in `game_db` into `Contract`.

A player's contract is assembled from a chain of registration records (the tag
`01 00 6c 07` plus a matching selector), searched for in the player's own record window.
`ContractDecoder`, built once per `players()`/`contracts()` call from the save's layout and
its `ClubIndex`, holds everything a single record's decode needs, the way
`readers/persons.py`'s `PersonBlockDecoder` does: every offset, Struct and needle is bound as
a field at build time, so decoding never repeats a layout lookup or a team-to-club join.
`ContractDecoder.decode_chain_record` decodes a single located chain record (its tail, its
clauses, and its head) from its tag offset alone, with no player window; `ContractDecoder.decode`
finds every chain record for one player and assembles the public `Contract` by the assembly
rules documented on `ContractLayout` and on the `Contract` and `ContractChainEntry` models.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import date

from fmsave._errors import CorruptSaveError
from fmsave._frozen import FrozenMapping
from fmsave._layouts import ContractLayout
from fmsave._scan import decode_date
from fmsave.models.common import CodedValue, ContractEndSource
from fmsave.models.contracts import (
    Clause,
    ClauseKind,
    Contract,
    ContractChainEntry,
    ContractType,
    SquadStatus,
)
from fmsave.readers._common import section_label
from fmsave.readers.clubs import ClubIndex

_U32 = struct.Struct("<I")
_FOUR_FF = b"\xff\xff\xff\xff"
_ZERO8 = bytes(8)
_MISSING_U32 = 0xFFFFFFFF
_MISSING_U16 = 0xFFFF
_DATE_CACHE_MISS = object()

# The tail locator's signature: byte E+3 (always 3) followed by the u32 at E+4 (always 4,
# stored little-endian), five bytes that a `rfind` can search for directly.
_TAIL_SIGNATURE = b"\x03\x04\x00\x00\x00"
_TAIL_SIGNATURE_LENGTH = len(_TAIL_SIGNATURE)

# One decoded chain record, before club resolution, in this fixed field order:
# (team_id, wage, start, end, has_tail, squad_status_raw, event_count, clauses,
#  contract_type_raw, unknown). end, squad_status_raw, event_count and contract_type_raw are
# None, clauses is (), and unknown is None, when has_tail is False (contract_type_raw stays
# None either way when the head was not found).
type _ChainRecordTuple = tuple[
    int,
    int,
    "date | None",
    "date | None",
    bool,
    "int | None",
    "int | None",
    "tuple[Clause, ...]",
    "int | None",
    "dict[str, int] | None",
]


def _build_tail_struct(layout: ContractLayout) -> struct.Struct:
    """One struct spanning the whole 46-byte tail block, from `E` to `E+46`.

    Reads e2, e8, e12, e16, e20, e24, the end date's raw u32 (for the date cache), squad
    status, e37, e38, e39 and event_count; skips the sentinel bytes the locator already
    checked and the excluded printed-start date at E+32.
    """
    assert layout.tail_e2_offset == 2
    assert layout.tail_e8_offset == 8
    assert layout.tail_e12_offset == 12
    assert layout.tail_e16_offset == 16
    assert layout.tail_e20_offset == 20
    assert layout.tail_e24_offset == 24
    assert layout.tail_end_offset == 28
    assert layout.tail_squad_status_offset == 36
    assert layout.tail_e37_offset == 37
    assert layout.tail_e38_offset == 38
    assert layout.tail_e39_offset == 39
    assert layout.tail_event_count_offset == 42
    return struct.Struct("<2xH4xIIIIII4xBBBB2xI")


def _build_head_struct(layout: ContractLayout) -> struct.Struct:
    """One struct spanning the head gate through money_c, from `base + head_gate_offset`."""
    assert layout.head_type_offset - layout.head_gate_offset == 2
    assert layout.head_money_a_offset - layout.head_gate_offset == 3
    assert layout.head_money_b_offset - layout.head_money_a_offset == 4
    assert layout.head_money_c_offset - layout.head_money_b_offset == 4
    return struct.Struct("<HBIII")


def _build_team_wage_struct(layout: ContractLayout) -> struct.Struct:
    """One struct reading team_id and wage together, from `chain_tag_offset + team_id_offset`."""
    assert layout.wage_offset - layout.team_id_offset == 8
    return struct.Struct("<I4xI")


def _build_clause_prefixes(layout: ContractLayout) -> tuple[bytes, ...]:
    """`FF` x 8, `00` x 3, then the count byte, for each possible count, indexed by count."""
    assert layout.clause_zero_offset - layout.clause_ff_offset == 8
    assert layout.clause_count_offset - layout.clause_zero_offset == 3
    return tuple(
        b"\xff" * 8 + b"\x00" * 3 + bytes([count]) for count in range(layout.clause_max_count + 1)
    )


def _build_clause_structs(layout: ContractLayout) -> tuple[struct.Struct, ...]:
    """One struct per possible clause count, each unpacking that many (value, parameter,
    kind) triples starting at `base + clause_entries_offset`.
    """
    return tuple(struct.Struct("<" + "IHH" * count) for count in range(layout.clause_max_count + 1))


def _new_date_cache() -> dict[int, date | None]:
    return {}


def _new_clause_kind_cache() -> dict[int, CodedValue[ClauseKind]]:
    return {}


def _new_squad_status_cache() -> dict[int, CodedValue[SquadStatus]]:
    return {}


def _new_contract_type_cache() -> dict[int, CodedValue[ContractType]]:
    return {}


@dataclass(slots=True)
class ContractDecoder:
    """Decodes contract chains for one save; built once per `players()`/`contracts()` call.

    Every offset the hot path (`decode`, `decode_chain_record` and the methods they call)
    uses is bound here as a plain field, computed once from the layout at build time: no
    method below loads a `layout` attribute inside a per-record or per-candidate loop. The
    per-save caches (dates by their raw stored u32, and `CodedValue` labels by raw code) are
    keyed by values shared across many players; `CodedValue` objects are never cached
    process-globally, since a cache tied to this decoder is dropped with the save.
    """

    layout: ContractLayout
    club_by_team_id: dict[int, tuple[int | None, str | None]]
    clock: date
    file_name: str

    tail_struct: struct.Struct
    head_struct: struct.Struct
    team_wage_struct: struct.Struct
    clause_prefixes: tuple[bytes, ...]
    clause_structs: tuple[struct.Struct, ...]
    empty_unknown: FrozenMapping[str, int]

    date_cache: dict[int, date | None] = field(default_factory=_new_date_cache)
    clause_kind_cache: dict[int, CodedValue[ClauseKind]] = field(
        default_factory=_new_clause_kind_cache
    )
    squad_status_cache: dict[int, CodedValue[SquadStatus]] = field(
        default_factory=_new_squad_status_cache
    )
    contract_type_cache: dict[int, CodedValue[ContractType]] = field(
        default_factory=_new_contract_type_cache
    )

    def _cached_date(self, game_db: bytes, raw_value: int, date_offset: int) -> date | None:
        cache = self.date_cache
        cached = cache.get(raw_value, _DATE_CACHE_MISS)
        if cached is not _DATE_CACHE_MISS:
            return cached  # type: ignore[return-value]
        decoded = decode_date(game_db, date_offset)
        cache[raw_value] = decoded
        return decoded

    def _cached_clause_kind(self, raw_kind: int) -> CodedValue[ClauseKind]:
        cache = self.clause_kind_cache
        kind = cache.get(raw_kind)
        if kind is None:
            kind = cache[raw_kind] = CodedValue.from_raw(ClauseKind, raw_kind)
        return kind

    def _cached_squad_status(self, raw_status: int) -> CodedValue[SquadStatus]:
        cache = self.squad_status_cache
        status = cache.get(raw_status)
        if status is None:
            status = cache[raw_status] = CodedValue.from_raw(SquadStatus, raw_status)
        return status

    def _cached_contract_type(self, raw_type: int) -> CodedValue[ContractType]:
        cache = self.contract_type_cache
        contract_type = cache.get(raw_type)
        if contract_type is None:
            contract_type = cache[raw_type] = CodedValue.from_raw(ContractType, raw_type)
        return contract_type

    def _locate_tail(self, game_db: bytes, chain_tag_offset: int) -> int | None:
        """The tail start offset E, or None when no candidate's checks all pass.

        Tries `event_count = 0` (`E = chain_tag_offset - tail_base_offset`) directly first.
        Failing that, it searches right to left for the five-byte tail signature with
        `rfind`, so candidates come back in ascending `event_count` order; a hit is a real
        tail only when its distance from the `event_count = 0` position is a multiple of
        `tail_step_bytes` and its own stored event count matches that multiple.
        """
        layout = self.layout
        first_candidate = chain_tag_offset - layout.tail_base_offset
        if first_candidate < 0:
            return None
        game_db_length = len(game_db)
        if (
            first_candidate + 46 <= game_db_length
            and game_db[first_candidate] == 0
            and game_db[first_candidate + 1] == 0
            and game_db.startswith(_TAIL_SIGNATURE, first_candidate + 3)
            and _U32.unpack_from(game_db, first_candidate + layout.tail_event_count_offset)[0] == 0
        ):
            return first_candidate

        step_bytes = layout.tail_step_bytes
        lowest_candidate = first_candidate - step_bytes * layout.tail_max_event_count
        lowest_candidate = max(lowest_candidate, 0)
        # Bounds the search to distances of at least one step, since event_count = 0 was
        # already tried above: the signature for event_count = 1 sits at
        # first_candidate - step_bytes + 3, and rfind's end is exclusive.
        search_end = first_candidate - step_bytes + 3 + _TAIL_SIGNATURE_LENGTH
        signature_start = lowest_candidate + 3
        rfind = game_db.rfind
        signature_hit = rfind(_TAIL_SIGNATURE, signature_start, search_end)
        while signature_hit >= 0:
            candidate = signature_hit - 3
            distance = first_candidate - candidate
            if (
                distance % step_bytes == 0
                and candidate + 46 <= game_db_length
                and game_db[candidate] == 0
                and game_db[candidate + 1] == 0
            ):
                event_count = distance // step_bytes
                stored_event_count: int = _U32.unpack_from(
                    game_db, candidate + layout.tail_event_count_offset
                )[0]
                if stored_event_count == event_count:
                    return candidate
            signature_hit = rfind(_TAIL_SIGNATURE, signature_start, signature_hit + 4)
        return None

    def _locate_clause_base(self, game_db: bytes, tail_offset: int) -> tuple[int, int] | None:
        """(base, count), or None when no candidate count's checks all pass.

        Checks the cheap count byte first, then confirms with one `startswith` against a
        precomputed `FF*8 + 00*3 + count` needle, so a false count byte never allocates a
        slice to compare.
        """
        layout = self.layout
        game_db_length = len(game_db)
        step_bytes = layout.clause_step_bytes
        ff_offset = layout.clause_ff_offset
        count_offset = layout.clause_count_offset
        clause_prefixes = self.clause_prefixes
        startswith = game_db.startswith
        for count in range(layout.clause_max_count + 1):
            base = tail_offset - step_bytes * count
            ff_start = base + ff_offset
            if ff_start < 0:
                return None
            count_at = base + count_offset
            if (
                count_at < game_db_length
                and game_db[count_at] == count
                and startswith(clause_prefixes[count], ff_start)
            ):
                return base, count
        return None

    def _read_clauses(self, game_db: bytes, base: int, count: int) -> tuple[Clause, ...]:
        if count == 0:
            return ()
        entries_start = base + self.layout.clause_entries_offset
        values = self.clause_structs[count].unpack_from(game_db, entries_start)
        clauses: list[Clause] = []
        for entry_start in range(0, count * 3, 3):
            raw_value = values[entry_start]
            raw_parameter = values[entry_start + 1]
            raw_kind = values[entry_start + 2]
            clauses.append(
                Clause(
                    kind=self._cached_clause_kind(raw_kind),
                    parameter=None if raw_parameter == _MISSING_U16 else raw_parameter,
                    value=None if raw_value == _MISSING_U32 else raw_value,
                )
            )
        return tuple(clauses)

    def _read_head(self, game_db: bytes, base: int) -> tuple[int, int, int, int] | None:
        layout = self.layout
        head_offset = base + layout.head_gate_offset
        if head_offset < 0 or head_offset + self.head_struct.size > len(game_db):
            return None
        gate_value, contract_type_raw, money_a, money_b, money_c = self.head_struct.unpack_from(
            game_db, head_offset
        )
        if gate_value != layout.head_gate_value:
            return None
        return contract_type_raw, money_a, money_b, money_c

    def decode_chain_record(self, game_db: bytes, chain_tag_offset: int) -> _ChainRecordTuple:
        """Decode one chain record's team, wage, dates, tail and clauses from its tag offset
        alone: callable without a player window.

        Raises:
            CorruptSaveError: The record's team id or wage runs past the end of game_db.
        """
        layout = self.layout
        team_wage_struct = self.team_wage_struct
        team_wage_offset = chain_tag_offset + layout.team_id_offset
        fixed_fields_end = team_wage_offset + team_wage_struct.size
        if fixed_fields_end > len(game_db):
            raise CorruptSaveError(
                f"{section_label(self.file_name)}: a contract chain record at offset "
                f"{chain_tag_offset} needs bytes up to offset {fixed_fields_end}, past the "
                "end of the section"
            )
        team_id, wage = team_wage_struct.unpack_from(game_db, team_wage_offset)

        start_offset = chain_tag_offset + layout.start_offset
        start: date | None = None
        if start_offset >= 0:
            raw_start: int = _U32.unpack_from(game_db, start_offset)[0]
            start = self._cached_date(game_db, raw_start, start_offset)

        tail_offset = self._locate_tail(game_db, chain_tag_offset)
        if tail_offset is None:
            return (team_id, wage, start, None, False, None, None, (), None, None)

        (
            e2,
            e8,
            e12,
            e16,
            e20,
            e24,
            raw_end,
            squad_status_raw,
            e37,
            e38,
            e39,
            event_count,
        ) = self.tail_struct.unpack_from(game_db, tail_offset)
        end = self._cached_date(game_db, raw_end, tail_offset + layout.tail_end_offset)
        unknown: dict[str, int] = {
            "e2": e2,
            "e8": e8,
            "e12": e12,
            "e16": e16,
            "e20": e20,
            "e24": e24,
            "e37": e37,
            "e38": e38,
            "e39": e39,
        }

        clause_base = self._locate_clause_base(game_db, tail_offset)
        if clause_base is None:
            return (
                team_id,
                wage,
                start,
                end,
                True,
                squad_status_raw,
                event_count,
                (),
                None,
                unknown,
            )
        base, count = clause_base
        clauses = self._read_clauses(game_db, base, count)
        head = self._read_head(game_db, base)
        contract_type_raw: int | None = None
        if head is not None:
            contract_type_raw, money_a, money_b, money_c = head
            unknown["money_a"] = money_a
            unknown["money_b"] = money_b
            unknown["money_c"] = money_c
        return (
            team_id,
            wage,
            start,
            end,
            True,
            squad_status_raw,
            event_count,
            clauses,
            contract_type_raw,
            unknown,
        )

    def _find_chain_records(
        self,
        game_db: bytes,
        record_offset: int,
        record_window_end: int,
        is_last_record: bool,
        pindex: int,
    ) -> list[_ChainRecordTuple] | None:
        """Every chain record whose selector matches pindex, in file order, or None when
        there is none. Searches the tag inline (no intermediate hit list) and advances past
        each hit by 4 bytes, since the tag cannot overlap itself.
        """
        layout = self.layout
        search_start = record_offset + layout.chain_window_start_offset
        search_start = max(search_start, 0)
        search_end = (
            record_window_end
            if is_last_record
            else record_window_end + layout.chain_window_end_offset
        )
        search_end = max(search_end, search_start)
        selector_bytes = _U32.pack(pindex + 1)
        selector_offset = layout.selector_offset
        game_db_length = len(game_db)
        find = game_db.find
        startswith = game_db.startswith
        tag = layout.tag
        records: list[_ChainRecordTuple] | None = None
        hit = find(tag, search_start, search_end)
        while hit >= 0:
            selector_at = hit + selector_offset
            if selector_at + 4 <= game_db_length and startswith(selector_bytes, selector_at):
                decoded_record = self.decode_chain_record(game_db, hit)
                if records is None:
                    records = [decoded_record]
                else:
                    records.append(decoded_record)
            hit = find(tag, hit + 4, search_end)
        return records

    def _find_fallback_dates(
        self, game_db: bytes, record_offset: int, record_window_end: int
    ) -> tuple[date | None, date | None]:
        """(start, end) with the latest end among valid pairs, or (None, None).

        `record_window_end` is already `len(game_db)` for the last player (see
        `player_scan.window_end`), so no separate last-record case is needed here.
        """
        layout = self.layout
        search_start = record_offset + layout.fallback_start_from_record
        limit = record_window_end - layout.fallback_end_margin
        limit = max(limit, search_start)
        game_db_length = len(game_db)
        find_end = min(game_db_length, limit)
        gate_length = layout.fallback_gate_length
        nonzero_offset = layout.fallback_nonzero_offset
        nonzero_length = layout.fallback_nonzero_length
        end_date_offset = layout.fallback_end_date_offset
        start_date_offset = layout.fallback_start_date_offset
        find = game_db.find
        startswith = game_db.startswith
        best_start: date | None = None
        best_end: date | None = None
        hit = find(_FOUR_FF, search_start, find_end)
        while hit >= 0:
            dates_offset = hit + 8  # "j" in ContractLayout's docstring
            nonzero_start = dates_offset + nonzero_offset
            if (
                dates_offset + gate_length <= limit
                and nonzero_start + nonzero_length <= game_db_length
                and not startswith(_ZERO8, nonzero_start)
            ):
                raw_end: int = _U32.unpack_from(game_db, dates_offset + end_date_offset)[0]
                end_date = self._cached_date(game_db, raw_end, dates_offset + end_date_offset)
                if end_date is not None and (best_end is None or end_date > best_end):
                    raw_start: int = _U32.unpack_from(game_db, dates_offset + start_date_offset)[0]
                    start_date = self._cached_date(
                        game_db, raw_start, dates_offset + start_date_offset
                    )
                    if start_date is not None and end_date > start_date:
                        best_end = end_date
                        best_start = start_date
            hit = find(_FOUR_FF, hit + 1, find_end)
        return best_start, best_end

    def decode(
        self,
        game_db: bytes,
        record_offset: int,
        record_window_end: int,
        is_last_record: bool,
        pindex: int,
        player_uid: int,
        player_name: str | None,
        player_team_id: int | None,
    ) -> tuple[Contract | None, bool | None, int | None, str | None]:
        """Assemble one player's contract from their chain records and, when needed, the
        fallback reader.

        Returns (contract, on_loan, loan_parent_club_uid, loan_parent_club_name); the last
        three are also carried inside contract when it is not None.

        Raises:
            CorruptSaveError: A chain record's team id or wage runs past the end of game_db.
        """
        chain_records = self._find_chain_records(
            game_db, record_offset, record_window_end, is_last_record, pindex
        )

        any_tail_parsed = False
        if chain_records is not None:
            for candidate_record in chain_records:
                if candidate_record[4]:
                    any_tail_parsed = True
                    break

        fallback_start: date | None = None
        fallback_end: date | None = None
        if chain_records is None or not any_tail_parsed:
            fallback_start, fallback_end = self._find_fallback_dates(
                game_db, record_offset, record_window_end
            )

        if chain_records is None and fallback_start is None and fallback_end is None:
            return None, None, None, None

        club_by_team_id = self.club_by_team_id
        clock = self.clock

        if chain_records is None:
            wage: int | None = None
            start = fallback_start
            live_club_uid: int | None = None
            live_club_name: str | None = None
            live_team_id: int | None = None
            squad_status: CodedValue[SquadStatus] | None = None
            event_count: int | None = None
            contract_type: CodedValue[ContractType] | None = None
            clauses: tuple[Clause, ...] = ()
            unknown: FrozenMapping[str, int] = self.empty_unknown
            on_loan: bool | None = None
            loan_parent_club_uid: int | None = None
            loan_parent_club_name: str | None = None
            chain: tuple[ContractChainEntry, ...] = ()
            chain_club_uids: tuple[int | None, ...] = ()
            chain_club_names: tuple[str | None, ...] = ()
            tailed_chain_club_uids: tuple[int, ...] = ()
            if fallback_end is not None and fallback_end >= clock:
                end, end_source = fallback_end, ContractEndSource.FALLBACK
            else:
                end, end_source = None, ContractEndSource.NONE
        else:
            first_record = chain_records[0]
            first_team_id, wage, first_start = first_record[0], first_record[1], first_record[2]
            start = first_start

            if len(chain_records) == 1:
                live_record = chain_records[0]
            else:
                live_record = None
                best_end: date | None = None
                for candidate_record in chain_records:
                    candidate_end = candidate_record[3]
                    if (
                        candidate_record[4]
                        and candidate_end is not None
                        and (best_end is None or candidate_end > best_end)
                    ):
                        live_record = candidate_record
                        best_end = candidate_end
                if live_record is None:
                    live_record = chain_records[-1]

            (
                live_team_id,
                _live_wage,
                _live_start,
                live_end,
                live_has_tail,
                live_squad_status_raw,
                live_event_count,
                live_clauses,
                live_contract_type_raw,
                live_unknown,
            ) = live_record
            live_club_uid, live_club_name = club_by_team_id.get(live_team_id, (None, None))

            if live_end is not None:
                end, end_source = live_end, ContractEndSource.TAIL
            elif not any_tail_parsed and fallback_end is not None and fallback_end >= clock:
                end, end_source = fallback_end, ContractEndSource.FALLBACK
            else:
                end, end_source = None, ContractEndSource.NONE

            if live_has_tail:
                # A tail-bearing record's tail fields are never None; see decode_chain_record.
                assert live_squad_status_raw is not None
                squad_status = self._cached_squad_status(live_squad_status_raw)
                event_count = live_event_count
                clauses = live_clauses
                contract_type = (
                    self._cached_contract_type(live_contract_type_raw)
                    if live_contract_type_raw is not None
                    else None
                )
                unknown = FrozenMapping(live_unknown) if live_unknown else self.empty_unknown
            else:
                squad_status = None
                event_count = None
                contract_type = None
                clauses = ()
                unknown = self.empty_unknown

            on_loan = None
            loan_parent_club_uid = None
            loan_parent_club_name = None
            if player_team_id is not None:
                player_club_uid, _player_club_name = club_by_team_id.get(
                    player_team_id, (None, None)
                )
                first_club_uid, first_club_name = club_by_team_id.get(first_team_id, (None, None))
                if player_club_uid is not None and first_club_uid is not None:
                    on_loan = player_club_uid != first_club_uid
                    if on_loan:
                        loan_parent_club_uid = first_club_uid
                        loan_parent_club_name = first_club_name

            if len(chain_records) == 1:
                only_record = chain_records[0]
                record_team_id = only_record[0]
                record_club_uid, record_club_name = club_by_team_id.get(
                    record_team_id, (None, None)
                )
                chain = (
                    ContractChainEntry(
                        club_uid=record_club_uid,
                        club_name=record_club_name,
                        team_id=record_team_id,
                        wage=only_record[1],
                        start=only_record[2],
                        end=only_record[3],
                        has_tail=only_record[4],
                    ),
                )
                chain_club_uids = (record_club_uid,)
                chain_club_names = (record_club_name,)
                tailed_chain_club_uids = (
                    (record_club_uid,) if only_record[4] and record_club_uid is not None else ()
                )
            else:
                entries: list[ContractChainEntry] = []
                club_uids: list[int | None] = []
                club_names: list[str | None] = []
                tailed_uids: list[int] = []
                for record in chain_records:
                    record_team_id = record[0]
                    record_club_uid, record_club_name = club_by_team_id.get(
                        record_team_id, (None, None)
                    )
                    club_uids.append(record_club_uid)
                    club_names.append(record_club_name)
                    if record[4] and record_club_uid is not None:
                        tailed_uids.append(record_club_uid)
                    entries.append(
                        ContractChainEntry(
                            club_uid=record_club_uid,
                            club_name=record_club_name,
                            team_id=record_team_id,
                            wage=record[1],
                            start=record[2],
                            end=record[3],
                            has_tail=record[4],
                        )
                    )
                chain = tuple(entries)
                chain_club_uids = tuple(club_uids)
                chain_club_names = tuple(club_names)
                tailed_chain_club_uids = tuple(tailed_uids)

        contract = Contract(
            player_uid=player_uid,
            player_name=player_name,
            club_uid=live_club_uid,
            club_name=live_club_name,
            team_id=live_team_id,
            wage=wage,
            start=start,
            end=end,
            end_source=end_source,
            squad_status=squad_status,
            type=contract_type,
            clauses=clauses,
            on_loan=on_loan,
            loan_parent_club_uid=loan_parent_club_uid,
            loan_parent_club_name=loan_parent_club_name,
            event_count=event_count,
            chain=chain,
            chain_club_uids=chain_club_uids,
            chain_club_names=chain_club_names,
            tailed_chain_club_uids=tailed_chain_club_uids,
            unknown=unknown,
        )
        return contract, on_loan, loan_parent_club_uid, loan_parent_club_name


def build_contract_decoder(
    layout: ContractLayout, club_index: ClubIndex, clock: date, file_name: str
) -> ContractDecoder:
    """Build the per-save contract decoder from the save's layout, its ClubIndex and clock."""
    club_by_team_id: dict[int, tuple[int | None, str | None]] = {}
    for team_id, (club_uid, _slot) in club_index.team_to_club.items():
        club = club_index.club_by_uid.get(club_uid)
        club_by_team_id[team_id] = (club_uid, club.name if club is not None else None)
    return ContractDecoder(
        layout=layout,
        club_by_team_id=club_by_team_id,
        clock=clock,
        file_name=file_name,
        tail_struct=_build_tail_struct(layout),
        head_struct=_build_head_struct(layout),
        team_wage_struct=_build_team_wage_struct(layout),
        clause_prefixes=_build_clause_prefixes(layout),
        clause_structs=_build_clause_structs(layout),
        empty_unknown=FrozenMapping({}),
    )
