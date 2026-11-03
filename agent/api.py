import logging
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from .reasoning_engine import RiskInput, calculate_risk
from .llm_agent import generate_safety_message


logger = logging.getLogger(__name__)

app = FastAPI(
    title="RipFinder AI Agent",
    version="1.0.0",
)

# assessment_source values (explicit, documented).
SOURCE_CLAUDE = "claude"
SOURCE_FALLBACK = "rule_engine_fallback"

# Deterministic fallback safety note, used when Claude phrasing is unavailable.
FALLBACK_SAFETY_NOTE = (
    "Computer vision may be incorrect. "
    "Follow official warnings and local lifeguards."
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
def assess(data: RiskInput, response: Response) -> AssessmentResponse:
    backend_start = time.perf_counter()

    # 1. Deterministic risk engine -- authoritative for risk_level/risk_score.
    risk_start = time.perf_counter()
    try:
        result = calculate_risk(data)
    except Exception as exc:  # deterministic engine itself failed -> 500
        logger.exception("Deterministic risk assessment failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to calculate the risk assessment.",
        ) from exc
    risk_ms = (time.perf_counter() - risk_start) * 1000.0

    # 2. Claude phrasing layer -- text only. Failure must NOT invalidate the
    #    deterministic assessment; we fall back and still return HTTP 200.
    claude_start = time.perf_counter()
    try:
        text = generate_safety_message(data, result)
        summary = text["summary"]
        recommendation = text["recommendation"]
        safety_note = text["safety_note"]
        assessment_source = SOURCE_CLAUDE
    except Exception as exc:
        # Do not log prompt contents or API keys -- just the failure type.
        logger.warning(
            "Claude phrasing unavailable (%s); using deterministic fallback.",
            type(exc).__name__,
        )
        summary = result.explanation
        recommendation = result.recommendation
        safety_note = FALLBACK_SAFETY_NOTE
        assessment_source = SOURCE_FALLBACK
    claude_ms = (time.perf_counter() - claude_start) * 1000.0

    backend_ms = (time.perf_counter() - backend_start) * 1000.0

    # 3. Latency instrumentation (response headers + one machine-readable line).
    response.headers["X-RipFinder-Risk-Ms"] = f"{risk_ms:.2f}"
    response.headers["X-RipFinder-Claude-Ms"] = f"{claude_ms:.2f}"
    response.headers["X-RipFinder-Backend-Ms"] = f"{backend_ms:.2f}"
    logger.info(
        "RIPFINDER_TIMING risk_ms=%.2f claude_ms=%.2f backend_ms=%.2f source=%s",
        risk_ms,
        claude_ms,
        backend_ms,
        assessment_source,
    )

    return AssessmentResponse(
        risk_level=result.risk_level,
        risk_score=result.risk_score,
        summary=summary,
        recommendation=recommendation,
        safety_note=safety_note,
        assessment_source=assessment_source,
    )
