"""Deterministic, auditable rip-current risk engine.

This module is the single authority for ``risk_level`` and ``risk_score``.
Claude (the phrasing layer) never computes or overrides either value.

Score model
-----------
The score is the sum of two contributions, then clamped to [0, 1]::

    risk_score = clamp( visual_contribution + environmental_contribution )

* ``visual_contribution``  -- from the on-device detector (rip flag,
  confidence tier, detection count).
* ``environmental_contribution`` -- from the NOAA forecast. It is the
  **maximum** of two independent environmental signals, so the two never
  double-count:
    - the official NWS rating from the SRF ``Rip Current Risk`` line
      (HIGH 0.30 / MODERATE 0.15 / LOW 0.0). When that line is present it
      replaces keyword matching, so the line itself cannot trip the generic
      "rip current" keyword; when absent, the original keyword match
      ("high rip current risk", "rip current", ...) is used,
    - a surf-height band parsed from the SRF ``Surf Height`` line.
  Using ``max`` preserves the original keyword floor (behaviour is unchanged
  whenever the keyword signal is the stronger of the two) and only raises the
  environmental term when surf height indicates more hazard than the keywords.

NWS floor
---------
The final ``risk_level`` is never lower than the official NWS rip current
rating. If the score-based level is lower, the level is raised to the NWS
rating and the score is lifted to that level's lower edge (0.35 / 0.70) so
score and level stay consistent.

Surf height is treated strictly as *environmental context*. It is NOT claimed
to be NOAA's rip-current risk rating -- NWS often omits an explicit rip-current
line for the SLO zone, and surf height is simply the signal that is reliably
present there.

PROTOTYPE POLICY THRESHOLDS
---------------------------
No defensible surf-height-to-score mapping exists anywhere in this repository.
The surf-height feet thresholds below are **prototype decision-policy
thresholds. They are not official NOAA/NWS rip-current risk thresholds and have
not yet been empirically calibrated.** They are isolated as named constants so
they can be reviewed and changed in one place. The contribution *magnitudes*
reuse the engine's existing environmental magnitudes (0.30 / 0.15) rather than
inventing new ones.

Surf height is parsed as the **representative midpoint** of the forecast range
(e.g. "4 to 7 feet" -> 5.5 ft), taken from the current/first forecast period of
the geographically filtered SLO section. See ``agent/surf_height.py``.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .noaa_forecast import parse_zone_section
from .surf_height import parse_surf_height_midpoint_ft

# --- Environmental contribution magnitudes (reuse existing engine values) ---
HIGH_FORECAST_CONTRIBUTION = 0.30
MODERATE_FORECAST_CONTRIBUTION = 0.15

# Surf-height contributions reuse the same magnitudes as the keyword bands.
HIGH_SURF_CONTRIBUTION = HIGH_FORECAST_CONTRIBUTION
MODERATE_SURF_CONTRIBUTION = MODERATE_FORECAST_CONTRIBUTION

# --- PROTOTYPE POLICY surf-height thresholds (feet) --------------------------
# These are prototype decision-policy thresholds. They are NOT official
# NOAA/NWS rip-current risk thresholds and have not yet been empirically
# calibrated. Provisional bands only; change here if better-supported
# thresholds become available. They are compared against the representative
# MIDPOINT of the forecast surf-height range (see agent/surf_height.py).
MODERATE_SURF_HEIGHT_FT = 4.0
HIGH_SURF_HEIGHT_FT = 6.0

# --- Risk-level boundaries (unchanged) ---------------------------------------
HIGH_RISK_THRESHOLD = 0.70
MODERATE_RISK_THRESHOLD = 0.35

HIGH_FORECAST_TERMS = (
    "high rip current risk",
    "dangerous rip currents",
    "life-threatening rip currents",
    "strong rip currents",
)

MODERATE_FORECAST_TERMS = (
    "moderate rip current risk",
    "rip currents possible",
    "rip current",
)


class RiskInput(BaseModel):
    beach: str = Field(min_length=1, max_length=200)
    rip_detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    detection_count: int = Field(ge=0, le=100)
    forecast: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_detection_values(self) -> "RiskInput":
        if not self.rip_detected:
            self.confidence = 0.0
            self.detection_count = 0
        elif self.detection_count == 0:
            raise ValueError(
                "detection_count must be greater than zero "
                "when rip_detected is true"
            )

        return self


class RiskOutput(BaseModel):
    risk_level: Literal["LOW", "MODERATE", "HIGH"]
    risk_score: float = Field(ge=0.0, le=1.0)
    explanation: str
    recommendation: str
    # Inspection fields (do not affect risk_level / risk_score contract).
    visual_contribution: float = 0.0
    environmental_contribution: float = 0.0
    parsed_surf_height_midpoint_ft: Optional[float] = None
    nws_rip_current_risk: Optional[str] = None
    nws_floor_applied: bool = False


RiskLevel = Literal["LOW", "MODERATE", "HIGH"]

LEVEL_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}

NWS_RATING_CONTRIBUTION = {
    "HIGH": HIGH_FORECAST_CONTRIBUTION,
    "MODERATE": MODERATE_FORECAST_CONTRIBUTION,
    "LOW": 0.0,
}


def _visual_contribution(data: RiskInput) -> tuple[float, list[str]]:
    """Detector-derived contribution (rip flag, confidence tier, count)."""
    score = 0.0
    reasons: list[str] = []

    if data.rip_detected:
        score += 0.35
        reasons.append("A possible rip current was detected.")

    if data.confidence >= 0.85:
        score += 0.30
        reasons.append("The detection confidence is very high.")
    elif data.confidence >= 0.70:
        score += 0.20
        reasons.append("The detection confidence is high.")
    elif data.confidence >= 0.50:
        score += 0.10
        reasons.append("The detection confidence is moderate.")

    if data.detection_count >= 3:
        score += 0.15
        reasons.append("Several possible rip-current regions were detected.")
    elif data.detection_count >= 2:
        score += 0.10
        reasons.append("Multiple possible rip-current regions were detected.")

    return round(score, 2), reasons


def _forecast_keyword_contribution(forecast: str) -> tuple[float, Optional[str]]:
    """Original substring-keyword environmental signal."""
    text = forecast.lower()
    if any(term in text for term in HIGH_FORECAST_TERMS):
        return HIGH_FORECAST_CONTRIBUTION, (
            "The official forecast reports dangerous rip-current conditions."
        )
    if any(term in text for term in MODERATE_FORECAST_TERMS):
        return MODERATE_FORECAST_CONTRIBUTION, (
            "The official forecast mentions possible rip currents."
        )
    return 0.0, None


def parse_nws_rip_current_risk(forecast: str) -> Optional[RiskLevel]:
    """Official rating from the first ``Rip Current Risk`` line, if any."""
    rating = parse_zone_section(forecast)["rip_current_risk"]
    if rating is None:
        return None
    rating = rating.upper()
    return rating if rating in LEVEL_RANK else None


def _forecast_rating_contribution(
    forecast: str,
    nws_rating: Optional[RiskLevel],
) -> tuple[float, Optional[str]]:
    """Official NWS rating band, falling back to keywords when absent."""
    if nws_rating is None:
        return _forecast_keyword_contribution(forecast)
    score = NWS_RATING_CONTRIBUTION[nws_rating]
    if score == 0.0:
        return 0.0, None
    return score, f"NWS rates the rip current risk {nws_rating}."


def _level_for_score(score: float) -> RiskLevel:
    if score >= HIGH_RISK_THRESHOLD:
        return "HIGH"
    if score >= MODERATE_RISK_THRESHOLD:
        return "MODERATE"
    return "LOW"


LEVEL_LOWER_EDGE = {
    "LOW": 0.0,
    "MODERATE": MODERATE_RISK_THRESHOLD,
    "HIGH": HIGH_RISK_THRESHOLD,
}

LEVEL_RECOMMENDATION = {
    "HIGH": "Stay out of the water and follow lifeguard instructions.",
    "MODERATE": (
        "Use caution, swim near a lifeguard, "
        "and review local warnings."
    ),
    "LOW": (
        "Remain cautious and continue following "
        "official beach guidance."
    ),
}


def _surf_height_contribution(
    surf_ft: Optional[float],
) -> tuple[float, Optional[str]]:
    """Surf-height band contribution (prototype policy thresholds).

    ``surf_ft`` is the representative midpoint of the forecast range.
    """
    if surf_ft is None:
        return 0.0, None
    if surf_ft >= HIGH_SURF_HEIGHT_FT:
        return HIGH_SURF_CONTRIBUTION, (
            f"The forecast surf height is high ({surf_ft:.1f} ft)."
        )
    if surf_ft >= MODERATE_SURF_HEIGHT_FT:
        return MODERATE_SURF_CONTRIBUTION, (
            f"The forecast surf height is elevated ({surf_ft:.1f} ft)."
        )
    return 0.0, None


def calculate_risk(data: RiskInput) -> RiskOutput:
    visual_score, reasons = _visual_contribution(data)

    # Environmental signal = max(keyword band, surf-height band).
    surf_ft = parse_surf_height_midpoint_ft(data.forecast)
    nws_rating = parse_nws_rip_current_risk(data.forecast)
    keyword_score, keyword_reason = _forecast_rating_contribution(
        data.forecast, nws_rating
    )
    surf_score, surf_reason = _surf_height_contribution(surf_ft)

    if surf_score > keyword_score:
        environmental_score = surf_score
        environmental_reason = surf_reason
    else:
        environmental_score = keyword_score
        environmental_reason = keyword_reason

    if environmental_reason:
        reasons.append(environmental_reason)

    score = min(round(visual_score + environmental_score, 2), 1.0)
    level = _level_for_score(score)

    # NWS floor: never report a lower level than the official rating.
    floor_applied = False
    if nws_rating is not None and LEVEL_RANK[nws_rating] > LEVEL_RANK[level]:
        level = nws_rating
        score = max(score, LEVEL_LOWER_EDGE[nws_rating])
        floor_applied = True
        reasons.append(
            "Risk level raised to match the official NWS rip current risk."
        )

    recommendation = LEVEL_RECOMMENDATION[level]

    explanation = (
        " ".join(reasons)
        if reasons
        else "No strong rip-current indicators were received."
    )

    return RiskOutput(
        risk_level=level,
        risk_score=score,
        explanation=explanation,
        recommendation=recommendation,
        visual_contribution=round(visual_score, 2),
        environmental_contribution=round(environmental_score, 2),
        parsed_surf_height_midpoint_ft=surf_ft,
        nws_rip_current_risk=nws_rating,
        nws_floor_applied=floor_applied,
    )
