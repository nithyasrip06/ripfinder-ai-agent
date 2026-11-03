"""Surf-height extraction from NWS Surf Zone Forecast (SRF) text.

This module parses the free-form ``forecast`` string that the Unity client
posts to ``/v1/assess`` (the geographically filtered "San Luis Obispo County
Beaches" SRF section) and returns a numeric surf height in feet.

Why this exists
---------------
The deterministic risk engine's forecast rule (``reasoning_engine``) does a
plain keyword substring match for phrases like "rip current" / "high surf".
For the configured Pismo/SLO zone the NWS SRF product frequently contains *no*
such phrase -- only ``Surf Height...`` / ``Water Temperature...`` / ``Tides...``
lines -- so the keyword contribution is effectively zero for that zone. This
parser lets the engine use a signal that is actually present in the forecast.

What it returns
---------------
The **representative midpoint** of the surf-height range, as a float in feet::

    "Surf Height...................4 to 7 feet."   -> 5.5   (midpoint of 4..7)
    "Surf Height...................1 to 2 feet."   -> 1.5
    "Surf Height...................3 to 5 feet."   -> 4.0
    "Surf Height...................4.5 to 6.5 feet."-> 5.5
    "Surf Height...................4 feet."         -> 4.0   (single value)

Returns ``None`` when no surf-height value can be found.

Why the midpoint (not the upper bound)
--------------------------------------
Earlier prototype code used the **upper bound** of the range. For the
prototype's decision policy that is too aggressive: an ordinary "4 to 7 feet"
day would be scored as if the surf were a sustained 7 ft. The midpoint is a
more representative single value for the period. This is a *policy* choice,
not a NOAA convention. The function name (``parse_surf_height_midpoint_ft``)
and the engine field (``parsed_surf_height_midpoint_ft``) are deliberately
explicit that this is a representative midpoint, not a maximum.

Current / first forecast period
-------------------------------
An SRF section lists several periods (``.THIS AFTERNOON THROUGH MONDAY...``,
``.TUESDAY...``, ...), each with its own ``Surf Height`` line. **We use the
FIRST ``Surf Height`` line in the supplied text**, which corresponds to the
current / nearest forecast period -- the period relevant to a swimmer standing
on the beach now. We deliberately do NOT take the maximum across periods.
``max_surf_height_midpoint_ft`` is provided separately for callers that
explicitly want the worst-case period; the risk engine uses the first-period
value only.

The supplied text is assumed to be a single geographically filtered zone
section (as produced by ``noaa_forecast.extract_zone_section``), so "first
line" is the current period of *that* zone, not of some other geographic zone.
"""

from __future__ import annotations

import re
from typing import Optional

# Matches a single "Surf Height ... N feet" or "... N to M feet" line.
# - case-insensitive
# - tolerant of the dotted leader and variable whitespace between the label
#   and the value (``[\s.]+``)
# - accepts integer or decimal values
# - accepts "feet", "foot", or "ft"
# - the numeric value must appear immediately after the label, so a glossary
#   sentence ("Surf Height is the height of...") does not match.
_SURF_HEIGHT_RE = re.compile(
    r"surf\s+height[\s.]+"
    r"(?P<low>\d+(?:\.\d+)?)"
    r"(?:\s*to\s*(?P<high>\d+(?:\.\d+)?))?"
    r"\s*(?:feet|foot|ft)\b",
    re.IGNORECASE,
)


def _line_midpoint_ft(match: "re.Match[str]") -> Optional[float]:
    """Representative midpoint (feet) for one Surf Height match.

    For a range "N to M feet" this is (N + M) / 2. For a single "N feet" value
    the midpoint is just N.
    """
    low = match.group("low")
    high = match.group("high")
    try:
        low_val = float(low)
    except (TypeError, ValueError):
        return None
    if high is None:
        return round(low_val, 2)
    try:
        high_val = float(high)
    except (TypeError, ValueError):
        return round(low_val, 2)
    return round((low_val + high_val) / 2.0, 2)


def _iter_surf_height_midpoints_ft(forecast: str):
    """Yield the representative midpoint feet for every Surf Height line, in order."""
    if not forecast:
        return
    for match in _SURF_HEIGHT_RE.finditer(forecast):
        value = _line_midpoint_ft(match)
        if value is not None:
            yield value


def parse_surf_height_midpoint_ft(forecast: Optional[str]) -> Optional[float]:
    """Return the representative midpoint surf height (feet) of the FIRST/current
    forecast period in the supplied (geographically filtered) SRF section.

    "4 to 7 feet" -> 5.5. Returns ``None`` if the forecast is empty or contains
    no parseable ``Surf Height`` line.
    """
    if not forecast:
        return None
    for value in _iter_surf_height_midpoints_ft(forecast):
        return value
    return None


def max_surf_height_midpoint_ft(forecast: Optional[str]) -> Optional[float]:
    """Return the largest per-period representative midpoint across all periods.

    NOT used by the risk engine (which uses the first/current period via
    :func:`parse_surf_height_midpoint_ft`). Provided for callers that explicitly
    want the worst-case period across the supplied section.
    """
    if not forecast:
        return None
    values = list(_iter_surf_height_midpoints_ft(forecast))
    return max(values) if values else None
