from dataclasses import fields

import pytest

from fmsave import StaffAttributes


def test_staff_display_scale_uses_the_scale_of_each_field() -> None:
    native_ratings = {"adaptability": 0, "authority": 19, "working_with_youngsters": 7}
    stored = {field.name: 16 for field in fields(StaffAttributes)} | native_ratings
    attributes = StaffAttributes(**stored)

    display = attributes.to_display_scale()

    expected = {field.name: 3 for field in fields(StaffAttributes)} | native_ratings
    assert display == StaffAttributes(**expected)
    assert attributes == StaffAttributes(**stored)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(None, None), (1, 1), (12, 2), (13, 3), (100, 20), (125, 20)],
)
def test_staff_display_scale_rounds_and_bounds_available_ratings(
    stored: int | None, expected: int | None
) -> None:
    attributes = StaffAttributes(adaptability=9, motivating=stored)

    assert attributes.to_display_scale() == StaffAttributes(adaptability=9, motivating=expected)
