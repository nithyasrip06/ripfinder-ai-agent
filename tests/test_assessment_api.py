"""API tests for /v1/assess.

Both the Claude-success and Claude-failure paths are exercised with the
external Anthropic call MOCKED -- no paid/network calls happen here. The point
of these tests is the contract: the deterministic risk_level/risk_score are
always preserved, and a Claude failure degrades to a deterministic fallback
with HTTP 200 (never an unavailable assessment).
"""

import agent.api as api
from fastapi.testclient import TestClient

from agent.reasoning_engine import RiskInput, calculate_risk

client = TestClient(api.app)

PAYLOAD = {
    "beach": "Pismo Beach",
    "rip_detected": True,
    "confidence": 0.90,
    "detection_count": 2,
    "forecast": "Surf Height...................5 to 7 feet.",
}

# Deterministic ground truth for the payload above.
EXPECTED = calculate_risk(RiskInput(**PAYLOAD))


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_claude_success_path(monkeypatch):
    def fake_generate(risk_input, risk_output):
        return {
            "summary": "Elevated rip-current risk in view.",
            "recommendation": "Stay out of the water.",
            "safety_note": "Defer to lifeguards and posted warnings.",
        }

    monkeypatch.setattr(api, "generate_safety_message", fake_generate)

    resp = client.post("/v1/assess", json=PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()

    # Deterministic values preserved exactly.
    assert body["risk_level"] == EXPECTED.risk_level
    assert body["risk_score"] == EXPECTED.risk_score

    # Claude-generated text is used.
    assert body["summary"] == "Elevated rip-current risk in view."
    assert body["recommendation"] == "Stay out of the water."
    assert body["safety_note"] == "Defer to lifeguards and posted warnings."
    assert body["assessment_source"] == "claude"

    # Latency headers present.
    assert "X-RipFinder-Risk-Ms" in resp.headers
    assert "X-RipFinder-Claude-Ms" in resp.headers
    assert "X-RipFinder-Backend-Ms" in resp.headers


def test_claude_failure_path(monkeypatch):
    def boom(risk_input, risk_output):
        raise RuntimeError("simulated Claude/API failure")

    monkeypatch.setattr(api, "generate_safety_message", boom)

    resp = client.post("/v1/assess", json=PAYLOAD)

    # Endpoint still succeeds despite Claude failing.
    assert resp.status_code == 200
    body = resp.json()

    # Deterministic values preserved exactly.
    assert body["risk_level"] == EXPECTED.risk_level
    assert body["risk_score"] == EXPECTED.risk_score

    # Deterministic fallback strings returned.
    assert body["assessment_source"] == "rule_engine_fallback"
    assert body["summary"] == EXPECTED.explanation
    assert body["recommendation"] == EXPECTED.recommendation
    assert body["safety_note"] == api.FALLBACK_SAFETY_NOTE


def test_no_rip_normalizes_inputs(monkeypatch):
    # rip_detected False -> confidence/count coerced to 0 by the model validator.
    monkeypatch.setattr(
        api,
        "generate_safety_message",
        lambda ri, ro: {"summary": "s", "recommendation": "r", "safety_note": "n"},
    )
    resp = client.post(
        "/v1/assess",
        json={
            "beach": "Pismo Beach",
            "rip_detected": False,
            "confidence": 0.9,
            "detection_count": 5,
            "forecast": "",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "LOW"
    assert body["risk_score"] == 0.0
