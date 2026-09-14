from __future__ import annotations

import copy
import pickle

import pytest

from fmsave._frozen import FrozenMapping


def example_schemas() -> FrozenMapping[str, int]:
    return FrozenMapping({"game_info": 46, "humans": 21})


def test_reads_like_a_mapping() -> None:
    schemas = example_schemas()
    assert schemas["game_info"] == 46
    assert list(schemas) == ["game_info", "humans"]
    assert len(schemas) == 2
    assert "humans" in schemas
    assert schemas.get("no_such_section") is None


def test_keeps_its_own_copy_of_the_items() -> None:
    source_items = {"game_info": 46}
    schemas = FrozenMapping(source_items)
    source_items["game_info"] = 1
    assert schemas["game_info"] == 46


def test_equals_a_plain_dict() -> None:
    assert example_schemas() == {"game_info": 46, "humans": 21}
    assert example_schemas() != {"game_info": 46}


def test_repr_is_shaped_like_a_dict() -> None:
    assert repr(example_schemas()) == "{'game_info': 46, 'humans': 21}"


def test_mutation_attempts_raise_type_error() -> None:
    schemas = example_schemas()
    with pytest.raises(TypeError):
        schemas["game_info"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        del schemas["game_info"]  # type: ignore[attr-defined]
    assert schemas == {"game_info": 46, "humans": 21}


def test_is_unhashable_and_has_no_instance_dictionary() -> None:
    schemas = example_schemas()
    with pytest.raises(TypeError):
        hash(schemas)
    assert not hasattr(schemas, "__dict__")


def test_pickle_and_copies_keep_type_and_items() -> None:
    schemas = example_schemas()
    for copied_schemas in (
        pickle.loads(pickle.dumps(schemas)),
        copy.deepcopy(schemas),
        copy.copy(schemas),
    ):
        assert type(copied_schemas) is FrozenMapping
        assert copied_schemas == schemas
