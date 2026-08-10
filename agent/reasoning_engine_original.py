from pydantic import BaseModel
from typing import Optional

class RiskInput(BaseModel):
    detection_confidence: float
    detection_last_30_frames: int
    detection_count: int
    noaa_forecast: str
    location: Optional[str] = None

class RiskOutput(BaseModel):
    risk_level: str
    risk_score: float
    explanation: str
    recommendation: str

def calculate_risk(data: RiskInput) -> RiskOutput:
    score = 0.0

    # rule 1: detection confidence
    if data.detection_confidence >= 0.75:
        score += 0.40
    elif data.detection_confidence >= 0.50:
        score += 0.25

    # rule 2: detection last 30 frames
    if data.detection_last_30_frames >= 20:
        score += 0.25
    elif data.detection_last_30_frames >= 10:
        score += 0.15

    # rule 3: detection count
    if data.detection_count >= 2:
        score += 0.15

    # rule 4: noaa forecast
    forecast = data.noaa_forecast.lower()
    if ("rip current" in forecast or "high surf" in forecast or "advisory" in forecast):
        score += 0.20

    # convert score to risk level
    if score >= 0.70:
        risk_level = "High"
    elif score >= 0.40:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    # return risk output
    return RiskOutput(
        risk_level=risk_level,
        risk_score=round(score, 2),
        explanation=(
                f"The system classified the current situation as "
                f"{risk_level} risk based on visual detections "
                f"and surf forecast conditions."
            ),
        recommendation=(
            "Avoid entering the water in this area and follow "
            "official lifeguard or NOAA guidance."
            if risk_level == "High"
            else "Use caution and continue monitoring surf "
                "conditions before entering the water."
        )
    )