"""A read-only mapping for public records."""

from __future__ import annotations

from collections.abc import Iterator, Mapping


class FrozenMapping[KeyT, ValueT](Mapping[KeyT, ValueT]):
    """An immutable mapping that holds its own copy of the items.

    Unlike types.MappingProxyType it can be pickled and deep-copied, so records holding one
    can be too. It compares equal to any mapping with the same items and is not hashable.
    """

    __slots__ = ("_items",)
    __hash__ = None

    def __init__(self, items: Mapping[KeyT, ValueT]) -> None:
        self._items: dict[KeyT, ValueT] = dict(items)

    def __getitem__(self, key: KeyT) -> ValueT:
        return self._items[key]

    def __iter__(self) -> Iterator[KeyT]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(self._items)

    def __reduce__(self) -> tuple[type[FrozenMapping[KeyT, ValueT]], tuple[dict[KeyT, ValueT]]]:
        return (FrozenMapping, (dict(self),))
