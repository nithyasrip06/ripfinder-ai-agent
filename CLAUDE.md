# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A prototype Python backend for **RipFinder-AR**, an AR rip-current detection safety system. The real system (described in an associated research paper) is a Meta Quest 3 app built in Unity that runs YOLOv8 models via Unity Sentis for on-device rip-current detection, overlays bounding boxes/NOAA forecasts/safety posters in passthrough AR, and scrapes live NOAA surf forecast data. This repo is *not* the Unity app — it's a standalone Python prototype of the decision layer: given detection stats and a forecast string, compute a risk score and generate a safety message via Claude.

There is currently no server, no CLI arguments, and no connection to a live NOAA feed or a real Unity client — it runs once against one hardcoded sample file.

## Commands

Setup:
```bash
pip install -r requirements.txt
```

Run the demo end-to-end (loads `sample_inputs/sample_input.json`, prints the rule-based risk output and the Claude-generated safety message):
```bash
python3 agent/main.py
```

Note: must be run as a script from `agent/` context (`python3 agent/main.py`), not as `python3 -m agent.main` — the internal imports (`from reasoning_engine import ...`, `from llm_agent import ...`) are bare/script-relative, and there is no `agent/__init__.py`.

Requires `ANTHROPIC_API_KEY` set in a `.env` file at the project root (loaded via `python-dotenv` in `agent/llm_agent.py`).

There are no tests, no lint config, and no build step. `tests/test_cases.json` exists but is empty.

## Architecture

Three-file pipeline, always run in this order from `agent/main.py`:

1. **`agent/reasoning_engine.py`** — deterministic, rule-based risk scoring. `RiskInput` (pydantic) holds detection stats (`detection_confidence`, `detection_last_30_frames`, `detection_count`) plus `noaa_forecast` (a raw forecast string) and optional `location`. `calculate_risk()` does additive point-scoring across four rules (confidence tier, detection persistence over the last 30 frames, detection count, and a **substring keyword match** against the forecast text for "rip current"/"high surf"/"advisory") into a 0–1 score, bucketed into Low/Moderate/High risk. This is deliberately kept rule-based rather than delegated to the LLM, so the actual risk classification stays auditable — the LLM is only used downstream for message phrasing (see below). No range validation on inputs (e.g. `detection_confidence` isn't constrained to [0,1]).

2. **`agent/llm_agent.py`** — takes the `RiskInput`/`RiskOutput` pair, loads the system prompt from `prompts/safety_prompt_v1.txt`, builds a single f-string user message embedding all the structured data, and makes **one** `client.messages.create()` call to `claude-sonnet-4-6` (temperature 0.2, max_tokens 300) to turn it into a natural-language AR safety message. Response is expected to be raw JSON text, parsed via `parse_claude_json()` — this is the only error handling in the codebase (catches `json.JSONDecodeError` and re-raises `ValueError`; no handling for API errors, empty responses, or non-text content blocks).

3. **`prompts/safety_prompt_v1.txt`** — the active system prompt, with explicit safety guardrails (do not claim certainty, do not say the beach is safe, return only raw valid JSON, uses approved rip-current safety guidance). `prompts/safety_prompt.txt` is an empty, unused, confusingly-named dead file — don't confuse the two.

`agent/forecast_parser.py` is an empty, unreferenced stub — presumably intended for structured NOAA forecast parsing (to replace the current substring-matching approach) but never implemented.

`sample_inputs/sample_input.json` is the only input the system currently accepts; there's no way to pass real/different data without editing this file or `agent/main.py`.

---

## Planned Agentic Redesign

The section below is a **forward-looking design plan for making this backend paper-grade sophisticated** — it describes an architecture that does not exist yet in this repo. None of the files, modules, or endpoints it references have been created. Treat this as documentation of intent, not a description of current code, until each phase is actually implemented (see "Suggested build order" for the intended sequencing).

### Context
The current repo is a simple linear demo: load one hardcoded JSON file → rule-based risk score → single LLM call that phrases the result as text. It works for a quick prototype demo but doesn't read as an "AI agent," and it doesn't reflect the system described in the RipFinder-AR paper (Unity/Meta Quest 3 app running YOLOv8 detections via Sentis, live NOAA forecast scraping, automatic safety-poster overlays, continuous real-time detection streams). Since this backend will become part of the actual bigger project and be referenced in the paper, the goal is to make it genuinely more sophisticated: real tool-using agent reasoning, real NOAA data, and a real service layer the Unity app could call.

Three architectural decisions to build around:
1. **Full agentic redesign** — give Claude actual tools (Anthropic tool-use), not one canned prompt→JSON call.
2. **Real NOAA integration** — real structured forecast data, not keyword-substring matching.
3. **FastAPI service layer** — turn this into the real backend the Unity app would call (using the currently-unused `fastapi`/`uvicorn` deps), supporting a continuous-session model rather than one-shot static input.

### Target architecture

Request flow: Unity posts detections for a session → session store keeps a rolling window of recent detections → a debounce check decides whether to actually re-run the agent (an LLM call can't happen at 15–20 FPS) → if triggered, the agent runs a **multi-turn tool-use loop** (fetch forecast, pull detection history, compute risk score, pick a safety poster, judge whether to escalate) → final answer is returned as schema-constrained structured JSON → response (risk level, message, poster, escalate flag, tool trace, latency) goes back to Unity → every assessment is logged as structured JSON for the paper's evaluation section.

#### Key design decisions
- **Deterministic risk scoring is preserved, not replaced, by the agent.** `calculate_risk()` stays a pure rule-based function (this was the strongest part of the original design — auditable, not a black box). It becomes a **tool** the agent calls (`calculate_risk_score`), and the system prompt explicitly forbids the LLM from computing or adjusting a risk number itself — it must echo the tool's output verbatim. The LLM's real judgment work is elsewhere: deciding forecast/history staleness, judging *sustained* risk trends for escalation (not just one high score), reconciling conflicting signals (e.g. high visual confidence + calm forecast) in the explanation, and generating the safety message.
- **Multi-class detections** (`rip` / `sediment_rip` / `background`, matching the paper's multi-class YOLOv8 model) get per-class weights in the risk engine (`sediment_rip` weighted lower than `rip`, `background` excluded) instead of one scalar confidence field.
- **Real NOAA data**: NDBC buoy data (`ndbc.noaa.gov/data/realtime2/{station}.txt` — wave height, period, wind, no API key) + NWS active alerts (`api.weather.gov/alerts/active` — structured advisory/statement objects) replace the current `"rip current" in forecast.lower()` substring check. Fetch and parse are split into separate functions so parsing can be unit-tested against saved fixture files with no live network needed.
- **Session/temporal handling**: an in-memory rolling window per `session_id` (documented limitation: single-process, doesn't survive restart — fine for a research pilot), plus a debounce heuristic (only reassess on first detection, a plausible risk-bucket change, or after a minimum interval) so a continuous video stream doesn't trigger an LLM call every frame.
- **FastAPI service**: one primary `POST /assess` endpoint wrapping the agent loop, built so the Anthropic client and session store are app-level singletons (not reconstructed per request), and so tests can swap in a stub agent via `app.dependency_overrides` — meaning the full HTTP contract is testable with zero live LLM calls by default.
- **Observability for the paper**: structured JSON log line per assessment (per-tool timing, risk level, forecast source, prompt/model version) — this is what lets the paper report "decision-layer latency" (this backend) separately from "perception-layer latency" (the ~67ms/frame on-device YOLO number), and supports a batch-evaluation harness that replays authored detection scenarios and aggregates risk distribution / latency / escalation rate.

#### File changes (planned, not yet made)

**New:**
- `agent/forecast_parser.py` — implement the currently-empty stub: `fetch_ndbc_raw`, `fetch_nws_alerts_raw`, `parse_ndbc_text`, `parse_nws_alerts`, `get_forecast()` → `ForecastData` pydantic model (follows existing `RiskInput`/`RiskOutput` convention in `reasoning_engine.py`), with an in-memory TTL cache.
- `agent/station_config.py` — static map of pilot site names → NDBC station ID + lat/lon.
- `agent/session_store.py` — `DetectionEvent`/`SessionState` models, rolling window, debounce heuristic, lazy session eviction.
- `agent/posters.py` — safety-poster catalog + deterministic selection by risk level/class.
- `agent/tools.py` — tool JSON-schema definitions + dispatch to the above modules and `reasoning_engine.calculate_risk`.
- `agent/agent_runner.py` — the manual multi-turn tool-use loop (explicit loop over `stop_reason`, not the beta tool runner — more legible for a paper artifact); enforces a max-iteration cap with a deterministic-only fallback response.
- `agent/observability.py` — structured JSON logging to `logs/assessments.jsonl`.
- `api/main.py` (+ `api/__init__.py`) — FastAPI app: `POST /assess`, `GET /health`, `GET /sessions/{id}`; pydantic request/response schemas; Anthropic client + session store as app-state singletons.
- `prompts/agent_system_prompt_v1.txt` — new tool-use system prompt: tool descriptions + trigger conditions, the "never recompute risk_score" rule, escalation judgment guidance, the existing safety guardrails carried over near-verbatim from `safety_prompt_v1.txt`.
- `eval/run_batch_eval.py` + `sample_inputs/sample_sessions/*.jsonl` — batch harness replaying authored scenarios (calm day, high-surf advisory, sediment-only, sustained rip, borderline flicker) through the same code path as the API, aggregating latency/risk distribution/escalation rate; supports `--live` vs. mocked mode.
- `tests/test_reasoning_engine.py`, `test_forecast_parser.py` (against `fixtures/ndbc_sample.txt`, `fixtures/nws_alerts_sample.json`), `test_session_store.py`, `test_tools.py`, `test_api.py` (FastAPI `TestClient` with mocked agent dependency).
- `agent/__init__.py`, `api/__init__.py` — make these importable packages.

**Changed:**
- `agent/reasoning_engine.py` — add multi-class weighting (`CLASS_WEIGHT` constant) on top of existing additive scoring logic; keep a backward-compatible path for the old scalar-input shape.
- `agent/main.py` — becomes a thin CLI wrapper calling `agent_runner.run_assessment`, printing the tool-call trace + final message.
- `requirements.txt` — add `httpx` (for `TestClient`) and a dev-deps split (`pytest`); `fastapi`/`uvicorn`/`requests` go from unused to actually used.

**Removed:**
- `agent/llm_agent.py` — its single-shot responsibility is absorbed into `agent_runner.py` + `tools.py`; JSON-parsing try/except is superseded by schema-constrained structured output (`output_config.format`).
- `prompts/safety_prompt.txt` — empty, dead, confusingly named next to `safety_prompt_v1.txt`.
- `tests/test_cases.json` — empty, replaced by real `pytest` modules.
- `prompts/safety_prompt_v1.txt` is **kept** (not deleted) as a citable "v1 single-shot design" artifact for the paper, just no longer loaded by code.

#### Suggested build order (each phase leaves a demoable state)
0. **Safety net** — add `pytest`, write tests for *today's* `calculate_risk()`/CLI flow before refactoring anything.
1. **NOAA integration** — self-contained, highest external-dependency risk, de-risk first. Wire in as an optional structured input alongside the current string field.
2. **Multi-class detections + session store** — richer per-class risk breakdown, still CLI-demoable.
3. **Tool-use agent redesign (centerpiece)** — `tools.py`/`agent_runner.py`/new system prompt; remove `llm_agent.py`; CLI now prints a visible tool-call trace.
4. **FastAPI service layer** — `POST /assess` wrapping the agent; demo by sending a sequence of requests on one `session_id` to show debounced reassessment + escalation.
5. **Observability + batch eval harness** — produces the latency/risk-distribution/escalation-rate numbers the paper's evaluation section needs.
6. **Optional/stretch** — SQLite audit log (stdlib only) for replay/citation, minimal `/assess` auth if exposed beyond localhost, `Dockerfile` for field-test deployment.

#### Verification (once implemented)
- Phases 0–3 are verifiable by running `python -m agent.main` and inspecting the printed tool-call trace and structured output.
- Phase 1 (NOAA) is unit-testable offline via fixture files — no live network needed for routine dev/test runs.
- Phase 4 (API) is verifiable via `pytest tests/test_api.py` using FastAPI's `TestClient` with a stubbed agent dependency, plus a manual `curl` sequence of `POST /assess` calls sharing a `session_id`.
- Phase 5 is verifiable by running `python eval/run_batch_eval.py` and checking the aggregated summary output.
