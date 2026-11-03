"""Unit tests for the surf-height parser (agent/surf_height.py).

The parser returns the REPRESENTATIVE MIDPOINT of the surf-height range for the
first/current forecast period, not the upper bound.
"""

from agent.surf_height import (
    max_surf_height_midpoint_ft,
    parse_surf_height_midpoint_ft,
)


def _line(value: str) -> str:
    # Reproduce the NWS dotted-leader format the Unity client forwards.
    return f"Surf Height...................{value}"


def test_range_4_to_7_feet_is_midpoint():
    # Canonical case: 4 to 7 feet -> 5.5 (midpoint), NOT 7.0 (upper bound).
    assert parse_surf_height_midpoint_ft(_line("4 to 7 feet.")) == 5.5


def test_range_1_to_2_feet():
    assert parse_surf_height_midpoint_ft(_line("1 to 2 feet.")) == 1.5


def test_range_3_to_5_feet():
    assert parse_surf_height_midpoint_ft(_line("3 to 5 feet.")) == 4.0


def test_range_decimal_4p5_to_6p5_feet():
    assert parse_surf_height_midpoint_ft(_line("4.5 to 6.5 feet.")) == 5.5


def test_single_value_feet_is_itself():
    assert parse_surf_height_midpoint_ft(_line("4 feet.")) == 4.0


def test_case_insensitive_and_ft_unit():
    # 2 to 4 -> midpoint 3.0
    assert parse_surf_height_midpoint_ft("SURF HEIGHT... 2 to 4 FT.") == 3.0


def test_malformed_returns_none():
    assert parse_surf_height_midpoint_ft(_line("Variable.")) is None


def test_glossary_sentence_does_not_match():
    # A glossary-style definition has no numeric value right after the label.
    glossary = "Surf Height is the height of the breaking waves, measured in feet."
    assert parse_surf_height_midpoint_ft(glossary) is None


def test_missing_returns_none():
    assert (
        parse_surf_height_midpoint_ft(
            "Water Temperature.............59 to 61 degrees."
        )
        is None
    )


def test_empty_and_none_return_none():
    assert parse_surf_height_midpoint_ft("") is None
    assert parse_surf_height_midpoint_ft(None) is None


MULTI_PERIOD = """
.THIS AFTERNOON THROUGH MONDAY...
Surf Height...................4 to 7 feet.
Water Temperature.............60 degrees.

.TUESDAY...
Surf Height...................3 to 5 feet.
"""


def test_multiple_periods_uses_first_period_midpoint():
    # First/current period is 4 to 7 -> 5.5, NOT Tuesday's 3 to 5 (4.0).
    assert parse_surf_height_midpoint_ft(MULTI_PERIOD) == 5.5


def test_multiple_periods_max_helper():
    # Worst-case period midpoint: max(5.5, 4.0) = 5.5. (Not used by the engine.)
    assert max_surf_height_midpoint_ft(MULTI_PERIOD) == 5.5
