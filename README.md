# RipFinder-AR (Python backend prototype)

Standalone Python prototype of the **decision layer** for RipFinder-AR, an AR
rip-current detection safety system. The full system (described in an
associated research paper) is a Meta Quest 3 app built in Unity that runs
YOLOv8 models via Unity Sentis on-device, overlays bounding boxes / NOAA
forecasts / safety posters in passthrough AR, and scrapes live NOAA surf
forecast data. This repo is not that app — it's the part of the pipeline that
turns detection stats + a surf forecast into a risk score and a
natural-language AR safety message.

There are two entry points:

- **`agent/main.py`** — the original demo: loads a hardcoded sample JSON file
  (`sample_inputs/sample_input.json`), computes a rule-based risk score, and
  generates a safety message via Claude. No network calls, no model file
  needed.
- **`agent/real_data_pipeline.py`** — the real pipeline: pulls recent still
  images from a live WebCOOS beach camera, runs a YOLOv8 ONNX model over them
  to get detection stats, fetches the matching NOAA Surf Zone Forecast for
  that camera's coastline, and feeds all of it through the same risk scoring
  + Claude messaging steps.

## Architecture

1. **`agent/reasoning_engine.py`** — deterministic, rule-based risk scoring.
   `RiskInput` (pydantic) holds detection stats (`detection_confidence`,
   `detection_last_30_frames`, `detection_count`) plus `noaa_forecast` (a raw
   forecast string) and optional `location`. `calculate_risk()` does additive
   point-scoring across four rules (confidence tier, detection persistence
   over the last 30 frames, detection count, and a substring keyword match
   against the forecast text for "rip current"/"high surf"/"advisory") into a
   0–1 score, bucketed into Low/Moderate/High risk. This is deliberately kept
   rule-based rather than delegated to the LLM, so the risk classification
   stays auditable — the LLM is only used downstream for message phrasing.

2. **`agent/llm_agent.py`** — takes the `RiskInput`/`RiskOutput` pair, loads
   the system prompt from `prompts/safety_prompt_v1.txt`, builds a single
   f-string user message embedding all the structured data, and makes one
   `client.messages.create()` call to Claude to turn it into a
   natural-language AR safety message. Response is expected to be raw JSON
   text, parsed via `parse_claude_json()`.

3. **`agent/rip_detector.py`** — loads a YOLOv8 ONNX model (`onnxruntime`) and
   runs inference over a list of frames (stills or sampled video frames),
   producing per-class scores (`rip` weighted full, `sediment_rip` weighted
   lower, `background` excluded) collapsed into the same detection stats
   shape `reasoning_engine.py` expects.

4. **`agent/webcoos_client.py`** — thin wrapper around the WebCOOS camera API
   (`pywebcoos`) for discovering cameras/products and downloading a recent
   window of still images or video for a given camera.

5. **`agent/noaa_forecast.py`** — fetches and parses the NWS Surf Zone
   Forecast (SRF) product for a given Weather Forecast Office + zone,
   extracting rip current risk / surf height / issue time, with a short-lived
   in-memory cache. `agent/station_config.py` maps each supported WebCOOS
   camera to its WFO site + zone code.

6. **`prompts/safety_prompt_v1.txt`** — the active system prompt, with
   explicit safety guardrails (do not claim certainty, do not say the beach
   is safe, return only raw valid JSON). `prompts/safety_prompt.txt` is an
   empty, unused, confusingly-named dead file — don't confuse the two.

`agent/forecast_parser.py` is an empty, unreferenced stub.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root with:

```
ANTHROPIC_API_KEY=your-anthropic-api-key
WEBCOOS_API_TOKEN=your-webcoos-api-token   # only needed for real_data_pipeline.py
```

Model files (`.onnx`) are not checked into this repo (they're large binaries
excluded via `.gitignore`). To run `real_data_pipeline.py` or
`rip_detector.py`, place the relevant YOLOv8 ONNX model(s) under `models/`
(default expected path: `models/Bathy Model.onnx`).

## Running

Demo pipeline (hardcoded sample input, no network/model required):

```bash
python3 agent/main.py
```

Real pipeline (live WebCOOS camera + live NOAA forecast + local ONNX model):

```bash
python3 agent/real_data_pipeline.py
```

Both must be run as scripts from the `agent/` context shown above (not as
`python3 -m agent.main`) — the internal imports are bare/script-relative and
there is no `agent/__init__.py`.

## Notes

- There are no tests, no lint config, and no build step. `tests/test_cases.json`
  exists but is empty.
- `data/webcoos_cache/` (downloaded camera stills/video) and `models/`
  (ONNX model weights) are gitignored — they're runtime artifacts, not source.
- See `CLAUDE.md` for a more detailed breakdown of current vs. planned
  architecture, including a forward-looking design for a full tool-using
  agent + FastAPI service layer (not yet implemented).
