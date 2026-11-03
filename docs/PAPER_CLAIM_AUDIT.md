# Paper Claim Audit — Backend Integration

Scope: claims relevant to the `/v1/assess` backend integration only. This is
not the paper. Each claim is classified **SUPPORTED**, **PARTIALLY SUPPORTED**,
**UNSUPPORTED**, or **REQUIRES MEASUREMENT**, with the evidence in this repo.

| # | Claim | Verdict | Evidence / caveat |
|---|---|---|---|
| 1 | Forecast data contributes to the deterministic risk calculation. | **SUPPORTED** | `calculate_risk` adds an environmental contribution = max(keyword band, surf-height band) (`reasoning_engine.py`). Note: for the configured SLO/Pismo zone the keyword term is usually 0; the surf-height band is what actually contributes there. |
| 2 | Claude is part of the runtime `/v1/assess` path. | **SUPPORTED** | `api.assess()` calls `generate_safety_message()` on every request (`agent/api.py`). Previously it did not. |
| 3 | Claude generates language only. | **SUPPORTED** | Claude returns only `summary`/`recommendation`/`safety_note`; the prompt forbids emitting a risk value (`prompts/safety_prompt_v1.txt`); the API reads `risk_level`/`risk_score` only from the engine. |
| 4 | Claude cannot alter risk level or risk score. | **SUPPORTED** | Response `risk_level`/`risk_score` come from `result` regardless of Claude output; `tests/test_assessment_api.py` asserts preservation on both the success and failure paths. |
| 5 | The service has deterministic fallback behavior if Claude fails. | **SUPPORTED** | Any Claude exception → deterministic text + `assessment_source="rule_engine_fallback"` + HTTP 200 (`agent/api.py`; `test_assessment_api.py::test_claude_failure_path`). |
| 6 | No camera image is sent to this assessment backend. | **SUPPORTED** | `RiskInput` accepts only scalars/strings (`beach`, `rip_detected`, `confidence`, `detection_count`, `forecast`) — no image field anywhere in the request path. |
| 7 | No 30-frame aggregation is used by this backend. | **SUPPORTED** | The obsolete `detection_last_30_frames` dependency was removed from `llm_agent.py`; the engine performs no temporal aggregation (`detection_count` is an instantaneous count from the client). Remaining `detection_last_30_frames` references live only in the standalone WebCOOS pipeline (`rip_detector.py`, `reasoning_engine_original.py`), which is not on the `/v1/assess` path. |
| 8 | Environmental context can change the score. | **SUPPORTED** | `scripts/evaluate_risk_engine.py` summary: environment changes only the score at 8 detector points (e.g. confidence 0.55 / count 1: 0.45 → 0.60 from moderate surf). |
| 9 | Environmental context can change the categorical risk level. | **SUPPORTED** | Same evaluation: environment changes the class at 14 detector points (e.g. confidence 0.55 / count 1: MODERATE → HIGH at high surf). |
| 10 | The decision function is deterministic given identical structured inputs. | **SUPPORTED** (risk layer) | `calculate_risk` is a pure function with no randomness — identical `RiskInput` → identical `risk_level`/`risk_score`. Caveat: the Claude *text* is not deterministic (temperature 0.2); only the risk decision is. |
| 11 | The model is reproducible from logged structured inputs. | **PARTIALLY SUPPORTED** | The deterministic `risk_level`/`risk_score` are fully reproducible from the `RiskInput`. However (a) Claude text is not reproducible, and (b) this backend does not yet persist a structured per-request input/output log — only the `RIPFINDER_TIMING` line is emitted. Add structured request logging before claiming full reproducibility. |
| 12 | Latency has been characterized. | **REQUIRES MEASUREMENT** | Instrumentation (`X-RipFinder-*-Ms`, `RIPFINDER_TIMING`) and `scripts/benchmark_assessment.py` exist and were demonstrated in fallback mode (risk engine median ≈ 0.02 ms; backend total ≈ 1 ms with no live Claude). A real characterization with live Claude (the documented 5 warm-up + 30 trial run) has **not** been executed and must be run to report end-to-end latency. |
| 13 | Detector mAP / precision / recall have been characterized. | **UNSUPPORTED** | Not available from this backend repository. No training artifacts, evaluation data, or detector metrics exist here; the detector is trained and evaluated in the Unity/YOLO side, not in this backend. Do not fabricate these numbers. |

## Detector / model claims (Unity Sentis side)

Verified from `RipFinder-Unity/.../RipDetection` source and model-asset files.
Threshold values are the **code-level `SerializeField` defaults**; the Unity
scene inspector can override them, so treat these as the in-repo defaults unless
the scene value is captured on-device.

| Claim | Verdict | Evidence |
|---|---|---|
| `medium.onnx` is used | **SUPPORTED (default)** | `SentisInference/Model/medium.onnx` exists; `DetectionManager.Start()` loads it as `"YOLOv8-medium"` at startup. Nano and a dual-class model are runtime-switchable via a controller button, but Medium is the default. |
| Input size 640×640 | **SUPPORTED** | `SentisInferenceRunManager.m_inputSize = new(640, 640)`. |
| Confidence threshold 0.25 | **NOT AS STATED** | Code default is `m_scoreThreshold = 0.23f`, not 0.25 (inspector may override). |
| NMS IoU threshold 0.5 | **NOT AS STATED** | Code default is `m_iouThreshold = 0.6f`, not 0.5 (inspector may override). |
| Single-class output | **SUPPORTED (default model)** | The default `medium.onnx` pairs with `labels.txt` = `rip` (one class); `RIP_CLASS_ID = 0`. |
| `sediment_rip` class exists / multi-class | **PARTIALLY SUPPORTED** | A two-class model (`2 Types Model.onnx`) with `labels 1.txt` = `rip`, `sediment_rip` exists and is selectable as the `"YOLOv8-dual"` option — but it is **not the startup default**. The default (medium) is single-class and **cannot emit `sediment_rip`**. (`SentisYoloClasses.txt` is the unused 80-class COCO list from the Sentis sample, not a rip taxonomy.) |
| Detector mAP / precision / recall | **UNSUPPORTED** | No training artifacts, eval data, or metrics anywhere in either repository. Do not fabricate. |
| Application FPS | **DO NOT REPORT** | The HUD "Frame Rate … FPS" is `1000 / scheduled-inference-ms` (see `InferenceStatsUI.cs`), i.e. an inference-throughput reciprocal spread across frames — **not** a measured application frame rate. See `docs/HEADSET_TIMING_INSTRUCTIONS.md`. |

Note: the backend's standalone `agent/rip_detector.py` (WebCOOS research
pipeline, **not** on the `/v1/assess` path) defines `CLASS_WEIGHT =
{"rip": 1.0, "sediment_rip": 0.3}`, `INPUT_SIZE = 640`, and a frame-positivity
`DETECTION_THRESHOLD = 0.5`, and points at a `Bathy Model.onnx` that is not
present in this repo. It performs no NMS (frame-level max over anchors). This is
separate from the shipped Unity detector and should not be conflated with it.

## Notes for the paper

- Claims 1–10 are backed by code and passing tests in this repository.
- Claim 11 should be narrowed to "the deterministic risk decision is
  reproducible from logged structured inputs" unless structured request
  logging is added and the Claude phrasing is excluded from the reproducibility
  claim.
- Claim 12 must either be softened to "the backend is instrumented for latency"
  or supported by actually running `scripts/benchmark_assessment.py` against a
  live-Claude server and reporting the numbers.
- Claim 13 must be sourced from the detector/training repository, not this one.
