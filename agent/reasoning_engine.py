from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


def calculate_risk(data: RiskInput) -> RiskOutput:
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
        reasons.append(
            "Several possible rip-current regions were detected."
        )
    elif data.detection_count >= 2:
        score += 0.10
        reasons.append(
            "Multiple possible rip-current regions were detected."
        )

    forecast = data.forecast.lower()

    high_forecast_terms = (
        "high rip current risk",
        "dangerous rip currents",
        "life-threatening rip currents",
        "strong rip currents",
    )

    moderate_forecast_terms = (
        "moderate rip current risk",
        "rip currents possible",
        "rip current",
    )

    if any(term in forecast for term in high_forecast_terms):
        score += 0.30
        reasons.append(
            "The official forecast reports dangerous "
            "rip-current conditions."
        )
    elif any(term in forecast for term in moderate_forecast_terms):
        score += 0.15
        reasons.append(
            "The official forecast mentions possible rip currents."
        )

    score = min(round(score, 2), 1.0)

    if score >= 0.70:
        level = "HIGH"
        recommendation = (
            "Stay out of the water and follow lifeguard instructions."
        )
    elif score >= 0.35:
        level = "MODERATE"
        recommendation = (
            "Use caution, swim near a lifeguard, "
            "and review local warnings."
        )
    else:
        level = "LOW"
        recommendation = (
            "Remain cautious and continue following "
            "official beach guidance."
        )

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
    )