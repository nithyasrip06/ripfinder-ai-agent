import os
import json
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

def load_prompt() -> str:
    project_root = Path(__file__).resolve().parent.parent
    prompt_path = project_root / "prompts" / "safety_prompt_v1.txt"
    with open(prompt_path, "r") as file:
        return file.read()

def parse_claude_json(response_text: str) -> dict:
    try: return json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON response from Claude: {error}")

def generate_safety_message(risk_input, risk_output):
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_prompt()
    user_message = f"""
Structured rip-current risk assessment:

Risk level: {risk_output.risk_level}
Risk score: {risk_output.risk_score}

Computer vision data:
Detection confidence: {risk_input.detection_confidence}
Detections in last 30 frames: {risk_input.detection_last_30_frames}
Detection count: {risk_input.detection_count}

Environmental forecast:
Location: {risk_input.location}
NOAA forecast: {risk_input.noaa_forecast}

Base explanation:
{risk_output.explanation}

Base recommendation:
{risk_output.recommendation}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        temperature=0.2,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    response_text = response.content[0].text
    return parse_claude_json(response_text) or {}