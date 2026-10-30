"""Synthetic FM27 span fragments; all identities and values are fictional."""

from __future__ import annotations

import struct
from datetime import date

import pytest

from fmsave._errors import CorruptSaveError
from fmsave.readers.fm27_span import Fm27SpanLimits, read_fm27_span


def core(*, home: int = 1201, away: int = 1202, strict: bool = True) -> bytes:
    body = bytearray(65)
    body[0] = 31
    struct.pack_into("<II", body, 1, 401, 502)
    struct.pack_into("<I", body, 12, home)
    struct.pack_into("<I", body, 19, away)
    body[16] = body[23] = 255 if strict else 0
    struct.pack_into("<HH", body, 25, 170 | (12 << 9), 2032)
    return bytes(body)


def packet(*, goals: tuple[int, int] = (2, 1), events: int = 0) -> bytes:
    result = bytearray(29 + events * 16)
    result[0] = 31
    result[5], result[9] = goals
    struct.pack_into("<I", result, 25, events)
    return bytes(result)


def rules(*, quad_matches: bool = True, rounds: int = 2, interstitial: bool = False) -> bytes:
    prefix = bytearray(28)
    prefix[:4] = bytes((1, 2, 0, 3))
    prefix[4:8] = prefix[:4] if quad_matches else bytes((2, 1, 0, 3))
    result = prefix + bytes.fromhex("ffff000001ffffff") + b"\x00"
    result += struct.pack("<I", 2) + bytes((4, 7))
    result += struct.pack("<II", 1, 1234)
    result += struct.pack("<I", rounds)
    for ordinal in range(rounds):
        if ordinal and interstitial:
            result += b"\xff" * 4 + bytes(6)
        row = bytearray(21)
        struct.pack_into("<HH", row, 1, 170 + ordinal, 2032)
        row[5] = 9
        row[6] = ordinal
        struct.pack_into("<I", row, 9, 400 + ordinal)
        row[13] = 7  # Deliberately not a sequential ordinal.
        result += row[1:] if ordinal == 0 else row
    return bytes(result)


def test_strict_core_reads_only_correlated_fields_and_keeps_status_unknown() -> None:
    result = read_fm27_span([core()], clock_year=2032)
    (fixture,) = result.fixtures
    assert fixture.stage_id == 401
    assert fixture.stadium_ordinal == 501
    assert fixture.home_team_id == 1201
    assert fixture.away_team_id == 1202
    assert fixture.date == date(2032, 6, 18)
    assert fixture.packed_kick_off == 170 | (12 << 9)
    assert fixture.played is None
    assert fixture.home_goals is None and fixture.away_goals is None
    assert fixture.strict_anchor
    assert "match_record_id" in fixture.unsupported_fields


def test_owned_prefix_belongs_to_following_fixture_not_preceding_fixture() -> None:
    data = core() + b"\x01" + packet(goals=(3, 2), events=2) + core(home=1301, away=1302)
    first, second = read_fm27_span([data], clock_year=2032).fixtures
    assert first.played is None
    assert second.played is True
    assert (second.home_goals, second.away_goals) == (3, 2)
    assert second.status_source == "sibling_prefix"


def test_zero_owned_prefix_is_unplayed_not_a_goalless_score() -> None:
    data = core() + b"\x00" + core(home=1301, away=1302)
    _, second = read_fm27_span([data], clock_year=2032).fixtures
    assert second.played is False
    assert second.home_goals is None and second.away_goals is None


def test_continuation_is_admitted_only_after_path_closes_on_strict_anchor() -> None:
    middle = core(home=1401, away=1402, strict=False)
    data = core() + b"\x00" + middle + b"\x01" + packet() + core(home=1501, away=1502)
    result = read_fm27_span([data[:39], data[39:91], data[91:]], clock_year=2032)
    assert result.recovered_fixtures == 1
    first, second, third = result.fixtures
    assert first.strict_anchor and not second.strict_anchor and third.strict_anchor
    assert second.played is False
    assert third.played is True
    assert (third.home_goals, third.away_goals) == (2, 1)


def test_unclosed_continuation_never_produces_rows_or_status() -> None:
    data = core() + b"\x00" + core(home=1401, away=1402, strict=False)
    result = read_fm27_span([data], clock_year=2032)
    assert len(result.fixtures) == 1
    assert result.recovered_fixtures == 0
    assert result.fixtures[0].played is None


@pytest.mark.parametrize("prefix", [b"\x02", b"\x00GARBAGE"])
def test_malformed_sibling_path_does_not_resynchronize(prefix: bytes) -> None:
    data = core() + prefix + core(home=1301, away=1302)
    result = read_fm27_span([data], clock_year=2032)
    assert len(result.fixtures) == 2
    assert all(fixture.played is None for fixture in result.fixtures)


def test_absurd_event_count_is_not_traversed_or_treated_as_unplayed() -> None:
    broken = bytearray(packet())
    struct.pack_into("<I", broken, 25, 0xFFFFFFFF)
    data = core() + b"\x01" + broken + core(home=1301, away=1302)
    result = read_fm27_span([data], clock_year=2032)
    assert all(fixture.played is None for fixture in result.fixtures)


def test_rules_walks_counted_rows_and_new_interstitial_prefix() -> None:
    (rule,) = read_fm27_span([rules(interstitial=True)], clock_year=2032).rules
    assert rule.promotion_quad == (1, 2, 0, 3)
    assert rule.tie_breaks == (4, 7)
    assert rule.prize_money == (1234,)
    assert len(rule.rounds) == 2
    assert rule.rounds[0].date == date(2032, 6, 18)
    assert rule.rounds[0].raw_byte13 == rule.rounds[1].raw_byte13 == 7
    assert rule.rounds[1].raw_u32 == 401
    assert rule.interstitial_records == 1


def test_mismatched_promotion_copies_remain_unknown() -> None:
    (rule,) = read_fm27_span([rules(quad_matches=False)], clock_year=2032).rules
    assert rule.promotion_quad is None
    assert len(rule.rounds) == 2


def test_explicit_empty_round_list_is_distinct_from_malformed_parent() -> None:
    (rule,) = read_fm27_span([rules(rounds=0)], clock_year=2032).rules
    assert rule.rounds == ()
    malformed = bytearray(rules())
    struct.pack_into("<I", malformed, 37, 0xFFFFFFFF)
    result = read_fm27_span([malformed], clock_year=2032)
    assert result.rules == ()
    assert result.rejected_rule_candidates == 1


def test_truncated_rules_parent_is_not_partially_returned() -> None:
    result = read_fm27_span([rules()[:-1]], clock_year=2032)
    assert result.rules == ()
    assert result.rejected_rule_candidates == 1


def test_invalid_round_kind_does_not_scan_forward_to_another_date() -> None:
    data = bytearray(rules())
    data[-21] = 1
    result = read_fm27_span([data], clock_year=2032)
    assert result.rules == ()


@pytest.mark.parametrize(
    "limits,frames",
    [
        (Fm27SpanLimits(maximum_span_bytes=64), [bytes(40), bytes(40)]),
        (Fm27SpanLimits(maximum_frame_bytes=64), [bytes(65)]),
        (Fm27SpanLimits(maximum_candidates=1), [core() + core(home=1301, away=1302)]),
        (Fm27SpanLimits(maximum_fixtures=1), [core() + core(home=1301, away=1302)]),
    ],
)
def test_span_resources_are_bounded(limits: Fm27SpanLimits, frames: list[bytes]) -> None:
    with pytest.raises(CorruptSaveError):
        read_fm27_span(frames, clock_year=2032, limits=limits)


def test_memoryview_byte_extent_cannot_bypass_frame_cap() -> None:
    # A typed view's len counts words, not bytes; allocation limits count bytes.
    typed_frame = memoryview(bytes(68)).cast("I")
    with pytest.raises(CorruptSaveError):
        read_fm27_span(
            [typed_frame],
            clock_year=2032,
            limits=Fm27SpanLimits(maximum_frame_bytes=64),
        )


def test_rules_require_the_observed_reserved_byte_before_lists() -> None:
    data = bytearray(rules())
    data[36] = 1
    assert read_fm27_span([data], clock_year=2032).rules == ()
