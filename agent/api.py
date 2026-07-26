import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .reasoning_engine import RiskInput, calculate_risk


logger = logging.getLogger(__name__)

app = FastAPI(
    title="RipFinder AI Agent",
    version="1.0.0",
)


class AssessmentResponse(BaseModel):
    risk_level: Literal["LOW", "MODERATE", "HIGH"]
    risk_score: float = Field(ge=0.0, le=1.0)
    summary: str
    recommendation: str
    safety_note: str
    assessment_source: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/assess",
    response_model=AssessmentResponse,
)
def assess(data: RiskInput) -> AssessmentResponse:
    try:
        result = calculate_risk(data)

        return AssessmentResponse(
            risk_level=result.risk_level,
            risk_score=result.risk_score,
            summary=result.explanation,
            recommendation=result.recommendation,
            safety_note=(
                "Computer vision may be incorrect. "
                "Follow official warnings and local lifeguards."
            ),
            assessment_source="rule_engine",
        )
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Risk assessment failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to calculate the risk assessment.",
        ) from exc