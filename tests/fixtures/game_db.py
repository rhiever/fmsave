"""In-memory `game_db` fragments for tests, written from observed format facts.

This module must never import fmsave: a wrong offset inside fmsave has to fail
tests built here. All names are fictional.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

NAME_POOL_SIGNATURE = struct.pack("<6I", 46421, 0, 1024, 256, 2048, 0)


def name_pools_bytes(
    first_names: Sequence[str],
    surnames: Sequence[str],
    common_names: Sequence[str],
    *,
    signature: bytes = NAME_POOL_SIGNATURE,
    id_override: dict[tuple[int, int], int] | None = None,
) -> bytes:
    """The signature, then the three pools back to back.

    Each pool is a u32 entry count followed by entries of u32 id, u32 byte length and
    the UTF-8 name. `id_override` maps (pool number, index) to a stored id that differs
    from the index.
    """
    wrong_ids = id_override or {}
    output = bytearray(signature)
    for pool_number, pool_names in enumerate((first_names, surnames, common_names)):
        output.extend(struct.pack("<I", len(pool_names)))
        for entry_index, pool_name in enumerate(pool_names):
            encoded_name = pool_name.encode("utf-8")
            stored_id = wrong_ids.get((pool_number, entry_index), entry_index)
            output.extend(struct.pack("<II", stored_id, len(encoded_name)))
            output.extend(encoded_name)
    return bytes(output)
