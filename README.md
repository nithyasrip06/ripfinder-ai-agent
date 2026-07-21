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

```
ripfinder-ai-agent/
├── agent/
│   ├── main.py                # demo entry point (sample JSON -> risk -> Claude message)
│   ├── real_data_pipeline.py  # real entry point (WebCOOS + NOAA + ONNX -> risk -> Claude message)
│   ├── reasoning_engine.py    # rule-based risk scoring (RiskInput -> RiskOutput)
│   ├── llm_agent.py           # single-shot Claude call that phrases the safety message
│   ├── rip_detector.py        # YOLOv8 ONNX inference over camera frames
│   ├── webcoos_client.py      # WebCOOS camera API wrapper (discovery + download)
│   ├── noaa_forecast.py       # NWS Surf Zone Forecast fetch + parse (+ cache)
│   └── station_config.py      # camera name -> (WFO site, zone) map
├── prompts/
│   └── safety_prompt_v1.txt   # active system prompt (used by llm_agent.py)
├── sample_inputs/
│   └── sample_input.json      # hardcoded input for agent/main.py
├── models/                    # gitignored — place .onnx model weights here
├── data/webcoos_cache/        # gitignored — downloaded camera stills/video land here
└── requirements.txt
```

Data flow for both entry points converges on the same two steps:

```
detection stats + forecast text
        │
        ▼
reasoning_engine.calculate_risk()   (deterministic, auditable)
        │
        ▼
llm_agent.generate_safety_message()  (Claude call, phrasing only)
        │
        ▼
   risk output + safety message (JSON)
```

`agent/main.py` sources the top of that pipeline from
`sample_inputs/sample_input.json`; `agent/real_data_pipeline.py` sources it
from `webcoos_client.py` (camera stills) → `rip_detector.py` (ONNX detection
stats) + `noaa_forecast.py`/`station_config.py` (live NOAA forecast).

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

- There are no tests, no lint config, and no build step.
- `data/webcoos_cache/` (downloaded camera stills/video) and `models/`
  (ONNX model weights) are gitignored — they're runtime artifacts, not source.
- See `CLAUDE.md` for a more detailed breakdown of current vs. planned
  architecture, including a forward-looking design for a full tool-using
  agent + FastAPI service layer (not yet implemented).
