from __future__ import annotations

import copy
import pickle
from enum import IntEnum
from typing import assert_type

import pytest

from fmsave.models import CodedValue, ContractEndSource, TransferValueState


class ExampleStatus(IntEnum):
    UNKNOWN = -1
    FIRST_CHOICE = 3
    BACKUP = 20


class ExampleWithoutUnknown(IntEnum):
    FIRST_CHOICE = 3


class ExampleWithMisplacedUnknown(IntEnum):
    UNKNOWN = 0
    FIRST_CHOICE = 3


def test_known_raw_value_gets_its_member_label() -> None:
    coded_status: CodedValue[ExampleStatus] = CodedValue.from_raw(ExampleStatus, 3)
    assert coded_status.label is ExampleStatus.FIRST_CHOICE
    assert coded_status.raw == 3
    assert coded_status.label_text == "first_choice"


def test_from_raw_infers_the_enum_type() -> None:
    assert_type(CodedValue.from_raw(ExampleStatus, 3), CodedValue[ExampleStatus])


def test_unrecognised_raw_value_is_unknown_and_keeps_the_raw_value() -> None:
    coded_status = CodedValue.from_raw(ExampleStatus, 9)
    assert coded_status.label is ExampleStatus.UNKNOWN
    assert coded_status.raw == 9
    assert coded_status.label_text == "unknown"


def test_raw_value_equal_to_the_unknown_member_is_unknown() -> None:
    coded_status = CodedValue.from_raw(ExampleStatus, -1)
    assert coded_status.label is ExampleStatus.UNKNOWN
    assert coded_status.raw == -1


def test_enum_without_unknown_member_raises_type_error() -> None:
    with pytest.raises(TypeError, match="ExampleWithoutUnknown"):
        CodedValue.from_raw(ExampleWithoutUnknown, 3)


def test_enum_whose_unknown_member_is_not_minus_one_raises_type_error() -> None:
    with pytest.raises(TypeError, match="ExampleWithMisplacedUnknown"):
        CodedValue.from_raw(ExampleWithMisplacedUnknown, 3)


def test_coded_values_are_immutable_and_slotted() -> None:
    coded_status = CodedValue.from_raw(ExampleStatus, 3)
    with pytest.raises(AttributeError):
        coded_status.raw = 20  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(AttributeError):
        coded_status.label = ExampleStatus.BACKUP  # pyright: ignore[reportAttributeAccessIssue]
    assert not hasattr(coded_status, "__dict__")
    assert coded_status == CodedValue.from_raw(ExampleStatus, 3)


def test_equal_pairs_compare_equal_and_hash_alike() -> None:
    first_status = CodedValue.from_raw(ExampleStatus, 20)
    second_status = CodedValue(label=ExampleStatus.BACKUP, raw=20)
    assert first_status == second_status
    assert hash(first_status) == hash(second_status)
    assert len({first_status, second_status}) == 1
    assert CodedValue.from_raw(ExampleStatus, 9) != CodedValue.from_raw(ExampleStatus, 10)
    assert CodedValue.from_raw(ExampleStatus, 3) != CodedValue.from_raw(ExampleStatus, 20)


def test_coded_values_survive_pickle_and_deepcopy() -> None:
    coded_status = CodedValue.from_raw(ExampleStatus, 9)
    for copied_status in (pickle.loads(pickle.dumps(coded_status)), copy.deepcopy(coded_status)):
        assert type(copied_status) is CodedValue
        assert copied_status == coded_status
        assert copied_status.label is ExampleStatus.UNKNOWN


def test_transfer_value_state_members() -> None:
    assert TransferValueState("unset") is TransferValueState.UNSET
    assert [state.value for state in TransferValueState] == ["ok", "unset", "placeholder", "zero"]


def test_contract_end_source_members() -> None:
    assert str(ContractEndSource.CONTRACT) == "contract"
    assert [source.value for source in ContractEndSource] == [
        "contract",
        "player_record",
        "none",
    ]
