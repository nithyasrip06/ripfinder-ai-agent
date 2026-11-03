"""Deterministic policy tests for the risk engine.

Each case asserts BOTH risk_score and risk_level so the decision surface is
reproducible. These tests encode the policy as implemented -- including the
intentionally-exposed edge cases (e.g. no visual detection + strong surf is
still LOW; environmental context sometimes changes only the score, not the
class).
"""

import pytest

from agent.reasoning_engine import RiskInput, calculate_risk


def make(rip, confidence=0.0, count=0, forecast=""):
    return RiskInput(
        beach="Pismo Beach",
        rip_detected=rip,
        confidence=confidence,
        detection_count=count,
        forecast=forecast,
    )


def surf(feet_line):
    return f"Surf Height...................{feet_line}"


# 1. no rip, no forecast
def test_no_rip_no_forecast():
    out = calculate_risk(make(False))
    assert out.risk_score == 0.0
    assert out.risk_level == "LOW"


# 2. one rip, low confidence (score lands exactly on the MODERATE boundary)
def test_one_rip_low_confidence():
    out = calculate_risk(make(True, confidence=0.30, count=1))
    assert out.risk_score == 0.35
    assert out.risk_level == "MODERATE"


# 3. one rip, medium confidence
def test_one_rip_medium_confidence():
    out = calculate_risk(make(True, confidence=0.60, count=1))
    assert out.risk_score == 0.45
    assert out.risk_level == "MODERATE"


# 4. one rip, high confidence (just below HIGH)
def test_one_rip_high_confidence():
    out = calculate_risk(make(True, confidence=0.90, count=1))
    assert out.risk_score == 0.65
    assert out.risk_level == "MODERATE"


# 5. multiple detections -> HIGH
def test_multiple_detections():
    out = calculate_risk(make(True, confidence=0.90, count=3))
    assert out.risk_score == 0.80
    assert out.risk_level == "HIGH"


# 6. no rip + low surf (below the moderate surf threshold)
def test_no_rip_low_surf():
    out = calculate_risk(make(False, forecast=surf("2 feet.")))
    assert out.parsed_surf_height_midpoint_ft == 2.0
    assert out.environmental_contribution == 0.0
    assert out.risk_score == 0.0
    assert out.risk_level == "LOW"


# 7. no rip + elevated (moderate-band) surf -> environment raises score but
#    still LOW with no visual detection.
def test_no_rip_elevated_surf():
    out = calculate_risk(make(False, forecast=surf("5 feet.")))
    assert out.parsed_surf_height_midpoint_ft == 5.0
    assert out.environmental_contribution == 0.15
    assert out.risk_score == 0.15
    assert out.risk_level == "LOW"


# 7b. Intentionally exposed: no visual detection + STRONGEST environmental
#     condition is still LOW (0.30 < 0.35 MODERATE boundary).
def test_no_rip_strongest_surf_still_low():
    out = calculate_risk(make(False, forecast=surf("8 feet.")))
    assert out.parsed_surf_height_midpoint_ft == 8.0
    assert out.environmental_contribution == 0.30
    assert out.risk_score == 0.30
    assert out.risk_level == "LOW"


# 8. rip + low surf
def test_rip_low_surf():
    out = calculate_risk(make(True, confidence=0.60, count=1, forecast=surf("2 feet.")))
    assert out.risk_score == 0.45
    assert out.risk_level == "MODERATE"


# 9. same visual evidence + elevated surf -> environment changes the CLASS.
def test_same_visual_elevated_surf_changes_class():
    baseline = calculate_risk(make(True, confidence=0.60, count=1, forecast=surf("2 feet.")))
    elevated = calculate_risk(make(True, confidence=0.60, count=1, forecast=surf("6 feet.")))
    assert baseline.risk_score == 0.45 and baseline.risk_level == "MODERATE"
    assert elevated.risk_score == 0.75 and elevated.risk_level == "HIGH"


# 10. missing forecast
def test_missing_forecast():
    out = calculate_risk(make(True, confidence=0.60, count=1, forecast=""))
    assert out.environmental_contribution == 0.0
    assert out.risk_score == 0.45
    assert out.risk_level == "MODERATE"


# 11. malformed forecast -> no surf parsed, no environmental contribution
def test_malformed_forecast():
    out = calculate_risk(make(True, confidence=0.60, count=1, forecast=surf("Variable.")))
    assert out.parsed_surf_height_midpoint_ft is None
    assert out.environmental_contribution == 0.0
    assert out.risk_score == 0.45
    assert out.risk_level == "MODERATE"


# 12. benign forecast lines that must NOT alter the result
def test_benign_forecast_lines_do_not_alter_result():
    forecast = (
        "Thunderstorm Potential........None expected.\n"
        "Water Temperature.............59 to 61 degrees.\n"
        "Tides.........................Low 0.7 feet."
    )
    out = calculate_risk(make(False, forecast=forecast))
    assert out.environmental_contribution == 0.0
    assert out.risk_score == 0.0
    assert out.risk_level == "LOW"


# 13. score boundary values around LOW/MODERATE/HIGH thresholds
def test_boundary_moderate_lower_edge():
    # exactly 0.35 -> MODERATE
    out = calculate_risk(make(True, confidence=0.30, count=1))
    assert out.risk_score == 0.35 and out.risk_level == "MODERATE"


def test_boundary_just_below_moderate():
    # 0.30 -> LOW
    out = calculate_risk(make(False, forecast=surf("8 feet.")))
    assert out.risk_score == 0.30 and out.risk_level == "LOW"


def test_boundary_high_lower_edge():
    # exactly 0.70 -> HIGH  (rip 0.35 + conf>=0.70 0.20 + count>=3 0.15)
    out = calculate_risk(make(True, confidence=0.70, count=3))
    assert out.risk_score == 0.70 and out.risk_level == "HIGH"


def test_boundary_just_below_high():
    # 0.65 -> MODERATE
    out = calculate_risk(make(True, confidence=0.90, count=1))
    assert out.risk_score == 0.65 and out.risk_level == "MODERATE"


def test_score_is_clamped_to_one():
    out = calculate_risk(make(True, confidence=0.90, count=3, forecast=surf("8 feet.")))
    # visual 0.80 + env 0.30 = 1.10 -> clamped 1.0
    assert out.risk_score == 1.0 and out.risk_level == "HIGH"


# Input-model guard: rip detected but zero count is rejected.
def test_rip_with_zero_count_is_invalid():
    with pytest.raises(Exception):
        make(True, confidence=0.5, count=0)


# --- Official NWS "Rip Current Risk" rating + floor ---------------------------

def rating(level):
    return f"Rip Current Risk*.............{level}."


def test_nws_low_rating_does_not_raise_score():
    # Regression: the "Rip Current Risk" line used to trip the generic
    # "rip current" keyword (+0.15) even when the rating was Low.
    out = calculate_risk(make(False, forecast=rating("Low")))
    assert out.risk_score == 0.0 and out.risk_level == "LOW"
    assert out.nws_rip_current_risk == "LOW" and not out.nws_floor_applied


def test_nws_moderate_rating_floors_to_moderate():
    out = calculate_risk(make(False, forecast=rating("Moderate")))
    # env 0.15 -> LOW by score, raised to MODERATE at its lower edge
    assert out.risk_score == 0.35 and out.risk_level == "MODERATE"
    assert out.nws_floor_applied


def test_nws_high_rating_floors_to_high():
    out = calculate_risk(make(False, forecast=rating("High")))
    # env 0.30 -> LOW by score, raised to HIGH at its lower edge
    assert out.risk_score == 0.70 and out.risk_level == "HIGH"
    assert out.nws_floor_applied


def test_nws_high_rating_with_detection_needs_no_floor():
    out = calculate_risk(make(True, confidence=0.90, count=1, forecast=rating("High")))
    # visual 0.65 + env 0.30 = 0.95
    assert out.risk_score == 0.95 and out.risk_level == "HIGH"
    assert not out.nws_floor_applied


def test_nws_low_rating_keeps_surf_band():
    forecast = surf("6 to 8 feet.") + "\n" + rating("Low")
    out = calculate_risk(make(False, forecast=forecast))
    assert out.risk_score == 0.30 and out.risk_level == "LOW"
    assert not out.nws_floor_applied


def test_nws_rating_uses_first_period():
    forecast = (
        ".TODAY...\n" + rating("Moderate") + "\n\n"
        ".TUESDAY...\n" + rating("High")
    )
    out = calculate_risk(make(False, forecast=forecast))
    assert out.nws_rip_current_risk == "MODERATE"
    assert out.risk_score == 0.35 and out.risk_level == "MODERATE"
