# RipFinder — Paper Data Summary (factual results)

Branch `unity-api-integration`. Every value below is taken from the code and
from freshly regenerated artifacts in this `results/` directory. No values are
speculative. Where a measurement was not collected, it is listed under
"Outstanding Measurements" rather than estimated.

---

## Deterministic Risk Policy

`risk_score = clamp_0_1( round( visual_contribution + environmental_contribution, 2 ) )`

The deterministic engine (`agent/reasoning_engine.py`) is authoritative for
`risk_level` and `risk_score`. Claude never computes or changes either.

**Visual contribution (additive):**

| Condition | + |
|---|---|
| `rip_detected` true | 0.35 |
| `confidence >= 0.85` | 0.30 |
| `0.70 <= confidence < 0.85` | 0.20 |
| `0.50 <= confidence < 0.70` | 0.10 |
| `confidence < 0.50` | 0.00 |
| `detection_count >= 3` | 0.15 |
| `detection_count == 2` | 0.10 |
| `detection_count <= 1` | 0.00 |

**Environmental contribution = max(keyword band, surf-height band):**

| Signal | value |
|---|---|
| keyword high term | 0.30 |
| keyword moderate term | 0.15 |
| surf-height midpoint `>= 6.0 ft` | 0.30 |
| surf-height midpoint `>= 4.0 ft` and `< 6.0 ft` | 0.15 |
| otherwise | 0.00 |

The two environmental signals are combined with `max` (never summed), so they
cannot double-count.

**Class thresholds:** `>= 0.70` HIGH; `>= 0.35` MODERATE; `< 0.35` LOW.

**Prototype-policy caveat:** `MODERATE_SURF_HEIGHT_FT = 4.0` and
`HIGH_SURF_HEIGHT_FT = 6.0` are **prototype decision-policy thresholds. They are
not official NOAA/NWS rip-current risk thresholds and have not been empirically
calibrated.** The magnitudes (0.15 / 0.30) reuse the engine's existing
environmental magnitudes. Surf height is environmental *context*, not a NOAA
rip-current rating.

**Input validation:** if `rip_detected` is false, `confidence` and
`detection_count` are coerced to 0; if `rip_detected` is true with
`detection_count == 0`, the request is rejected (HTTP 422).

---

## Forecast Parsing

Parser: `agent/surf_height.py::parse_surf_height_midpoint_ft`.

- **Value = representative midpoint of the range.** `"4 to 7 feet"` → `5.5`;
  `"1 to 2 feet"` → `1.5`; `"3 to 5 feet"` → `4.0`; `"4.5 to 6.5 feet"` → `5.5`;
  single `"4 feet"` → `4.0`. (Replaces an earlier upper-bound rule.)
- **Current-period selection:** the FIRST `Surf Height` line of the supplied,
  geographically filtered San Luis Obispo section is used. The parser does not
  take the maximum across periods and does not read another geographic zone.
- Returns `None` for empty/absent/non-numeric ("Variable") surf lines and for
  glossary sentences (a number must immediately follow the label).
- Regression coverage: `tests/test_noaa_parser.py` uses a realistic multi-zone,
  multi-period LOX SRF product and confirms: current period `4 to 7 feet` →
  `5.5` (not Tuesday's `3 to 5` → `4.0`, not the LA zone's `1 to 2` → `1.5`);
  the shared "San Luis Obispo County Beaches / Santa Barbara Central Coast
  Beaches-" heading is handled; `None` when the surf line is absent.

Paper-usable statement: *"The parser uses the first/current forecast period of
the geographically filtered San Luis Obispo section and reports the midpoint of
that period's surf-height range."*

---

## Decision-Surface Evaluation

Source: `scripts/evaluate_risk_engine.py` → `results/risk_surface.csv`
(regenerated with the real engine).

- **Total evaluated cases: 88.**
- **Class distribution: LOW 4, MODERATE 42, HIGH 42.**
- Observed score ranges: LOW `0.00–0.30`, MODERATE `0.35–0.65`, HIGH `0.70–1.00`.
- Holding detector inputs fixed and varying the forecast environment:
  - environment changes the **score only** at **8** detector points;
  - environment changes the **class** at **14** detector points.
- The decision surface is **monotonic** in surf band: raising the surf band
  never lowers the score (0 non-monotonic detector points).
- `low_surf` (midpoint 1.5 ft, below the 4.0 ft band) is identical to
  `missing_forecast` at every detector point — a sub-4 ft forecast adds nothing.

**Edge case — no detection + strongest environment (research finding, preserved):**

```
rip_detected=false, confidence=0, detection_count=0, high_surf (midpoint 7.0 ft)
-> visual 0.00 + environmental 0.30 = score 0.30 -> LOW
```

With no visual detection the maximum reachable score is 0.30 (< 0.35), so
**no-detection cases are always LOW regardless of surf.**

**Typical case (rip=True, confidence=0.55, detection_count=1):**

| Environment | surf midpoint | visual | env | score | level |
|---|---|---|---|---|---|
| missing forecast | – | 0.45 | 0.00 | 0.45 | MODERATE |
| low surf (1 to 2 ft) | 1.5 | 0.45 | 0.00 | 0.45 | MODERATE |
| moderate surf (4 to 7 ft) | 5.5 | 0.45 | 0.15 | 0.60 | MODERATE |
| high surf (6 to 8 ft) | 7.0 | 0.45 | 0.30 | 0.75 | HIGH |

Here environment raises the **score** (moderate surf) and, at high surf, flips
the **class** MODERATE→HIGH.

**Effect of the midpoint policy (upper-bound → midpoint) on an ordinary "4 to 7
feet" forecast:** its environmental contribution drops from 0.30 (upper bound
7.0 ≥ 6.0, high band) to 0.15 (midpoint 5.5, moderate band). Across the
rip-detected detector grid this demotes **6 of 21** grid points from HIGH to
MODERATE (e.g. conf 0.55 / count 1: 0.75 HIGH → 0.60 MODERATE). No-detection
rows stay LOW either way. So the midpoint policy specifically prevents ordinary
4-to-7 ft surf from producing a HIGH class on its own.

Curated 10-row paper table: `results/risk_surface_paper_table.csv`
(via `scripts/build_paper_table.py`).

---

## Claude Configuration

Source: `agent/llm_agent.py`, `agent/api.py`, `prompts/safety_prompt_v1.txt`.

| Item | Value |
|---|---|
| Model ID | `claude-sonnet-4-6` |
| Anthropic SDK | `anthropic==0.120.0` (installed) |
| `max_tokens` | 300 |
| `temperature` | 0.2 |
| `top_p` | not set (SDK default) |
| System prompt path | `prompts/safety_prompt_v1.txt` |
| System prompt SHA-256 | `fcac073a3359200959db9843eaa0d321014a598f889123be91fb317e42c078b8` |
| User message template | `agent/llm_agent.py::build_user_message` (structured, already-decided values) |
| `assessment_source` success | `claude` |
| `assessment_source` fallback | `rule_engine_fallback` |

Claude may only generate `summary`, `recommendation`, `safety_note`. It cannot
alter `risk_level` or `risk_score` (asserted on both success and failure paths
in `tests/test_assessment_api.py`). On any Claude failure the endpoint returns
HTTP 200 with deterministic fallback text and `assessment_source =
rule_engine_fallback`.

---

## Live Claude Example

**Not collected.** No valid `ANTHROPIC_API_KEY` was available in the environment
or a `.env` file at data-collection time. No response was fabricated.

To collect one live sample (one paid call) after providing a key:

```
python scripts/capture_claude_sample.py   # writes results/sample_claude_response.json
```

---

## Backend Latency

Source: `scripts/benchmark_assessment.py` → `results/latency.csv`,
`results/latency_summary.csv`.

**Mode: deterministic fallback path, zero paid Claude calls.** The server was
run with no `ANTHROPIC_API_KEY`, so every request fell back
(`assessment_source = rule_engine_fallback`, 60/60 rows). All timers below are
real, but **`claude_ms` here is the time for the Anthropic SDK to raise an
auth-failure, NOT live Claude generation.** Live end-to-end Claude latency is
not yet measured.

Runs: 5 warm-ups + 30 measured trials per case; 2 cases; 100% success (HTTP 200).
Percentiles use a reproducible linear-interpolation implementation.

**Combined (N=60), milliseconds:**

| Timer | median | p95 | min | max |
|---|---|---|---|---|
| `risk_ms` (deterministic engine) | 0.03 | 0.05 | 0.01 | 0.07 |
| `claude_ms` (fallback: SDK auth-failure, not live) | 1.075 | 1.52 | 0.56 | 1.78 |
| `backend_ms` (total endpoint work) | 1.10 | 1.551 | 0.57 | 1.83 |
| `client_round_trip_ms` (client-observed HTTP round-trip) | 2.993 | 4.481 | 1.511 | 4.785 |

Per-case values are in `results/latency_summary.csv`. `client_round_trip_ms` is
the client-observed HTTP round-trip (transport + serialization + server
processing over loopback); it is **not** network latency alone.

Takeaway available now: the deterministic engine is ~0.03 ms; total backend
work on the fallback path is ~1.1 ms median. The dominant end-to-end cost on a
**live** path will be Claude generation, which remains to be measured.

---

## Outstanding Measurements

Not collected in this pass; require a key or hardware. Do not report these as
results until measured.

- **Live Claude latency** (`claude_ms` on the real generation path) and the
  live end-to-end `client_round_trip_ms`. Needs a valid `ANTHROPIC_API_KEY`;
  `(5+30)*2 = 70` paid calls with the documented parameters.
- **One live Claude sample** (`results/sample_claude_response.json`). Same key
  requirement; one paid call.
- **Quest / headset timings** — Sentis scheduled inference duration,
  post-processing duration, Unity-observed HTTP round-trip, optional panel
  render. Procedure in `docs/HEADSET_TIMING_INSTRUCTIONS.md`. Hardware-only.
- **Detector metrics** — mAP / precision / recall. No training or evaluation
  artifacts exist in either repository.
- **On-device threshold confirmation** — the Unity Sentis code defaults are
  `scoreThreshold = 0.23`, `iouThreshold = 0.6` (not 0.25 / 0.5); the Unity
  scene inspector may override these, so the effective on-device values should
  be confirmed from the built scene or a device log.
