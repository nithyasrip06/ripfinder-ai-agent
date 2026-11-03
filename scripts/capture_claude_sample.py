#!/usr/bin/env python3
"""Capture exactly ONE live Claude assessment and save the full response.

This makes ONE paid Claude call. It requires a valid ANTHROPIC_API_KEY in the
environment or a project-root .env file. If no key is present it exits without
calling Claude and without writing any file (it never fabricates a response).

The deterministic engine remains authoritative for risk_level / risk_score;
Claude only fills summary / recommendation / safety_note. The saved JSON is the
exact /v1/assess response contract plus the deterministic inspection fields.

Run from the repo root:
    python scripts/capture_claude_sample.py
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from agent.api import SOURCE_CLAUDE, SOURCE_FALLBACK, FALLBACK_SAFETY_NOTE  # noqa: E402
from agent.llm_agent import generate_safety_message  # noqa: E402
from agent.reasoning_engine import RiskInput, calculate_risk  # noqa: E402

OUT = REPO_ROOT / "results" / "sample_claude_response.json"

# Realistic San Luis Obispo current forecast (first/current period 4 to 7 feet).
FORECAST = (
    ".THIS AFTERNOON THROUGH MONDAY...\n"
    "Surf Height...................4 to 7 feet.\n"
    "Thunderstorm Potential........None expected.\n"
    "Water Temperature.............58 to 62 degrees.\n"
    "Tides.........................Low 1.2 feet 09 AM. High 4.1 feet 03 PM.\n"
)

PAYLOAD = dict(
    beach="Pismo Beach",
    rip_detected=True,
    confidence=0.55,
    detection_count=1,
    forecast=FORECAST,
)


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "Live Claude response not collected because no valid API key was "
            "available.\nSet ANTHROPIC_API_KEY (env or .env) and re-run this "
            "script. It makes exactly ONE paid Claude call."
        )
        return 1

    data = RiskInput(**PAYLOAD)
    result = calculate_risk(data)  # authoritative risk_level / risk_score

    # Mirror the /v1/assess success/fallback contract exactly.
    try:
        text = generate_safety_message(data, result)
        summary = text["summary"]
        recommendation = text["recommendation"]
        safety_note = text["safety_note"]
        source = SOURCE_CLAUDE
    except Exception as exc:  # never fabricate; record the fallback truthfully
        print(f"Claude call failed ({type(exc).__name__}); recording fallback.")
        summary = result.explanation
        recommendation = result.recommendation
        safety_note = FALLBACK_SAFETY_NOTE
        source = SOURCE_FALLBACK

    response = {
        "risk_level": result.risk_level,
        "risk_score": result.risk_score,
        "summary": summary,
        "recommendation": recommendation,
        "safety_note": safety_note,
        "assessment_source": source,
        # Deterministic inspection context (not part of the response schema).
        "_inputs": PAYLOAD,
        "_visual_contribution": result.visual_contribution,
        "_environmental_contribution": result.environmental_contribution,
        "_parsed_surf_height_midpoint_ft": result.parsed_surf_height_midpoint_ft,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(response, indent=2))
    print(f"Wrote {OUT}\n")
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
