"""Split pytest cases across CI jobs by stable test ID."""

from __future__ import annotations

import hashlib

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--shard", metavar="INDEX/TOTAL", help="run this 1-based test shard")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    shard = config.getoption("--shard")
    if shard is None:
        return
    try:
        index, total = map(int, shard.split("/"))
    except ValueError as error:
        raise pytest.UsageError("--shard expects INDEX/TOTAL") from error
    if not 1 <= index <= total:
        raise pytest.UsageError("--shard expects 1 <= INDEX <= TOTAL")
    if total == 1:
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        digest = hashlib.sha256(item.nodeid.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % total
        (selected if bucket == index - 1 else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
