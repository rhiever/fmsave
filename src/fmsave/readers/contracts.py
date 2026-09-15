"""Decoding a player's contract chain in `game_db` into `Contract`.

A player's contract is assembled from a chain of registration records (the tag
`01 00 6c 07` plus a matching selector), searched for in the player's own record window.
`_decode_chain_record` decodes a single located record: its tail (an end date, squad
status, contract type and event count), its clauses, and its head (contract type and
three money fields). It is callable on its own, without a player window, from just the
tag's offset. `decode_contract` finds every chain record for one player, decodes each,
then assembles the public `Contract` by the assembly rules documented on `ContractLayout`
and on the `Contract` and `ContractChainEntry` models.
"""

from __future__ import annotations

import functools
import struct
from dataclasses import dataclass
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

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_FOUR_FF = b"\xff\xff\xff\xff"
_MISSING_U32 = 0xFFFFFFFF
_MISSING_U16 = 0xFFFF


# CodedValue.from_raw resolves an unnamed code through a try/except ValueError, so a save's
# small set of distinct raw codes is cached rather than re-resolved on every clause, squad
# status or contract type read.
@functools.cache
def _cached_clause_kind(raw_kind: int) -> CodedValue[ClauseKind]:
    return CodedValue.from_raw(ClauseKind, raw_kind)


@functools.cache
def _cached_squad_status(raw_status: int) -> CodedValue[SquadStatus]:
    return CodedValue.from_raw(SquadStatus, raw_status)


@functools.cache
def _cached_contract_type(raw_type: int) -> CodedValue[ContractType]:
    return CodedValue.from_raw(ContractType, raw_type)


@dataclass(frozen=True, slots=True)
class _TailFields:
    """Every field read from a parsed tail block, in raw (unlabelled) form."""

    e2: int
    e8: int
    e12: int
    e16: int
    e20: int
    e24: int
    end: date | None
    squad_status_raw: int
    e37: int
    e38: int
    e39: int
    event_count: int


@dataclass(frozen=True, slots=True)
class _HeadFields:
    """The four fields read only when a clause table's head gate matches."""

    contract_type_raw: int
    money_a: int
    money_b: int
    money_c: int


@dataclass(frozen=True, slots=True)
class _ChainRecord:
    """One located and decoded chain record, before club resolution."""

    chain_tag_offset: int
    team_id: int
    wage: int
    start: date | None
    tail: _TailFields | None
    clauses: tuple[Clause, ...]
    head: _HeadFields | None


def _locate_tail(game_db: bytes, chain_tag_offset: int, layout: ContractLayout) -> int | None:
    """The tail start offset E, or None when no candidate's checks all pass."""
    game_db_length = len(game_db)
    for event_count in range(layout.tail_max_event_count + 1):
        tail_offset = (
            chain_tag_offset - layout.tail_base_offset - layout.tail_step_bytes * event_count
        )
        if tail_offset < 0:
            return None
        if tail_offset + 46 > game_db_length:
            continue
        if game_db[tail_offset] != 0:
            continue
        if game_db[tail_offset + 1] != 0:
            continue
        if game_db[tail_offset + 3] != 3:
            continue
        four: int = _U32.unpack_from(game_db, tail_offset + 4)[0]
        if four != 4:
            continue
        stored_event_count: int = _U32.unpack_from(
            game_db, tail_offset + layout.tail_event_count_offset
        )[0]
        if stored_event_count != event_count:
            continue
        return tail_offset
    return None


def _read_tail_fields(game_db: bytes, tail_offset: int, layout: ContractLayout) -> _TailFields:
    e2: int = _U16.unpack_from(game_db, tail_offset + layout.tail_e2_offset)[0]
    e8: int = _U32.unpack_from(game_db, tail_offset + layout.tail_e8_offset)[0]
    e12: int = _U32.unpack_from(game_db, tail_offset + layout.tail_e12_offset)[0]
    e16: int = _U32.unpack_from(game_db, tail_offset + layout.tail_e16_offset)[0]
    e20: int = _U32.unpack_from(game_db, tail_offset + layout.tail_e20_offset)[0]
    e24: int = _U32.unpack_from(game_db, tail_offset + layout.tail_e24_offset)[0]
    end = decode_date(game_db, tail_offset + layout.tail_end_offset)
    squad_status_raw = game_db[tail_offset + layout.tail_squad_status_offset]
    e37 = game_db[tail_offset + layout.tail_e37_offset]
    e38 = game_db[tail_offset + layout.tail_e38_offset]
    e39 = game_db[tail_offset + layout.tail_e39_offset]
    event_count: int = _U32.unpack_from(game_db, tail_offset + layout.tail_event_count_offset)[0]
    return _TailFields(
        e2=e2,
        e8=e8,
        e12=e12,
        e16=e16,
        e20=e20,
        e24=e24,
        end=end,
        squad_status_raw=squad_status_raw,
        e37=e37,
        e38=e38,
        e39=e39,
        event_count=event_count,
    )


def _locate_clause_base(
    game_db: bytes, tail_offset: int, layout: ContractLayout
) -> tuple[int, int] | None:
    """(base, count), or None when no candidate count's checks all pass."""
    game_db_length = len(game_db)
    for count in range(layout.clause_max_count + 1):
        base = tail_offset - layout.clause_step_bytes * count
        ff_start = base + layout.clause_ff_offset
        if ff_start < 0:
            return None
        zero_start = base + layout.clause_zero_offset
        count_at = base + layout.clause_count_offset
        if count_at >= game_db_length:
            continue
        if game_db[count_at] != count:
            continue
        if game_db[zero_start : zero_start + layout.clause_zero_count] != bytes(
            layout.clause_zero_count
        ):
            continue
        if game_db[ff_start : ff_start + layout.clause_ff_count] != _FOUR_FF * (
            layout.clause_ff_count // 4
        ):
            continue
        return base, count
    return None


def _read_clauses(
    game_db: bytes, base: int, count: int, layout: ContractLayout
) -> tuple[Clause, ...]:
    if count == 0:
        return ()
    entries_start = base + layout.clause_entries_offset
    entry_bytes = layout.clause_entry_bytes
    game_db_length = len(game_db)
    clauses: list[Clause] = []
    for index in range(count):
        entry_start = entries_start + entry_bytes * index
        if entry_start < 0 or entry_start + entry_bytes > game_db_length:
            break
        raw_value: int = _U32.unpack_from(game_db, entry_start + layout.clause_value_offset)[0]
        raw_parameter: int = _U16.unpack_from(
            game_db, entry_start + layout.clause_parameter_offset
        )[0]
        raw_kind: int = _U16.unpack_from(game_db, entry_start + layout.clause_kind_offset)[0]
        value = None if raw_value == _MISSING_U32 else raw_value
        parameter = None if raw_parameter == _MISSING_U16 else raw_parameter
        clauses.append(Clause(kind=_cached_clause_kind(raw_kind), parameter=parameter, value=value))
    return tuple(clauses)


def _read_head(game_db: bytes, base: int, layout: ContractLayout) -> _HeadFields | None:
    gate_offset = base + layout.head_gate_offset
    if gate_offset < 0 or gate_offset + 2 > len(game_db):
        return None
    gate_value: int = _U16.unpack_from(game_db, gate_offset)[0]
    if gate_value != layout.head_gate_value:
        return None
    type_offset = base + layout.head_type_offset
    money_a_offset = base + layout.head_money_a_offset
    money_b_offset = base + layout.head_money_b_offset
    money_c_offset = base + layout.head_money_c_offset
    if type_offset < 0 or money_c_offset + 4 > len(game_db):
        return None
    contract_type_raw = game_db[type_offset]
    money_a: int = _U32.unpack_from(game_db, money_a_offset)[0]
    money_b: int = _U32.unpack_from(game_db, money_b_offset)[0]
    money_c: int = _U32.unpack_from(game_db, money_c_offset)[0]
    return _HeadFields(
        contract_type_raw=contract_type_raw, money_a=money_a, money_b=money_b, money_c=money_c
    )


def _decode_chain_record(
    game_db: bytes, chain_tag_offset: int, layout: ContractLayout, file_name: str
) -> _ChainRecord:
    """Decode one chain record's tail, clauses and head from its tag offset alone.

    Callable without a player window: every offset it reads counts from chain_tag_offset,
    or from a tail or clause-table offset found relative to it.

    Raises:
        CorruptSaveError: The record's team id or wage runs past the end of game_db.
    """
    fixed_fields_end = chain_tag_offset + max(layout.team_id_offset, layout.wage_offset) + 4
    if fixed_fields_end > len(game_db):
        raise CorruptSaveError(
            f"{section_label(file_name)}: a contract chain record at offset {chain_tag_offset} "
            f"needs bytes up to offset {fixed_fields_end}, past the end of the section"
        )
    team_id: int = _U32.unpack_from(game_db, chain_tag_offset + layout.team_id_offset)[0]
    wage: int = _U32.unpack_from(game_db, chain_tag_offset + layout.wage_offset)[0]
    start_offset = chain_tag_offset + layout.start_offset
    start = decode_date(game_db, start_offset) if start_offset >= 0 else None

    tail_offset = _locate_tail(game_db, chain_tag_offset, layout)
    if tail_offset is None:
        return _ChainRecord(
            chain_tag_offset=chain_tag_offset,
            team_id=team_id,
            wage=wage,
            start=start,
            tail=None,
            clauses=(),
            head=None,
        )

    tail = _read_tail_fields(game_db, tail_offset, layout)
    clause_base = _locate_clause_base(game_db, tail_offset, layout)
    if clause_base is None:
        return _ChainRecord(
            chain_tag_offset=chain_tag_offset,
            team_id=team_id,
            wage=wage,
            start=start,
            tail=tail,
            clauses=(),
            head=None,
        )
    base, count = clause_base
    clauses = _read_clauses(game_db, base, count, layout)
    head = _read_head(game_db, base, layout)
    return _ChainRecord(
        chain_tag_offset=chain_tag_offset,
        team_id=team_id,
        wage=wage,
        start=start,
        tail=tail,
        clauses=clauses,
        head=head,
    )


def _iter_chain_tag_hits(
    game_db: bytes, search_start: int, search_end: int, tag: bytes
) -> list[int]:
    hits: list[int] = []
    position = search_start
    find = game_db.find
    while True:
        hit = find(tag, position, search_end)
        if hit < 0:
            return hits
        hits.append(hit)
        position = hit + 1


def _find_chain_records(
    game_db: bytes,
    record_offset: int,
    record_window_end: int,
    is_last_record: bool,
    pindex: int,
    layout: ContractLayout,
    file_name: str,
) -> list[_ChainRecord]:
    search_start = max(0, record_offset + layout.chain_window_start_offset)
    search_end = (
        record_window_end if is_last_record else record_window_end + layout.chain_window_end_offset
    )
    search_end = max(search_start, search_end)
    selector = pindex + 1
    game_db_length = len(game_db)
    records: list[_ChainRecord] = []
    for chain_tag_offset in _iter_chain_tag_hits(game_db, search_start, search_end, layout.tag):
        selector_offset = chain_tag_offset + layout.selector_offset
        if selector_offset < 0 or selector_offset + 4 > game_db_length:
            continue
        stored_selector: int = _U32.unpack_from(game_db, selector_offset)[0]
        if stored_selector != selector:
            continue
        records.append(_decode_chain_record(game_db, chain_tag_offset, layout, file_name))
    return records


def _find_fallback_dates(
    game_db: bytes,
    record_offset: int,
    record_window_end: int,
    is_last_record: bool,
    layout: ContractLayout,
) -> tuple[date | None, date | None]:
    """(start, end) with the latest end among valid pairs, or (None, None)."""
    search_start = record_offset + layout.fallback_start_from_record
    next_reference = len(game_db) if is_last_record else record_window_end
    limit = max(search_start, next_reference - layout.fallback_end_margin)
    game_db_length = len(game_db)
    best_start: date | None = None
    best_end: date | None = None
    position = search_start
    find = game_db.find
    needle = _FOUR_FF
    while True:
        hit = find(needle, position, min(limit, game_db_length))
        if hit < 0:
            break
        dates_offset = hit + 8  # "j" in the layout docstring: the FF run is 8 bytes long
        nonzero_start = dates_offset + layout.fallback_nonzero_offset
        if (
            dates_offset + layout.fallback_gate_length <= limit
            and nonzero_start + layout.fallback_nonzero_length <= game_db_length
        ):
            nonzero_region = game_db[nonzero_start : nonzero_start + layout.fallback_nonzero_length]
            if nonzero_region != bytes(layout.fallback_nonzero_length):
                end_date = decode_date(game_db, dates_offset + layout.fallback_end_date_offset)
                start_date = decode_date(game_db, dates_offset + layout.fallback_start_date_offset)
                if (
                    end_date is not None
                    and start_date is not None
                    and end_date > start_date
                    and (best_end is None or end_date > best_end)
                ):
                    best_end = end_date
                    best_start = start_date
        position = hit + 1
    return best_start, best_end


def _resolve_club(team_id: int, club_index: ClubIndex) -> tuple[int | None, str | None]:
    resolved = club_index.team_to_club.get(team_id)
    if resolved is None:
        return None, None
    club_uid, _slot = resolved
    club = club_index.club_by_uid.get(club_uid)
    return club_uid, (club.name if club is not None else None)


def _pick_live_record(chain_records: list[_ChainRecord]) -> _ChainRecord | None:
    """Among tailed records with a non-null end, the latest end (first on ties); else last."""
    best: _ChainRecord | None = None
    best_end: date | None = None
    for record in chain_records:
        tail = record.tail
        if tail is not None and tail.end is not None and (best_end is None or tail.end > best_end):
            best = record
            best_end = tail.end
    if best is not None:
        return best
    return chain_records[-1] if chain_records else None


def _build_unknown(tail: _TailFields | None, head: _HeadFields | None) -> dict[str, int]:
    unknown: dict[str, int] = {}
    if tail is not None:
        unknown["e2"] = tail.e2
        unknown["e8"] = tail.e8
        unknown["e12"] = tail.e12
        unknown["e16"] = tail.e16
        unknown["e20"] = tail.e20
        unknown["e24"] = tail.e24
        unknown["e37"] = tail.e37
        unknown["e38"] = tail.e38
        unknown["e39"] = tail.e39
    if head is not None:
        unknown["money_a"] = head.money_a
        unknown["money_b"] = head.money_b
        unknown["money_c"] = head.money_c
    return unknown


def decode_contract(
    game_db: bytes,
    record_offset: int,
    record_window_end: int,
    is_last_record: bool,
    pindex: int,
    player_uid: int,
    player_name: str | None,
    player_team_id: int | None,
    club_index: ClubIndex,
    clock: date,
    layout: ContractLayout,
    file_name: str,
) -> tuple[Contract | None, bool | None, int | None, str | None]:
    """Assemble one player's contract from their chain records and, when needed, the
    fallback reader.

    Returns (contract, on_loan, loan_parent_club_uid, loan_parent_club_name); the last
    three are also carried inside contract when it is not None.

    Raises:
        CorruptSaveError: A chain record's team id or wage runs past the end of game_db.
    """
    chain_records = _find_chain_records(
        game_db, record_offset, record_window_end, is_last_record, pindex, layout, file_name
    )

    any_tail_parsed = any(record.tail is not None for record in chain_records)
    need_fallback = not chain_records or not any_tail_parsed
    fallback_start: date | None = None
    fallback_end: date | None = None
    if need_fallback:
        fallback_start, fallback_end = _find_fallback_dates(
            game_db, record_offset, record_window_end, is_last_record, layout
        )

    if not chain_records and fallback_start is None and fallback_end is None:
        return None, None, None, None

    wage = chain_records[0].wage if chain_records else None

    start = chain_records[0].start if chain_records else fallback_start

    live_record = _pick_live_record(chain_records)

    if (
        live_record is not None
        and live_record.tail is not None
        and live_record.tail.end is not None
    ):
        end = live_record.tail.end
        end_source = ContractEndSource.TAIL
    elif not any_tail_parsed and fallback_end is not None and fallback_end >= clock:
        end = fallback_end
        end_source = ContractEndSource.FALLBACK
    else:
        end = None
        end_source = ContractEndSource.NONE

    if live_record is not None:
        live_club_uid, live_club_name = _resolve_club(live_record.team_id, club_index)
        live_team_id: int | None = live_record.team_id
        if live_record.tail is not None:
            squad_status = _cached_squad_status(live_record.tail.squad_status_raw)
            event_count: int | None = live_record.tail.event_count
            clauses = live_record.clauses
            contract_type = (
                _cached_contract_type(live_record.head.contract_type_raw)
                if live_record.head is not None
                else None
            )
            unknown = _build_unknown(live_record.tail, live_record.head)
        else:
            squad_status = None
            event_count = None
            clauses = ()
            contract_type = None
            unknown = {}
    else:
        live_club_uid = live_club_name = None
        live_team_id = None
        squad_status = None
        event_count = None
        clauses = ()
        contract_type = None
        unknown = {}

    on_loan: bool | None = None
    loan_parent_club_uid: int | None = None
    loan_parent_club_name: str | None = None
    if chain_records and player_team_id is not None:
        player_club_uid, _player_club_name = _resolve_club(player_team_id, club_index)
        first_club_uid, first_club_name = _resolve_club(chain_records[0].team_id, club_index)
        if player_club_uid is not None and first_club_uid is not None:
            on_loan = player_club_uid != first_club_uid
            if on_loan:
                loan_parent_club_uid = first_club_uid
                loan_parent_club_name = first_club_name

    chain_club_uids: list[int | None] = []
    chain_club_names: list[str | None] = []
    tailed_chain_club_uids: list[int] = []
    chain_entries: list[ContractChainEntry] = []
    for record in chain_records:
        record_club_uid, record_club_name = _resolve_club(record.team_id, club_index)
        chain_club_uids.append(record_club_uid)
        chain_club_names.append(record_club_name)
        if record.tail is not None and record_club_uid is not None:
            tailed_chain_club_uids.append(record_club_uid)
        chain_entries.append(
            ContractChainEntry(
                club_uid=record_club_uid,
                club_name=record_club_name,
                team_id=record.team_id,
                wage=record.wage,
                start=record.start,
                end=record.tail.end if record.tail is not None else None,
                has_tail=record.tail is not None,
            )
        )

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
        chain=tuple(chain_entries),
        chain_club_uids=tuple(chain_club_uids),
        chain_club_names=tuple(chain_club_names),
        tailed_chain_club_uids=tuple(tailed_chain_club_uids),
        unknown=FrozenMapping(unknown),
    )
    return contract, on_loan, loan_parent_club_uid, loan_parent_club_name
