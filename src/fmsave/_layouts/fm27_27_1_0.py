"""Build-specific layouts for FM27 27.1.0+2505117."""

from dataclasses import replace

from fmsave._layouts import LayoutEntry
from fmsave._layouts import fm27_27_0_0 as previous

BUILD = "27.1.0+2505117"
KNOWN_BUILDS: tuple[str, ...] = ()

# The full finance suffix gains five bytes before the current balance.
_INSERT_AT = 22
_INSERT_BYTES = 5
_previous_suffix = previous.CLUB_TABLE.full_finance[-1]
CLUB_TABLE = replace(
    previous.CLUB_TABLE,
    full_finance=(
        *previous.CLUB_TABLE.full_finance[:-1],
        replace(_previous_suffix, lead_bytes=_previous_suffix.lead_bytes + _INSERT_BYTES),
    ),
)


def _shift_suffix_offset(offset: int) -> int:
    return offset + _INSERT_BYTES if offset >= _INSERT_AT else offset


SPONSOR_CHAINS = replace(
    previous.SPONSOR_CHAINS,
    prefix_suffix_bytes=previous.SPONSOR_CHAINS.prefix_suffix_bytes + _INSERT_BYTES,
    prefix_suffix_fixed=tuple(
        (_shift_suffix_offset(offset), expected)
        for offset, expected in previous.SPONSOR_CHAINS.prefix_suffix_fixed
    ),
    prefix_suffix_date_offsets=tuple(
        _shift_suffix_offset(offset)
        for offset in previous.SPONSOR_CHAINS.prefix_suffix_date_offsets
    ),
    balance_offset=_shift_suffix_offset(_INSERT_AT),
)

LAYOUTS = (
    LayoutEntry("game_db", 4000, BUILD, CLUB_TABLE),
    LayoutEntry("game_db", 4000, BUILD, SPONSOR_CHAINS),
    LayoutEntry("match_stats_cfg", 6, BUILD, previous.MATCH_REPORTS),
)
