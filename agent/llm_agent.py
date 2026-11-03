"""Claude phrasing layer.

Turns an already-computed deterministic assessment into user-facing text
(summary / recommendation / safety_note). Claude never decides or changes the
risk level or risk score -- those are passed in and treated as fixed.

Reproducibility (exact values used at runtime)
----------------------------------------------
* Model:        claude-sonnet-4-6   (Anthropic Claude Sonnet 4.6)
* SDK:          anthropic (see requirements.txt / installed version)
* max_tokens:   300
* temperature:  0.2
* timeout:      7 s, no retries (falls back to rule-engine text on failure)
* top_p:        not set (SDK default)
* Prompt file:  prompts/safety_prompt_v2.txt (v1 = longer-text version used for earlier captured samples)
These constants are exported below so the API layer and reproducibility docs
reference one source of truth.
"""

import json
import os
import re
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# --- Exact generation configuration (single source of truth) -----------------
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 300
CLAUDE_TEMPERATURE = 0.2
# Unity's request timeout is 10 s. Fail fast (no retries) so a slow Claude call
# still leaves time for the deterministic fallback to reach the headset.
CLAUDE_TIMEOUT_SECONDS = 7.0
CLAUDE_MAX_RETRIES = 0
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "safety_prompt_v2.txt"

# The three (and only three) user-facing text fields Claude is allowed to fill.
REQUIRED_FIELDS = ("summary", "recommendation", "safety_note")

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    """Lazily construct a single Anthropic client."""
    global _client
    if _client is None:
        _client = Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=CLAUDE_TIMEOUT_SECONDS,
            max_retries=CLAUDE_MAX_RETRIES,
        )
    return _client


def load_prompt() -> str:
    with open(PROMPT_PATH, "r") as file:
        return file.read()


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them anyway."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def parse_claude_json(response_text: str) -> dict:
    """Parse and validate Claude's JSON into exactly the required text fields.

    Raises ValueError on malformed JSON, missing fields, or non-string /
    empty values so the caller can fall back deterministically.
    """
    cleaned = _strip_code_fences(response_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON response from Claude: {error}")

    if not isinstance(data, dict):
        raise ValueError("Claude response was not a JSON object.")

    result = {}
    for field in REQUIRED_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Claude response is missing text field: {field!r}")
        result[field] = value.strip()
    return result


def build_user_message(risk_input, risk_output) -> str:
    """Assemble the structured, already-decided assessment for Claude.

    Reads only fields that exist on the current shipped RiskInput/RiskOutput.
    """
    surf = risk_output.parsed_surf_height_midpoint_ft
    surf_line = (
        f"{surf:.1f} ft (representative midpoint of forecast range)"
        if surf is not None
        else "not reported"
    )
    return f"""Structured rip-current risk assessment (already decided -- do not change):

Risk level: {risk_output.risk_level}
Risk score: {risk_output.risk_score}

Detector data:
Beach: {risk_input.beach}
Rip detected: {risk_input.rip_detected}
Detection confidence: {risk_input.confidence}
Detection count: {risk_input.detection_count}

Environmental data:
Parsed surf height: {surf_line}
NOAA forecast text: {risk_input.forecast or "(none provided)"}

Base explanation (from the rule engine):
{risk_output.explanation}

Base recommendation (from the rule engine):
{risk_output.recommendation}
"""


def generate_safety_message(risk_input, risk_output) -> dict:
    """Call Claude to phrase the assessment. Returns {summary, recommendation,
    safety_note}. Raises on any failure so the caller can fall back."""
    client = _get_client()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=load_prompt(),
        messages=[
            {
                "role": "user",
                "content": build_user_message(risk_input, risk_output),
            }
        ],
    )

    text_blocks = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_blocks:
        raise ValueError("Claude response contained no text content.")

    return parse_claude_json("".join(text_blocks))
