"""Regression tests: reading the correct San Luis Obispo forecast period.

These exercise the geographic zone filter (``noaa_forecast.extract_zone_section``)
together with the surf-height midpoint parser (``surf_height``) on a realistic
multi-period, multi-zone NWS Surf Zone Forecast (SRF) product.

Verified properties (see the paper's parser description):
1. The parser uses the FIRST/current forecast period.
2. It does NOT use a later period (e.g. Tuesday).
3. It does NOT parse a different geographic zone.
4. It returns the MIDPOINT of the current period's range.
5. The shared "San Luis Obispo County Beaches / Santa Barbara Central Coast
   Beaches-" zone heading is handled correctly.
6. It returns None when no Surf Height line is present.
"""

from agent.noaa_forecast import extract_zone_section
from agent.surf_height import parse_surf_height_midpoint_ft

# A realistic LOX (Los Angeles/Oxnard) SRF product. Two geographic zone
# sections separated by "$$". The SLO section (CAZ349-350) is a SHARED heading
# covering both "San Luis Obispo County Beaches" and "Santa Barbara Central
# Coast Beaches" and lists two periods. A second, DIFFERENT zone
# (CAZ040 Los Angeles County Beaches) has a different surf height, to prove the
# geographic filter is doing its job.
FULL_SRF = """000
FZUS56 KLOX 291030
SRFLOX

Surf Zone Forecast for Southwestern California
National Weather Service Los Angeles/Oxnard CA
330 AM PDT Fri Aug 29 2025

CAZ349-350-292215-
San Luis Obispo County Beaches-
Santa Barbara Central Coast Beaches-
330 AM PDT Fri Aug 29 2025

.THIS AFTERNOON THROUGH MONDAY...
Surf Height...................4 to 7 feet.
Thunderstorm Potential........None expected.
Water Temperature.............58 to 62 degrees.
Tides.........................Low 1.2 feet 09 AM. High 4.1 feet 03 PM.
Remarks.......................None.

.TUESDAY...
Surf Height...................3 to 5 feet.

$$

CAZ040-292215-
Los Angeles County Beaches-
330 AM PDT Fri Aug 29 2025

.THIS AFTERNOON THROUGH MONDAY...
Surf Height...................1 to 2 feet.

.TUESDAY...
Surf Height...................2 to 3 feet.

$$
"""


def test_slo_section_current_period_midpoint():
    # zone_match "349" selects the SLO/Santa Barbara Central Coast shared zone.
    section = extract_zone_section(FULL_SRF, "349")
    assert section is not None
    # Current period is "4 to 7 feet" -> midpoint 5.5 (NOT Tuesday's 3-5 -> 4.0,
    # NOT the LA zone's 1-2 -> 1.5).
    assert parse_surf_height_midpoint_ft(section) == 5.5


def test_shared_heading_lines_present_in_selected_section():
    section = extract_zone_section(FULL_SRF, "349")
    assert "San Luis Obispo County Beaches" in section
    assert "Santa Barbara Central Coast Beaches" in section
    # The other geographic zone must NOT be in the selected section.
    assert "Los Angeles County Beaches" not in section


def test_geographic_filter_isolates_other_zone():
    # The LA zone (CAZ040) has its own, different current-period surf.
    la_section = extract_zone_section(FULL_SRF, "040")
    assert la_section is not None
    assert parse_surf_height_midpoint_ft(la_section) == 1.5  # midpoint of 1 to 2
    assert "Los Angeles County Beaches" in la_section
    assert "San Luis Obispo County Beaches" not in la_section


def test_does_not_use_tuesday_period():
    section = extract_zone_section(FULL_SRF, "349")
    # Tuesday's value (3 to 5 -> 4.0) must not be what is returned.
    assert parse_surf_height_midpoint_ft(section) != 4.0


def test_none_when_no_surf_height_line():
    # A well-formed SLO section that omits the Surf Height line entirely.
    no_surf = """CAZ349-350-292215-
San Luis Obispo County Beaches-
Santa Barbara Central Coast Beaches-
330 AM PDT Fri Aug 29 2025

.THIS AFTERNOON THROUGH MONDAY...
Thunderstorm Potential........None expected.
Water Temperature.............58 to 62 degrees.

$$
"""
    section = extract_zone_section(no_surf, "349")
    assert section is not None
    assert parse_surf_height_midpoint_ft(section) is None
