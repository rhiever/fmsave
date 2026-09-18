"""The facilities rating a club keeps behind its monthly finance chain, club record by record.

The rating sits a fixed number of bytes past the **end** of the chain, so it moves down the
record as a career adds months to the chain: an offset counted from the record's head lands on
it only while the chain holds one particular number of rows, which is what an earlier reading
of this format got wrong. So this reader locates the chain exactly as the finance reader does
and then steps forward from where that chain ends.

Only a club with a chain has a rating, and only the clubs of the one or two league nations a
save tracks keep a chain, so most clubs yield no row at all. That is ordinary rather than a
fault, and it is the same population `finances()` covers.
"""

from __future__ import annotations

from fmsave._layouts import FacilityByteLayout, find_layout
from fmsave._reader_stats import FacilityStats
from fmsave.models.common import CodedValue
from fmsave.models.facilities import ClubFacilities, CorporateFacilities
from fmsave.readers._common import GAME_DB_SECTION
from fmsave.readers.clubs import ClubIndex
from fmsave.readers.finances import FinanceLayouts, locate_finance_chain, searched_record


def find_facility_layout(game_db_schema: int | None, build: str) -> FacilityByteLayout:
    """Look up the facility-byte layout for a `game_db` schema, falling back to the build."""
    return find_layout(FacilityByteLayout, GAME_DB_SECTION, game_db_schema, build).layout


def read_club_facilities(
    game_db: bytes,
    club_index: ClubIndex,
    finance_layouts: FinanceLayouts,
    layout: FacilityByteLayout,
    managed_club_exists: bool,
) -> tuple[tuple[ClubFacilities, ...], FacilityStats]:
    """Every club's facilities rating, in club index order, with what the pass counted.

    A club whose record holds no finance chain yields no row, so a save whose clubs keep none
    yields an empty table. A club whose record ends before the rating would sit is counted as
    a club with a chain and yields no row either, which no club of any save measured does and
    which the checks see as a rating the offset did not land on. A rating outside the layout's
    range is returned exactly as stored, labelled UNKNOWN like any unnamed code, and counted:
    blanking it would hide the one measurement that says whether the offset still lands on the
    rating at all.
    """
    chain_layout = finance_layouts.chains
    offset_after_chain = layout.offset_after_chain
    lowest_value, highest_value = layout.value_range
    span_by_club_uid = {span.club_uid: span for span in club_index.record_spans}
    rows: list[ClubFacilities] = []
    clubs_with_series = 0
    in_range = 0
    for club in club_index.clubs:
        span = span_by_club_uid.get(club.uid)
        if span is None or not searched_record(span, chain_layout):
            continue
        located_chain = locate_finance_chain(game_db, span, chain_layout)
        if located_chain is None:
            continue
        clubs_with_series += 1
        head, row_count, _chains_found = located_chain
        rating_offset = head + chain_layout.row_bytes * row_count + offset_after_chain
        if rating_offset >= min(span.record_end, len(game_db)):
            continue
        value = game_db[rating_offset]
        if lowest_value <= value <= highest_value:
            in_range += 1
        rows.append(
            ClubFacilities(
                club_uid=club.uid,
                club_name=club.name,
                corporate_facilities=CodedValue.from_raw(CorporateFacilities, value),
            )
        )
    return (
        tuple(rows),
        FacilityStats(
            clubs_with_series=clubs_with_series,
            rows=len(rows),
            in_range=in_range,
            managed_club_exists=managed_club_exists,
        ),
    )
