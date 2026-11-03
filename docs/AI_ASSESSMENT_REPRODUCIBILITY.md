# RipFinder AI Assessment — Reproducibility Reference

This documents the `/v1/assess` decision layer **as implemented** in this
repository (branch `unity-api-integration`). All values below are taken from
the actual code, not intent.

Pipeline:

```
Unity structured input
  -> RiskInput (validation)
  -> calculate_risk()            [deterministic: risk_level + risk_score]
  -> generate_safety_message()   [Claude: summary + recommendation + safety_note]
  -> AssessmentResponse
```

The deterministic engine is authoritative for `risk_level` and `risk_score`.
Claude only phrases text and can never change either value.

---

## 1. Request schema (`RiskInput`, `agent/reasoning_engine.py`)

| Field | Type | Constraints |
|---|---|---|
| `beach` | string | length 1–200 |
| `rip_detected` | bool | — |
| `confidence` | float | 0.0–1.0 |
| `detection_count` | int | 0–100 |
| `forecast` | string | ≤ 5000 chars, default `""` |

Model validator: if `rip_detected` is false, `confidence` and `detection_count`
are coerced to 0; if `rip_detected` is true and `detection_count == 0`, the
request is rejected (HTTP 422).

## 2. Response schema (`AssessmentResponse`, `agent/api.py`)

| Field | Type |
|---|---|
| `risk_level` | `"LOW" \| "MODERATE" \| "HIGH"` |
| `risk_score` | float 0.0–1.0 |
| `summary` | string |
| `recommendation` | string |
| `safety_note` | string |
| `assessment_source` | string (`"claude"` or `"rule_engine_fallback"`) |

## 3. Deterministic score formula

```
risk_score = clamp_0_1( round(visual_contribution + environmental_contribution, 2) )
```

`visual_contribution` and `environmental_contribution` are exposed on the
engine's `RiskOutput` for inspection but do not affect the response schema.

### Decision table

Visual contribution (additive):

| Condition | Contribution |
|---|---|
| `rip_detected` is true | +0.35 |
| `confidence >= 0.85` | +0.30 |
| `0.70 <= confidence < 0.85` | +0.20 |
| `0.50 <= confidence < 0.70` | +0.10 |
| `confidence < 0.50` | +0.00 |
| `detection_count >= 3` | +0.15 |
| `detection_count == 2` | +0.10 |
| `detection_count <= 1` | +0.00 |

Environmental contribution = **max**(NWS rating or keyword band, surf-height band):

| Signal | Contribution |
|---|---|
| NWS `Rip Current Risk` line: High | 0.30 |
| NWS `Rip Current Risk` line: Moderate | 0.15 |
| NWS `Rip Current Risk` line: Low | 0.00 |
| Keyword (only if no NWS rating line): any high term* | 0.30 |
| Keyword (only if no NWS rating line): any moderate term** | 0.15 |
| Surf height **midpoint** `>= 6.0 ft` | 0.30 |
| Surf height **midpoint** `>= 4.0 ft` and `< 6.0 ft` | 0.15 |
| otherwise | 0.00 |

The surf-height value compared against these bands is the **representative
midpoint** of the forecast range for the current/first period, e.g.
`"4 to 7 feet"` → `5.5 ft` (see §7). A `"4 to 7 feet"` forecast therefore lands
in the **moderate** surf band (0.15), not the high band.

\* high terms: `high rip current risk`, `dangerous rip currents`,
`life-threatening rip currents`, `strong rip currents`
\** moderate terms: `moderate rip current risk`, `rip currents possible`,
`rip current`

The two environmental signals are combined with `max` (not sum) so they never
double-count. Using `max` preserves the original keyword behaviour whenever the
keyword band is the stronger signal.

The NWS rating is read from the first `Rip Current Risk*.....<Level>.` line
(current period). When present it replaces keyword matching, so the line itself
cannot trip the generic `rip current` keyword.

## 4. Risk-level thresholds

| Score | Level |
|---|---|
| `>= 0.70` | HIGH |
| `>= 0.35` and `< 0.70` | MODERATE |
| `< 0.35` | LOW |

**NWS floor.** The final level is never lower than the official NWS rip current
rating. If the score-based level is lower, the level is raised to the NWS
rating and the score is lifted to that level's lower edge (0.35 for MODERATE,
0.70 for HIGH). Example: no detection + NWS High → HIGH 0.70. The paper's
`results/risk_surface*.csv` uses surf-height-only forecasts, so it is
unaffected.

## 5. Detection (visual) contribution rules

See the "Visual contribution" rows in §3. Source: `_visual_contribution()` in
`agent/reasoning_engine.py`.

## 6. Environmental / surf-height contribution rules

See the "Environmental contribution" rows in §3. Source:
`_forecast_rating_contribution()`, `_forecast_keyword_contribution()` and
`_surf_height_contribution()` in
`agent/reasoning_engine.py`.

> **PROTOTYPE POLICY — not scientifically validated.** The feet thresholds
> `MODERATE_SURF_HEIGHT_FT = 4.0` and `HIGH_SURF_HEIGHT_FT = 6.0` are **prototype
> decision-policy thresholds. They are not official NOAA/NWS rip-current risk
> thresholds and have not yet been empirically calibrated.** They are isolated
> as named constants. The contribution magnitudes (0.15 / 0.30) reuse the
> engine's existing environmental magnitudes rather than inventing new ones.
> Surf height is treated as environmental *context* (the representative midpoint
> of the forecast range), not as NOAA's rip-current risk rating.

## 7. Surf-height parser behaviour (`agent/surf_height.py`)

- `parse_surf_height_midpoint_ft(forecast)` returns the **representative
  midpoint** of the surf-height range for the **first / current forecast
  period**, in feet, as a float. Examples: `"4 to 7 feet"` → `5.5`,
  `"1 to 2 feet"` → `1.5`, `"3 to 5 feet"` → `4.0`, `"4.5 to 6.5 feet"` → `5.5`.
  A single value (`"4 feet"`) returns itself (`4.0`).
- **Midpoint rule:** `(low + high) / 2` for a range; the single value otherwise.
  This replaced an earlier upper-bound rule, which was too aggressive for the
  prototype (it scored an ordinary "4 to 7 feet" day as if surf were 7 ft).
  The name makes the semantics explicit; it is a policy choice, not a NOAA
  convention.
- **Current-period selection:** the **first** `Surf Height` line in the supplied
  text is used — the current/nearest period. The parser does **not** take the
  maximum across periods. The supplied text is the geographically filtered SLO
  zone section (from `noaa_forecast.extract_zone_section`), so "first line" is
  the current period of that zone, not another geographic zone. Verified by
  `tests/test_noaa_parser.py`.
- Case-insensitive; tolerant of the NWS dotted leader and variable whitespace;
  accepts integer or decimal values; accepts `feet` / `foot` / `ft`. The numeric
  value must follow the label directly, so a glossary sentence does not match.
- Returns `None` when no surf-height line is present or the value is
  non-numeric (e.g. "Variable").
- `max_surf_height_midpoint_ft()` (worst-case period midpoint) is provided
  separately for callers that want it but is **not** used by the engine.
- The engine exposes the parsed value as `RiskOutput.parsed_surf_height_midpoint_ft`
  and the decision-surface CSV column is `parsed_surf_height_midpoint_ft`.

## 8. Claude model ID

`claude-sonnet-4-6` (`agent/llm_agent.py`, `CLAUDE_MODEL`).

## 9. Anthropic SDK version

`anthropic==0.120.0` (installed). Declared in `requirements.txt` as `anthropic`.

## 10. `max_tokens`

`300` (`agent/llm_agent.py`, `CLAUDE_MAX_TOKENS`).

## 11. Temperature / top_p

`temperature = 0.2` (`CLAUDE_TEMPERATURE`). `top_p` is not set (SDK default).
No `thinking` / `output_config` parameters are used.

## 12. Prompt path

`prompts/safety_prompt_v2.txt` (`agent/llm_agent.py`, `PROMPT_PATH`).

v2 is v1 with constraint 6 tightened to hard per-field word limits (summary
<= 20, recommendation <= 15, safety_note <= 12 words) so text fits the AR
panel. Any Claude samples captured before this change used v1, which is kept
unchanged in `prompts/safety_prompt_v1.txt`.

## 13. Prompt SHA-256

```
v2 (active): 0491511301ae019959f6efa34a304071ec829291cdb970e67b000a03f898959d
v1:          fcac073a3359200959db9843eaa0d321014a598f889123be91fb317e42c078b8
```

Recompute with: `shasum -a 256 prompts/safety_prompt_v2.txt`.

## 14. `assessment_source` values

| Value | Meaning |
|---|---|
| `claude` | Claude phrasing succeeded; `summary`/`recommendation`/`safety_note` are Claude-generated. |
| `rule_engine_fallback` | Claude phrasing failed; deterministic fallback text was used. |

## 15. Claude failure / fallback behaviour

On any Claude failure (network, auth, timeout, empty/malformed response,
missing fields), `/v1/assess`:

- keeps the deterministic `risk_level` and `risk_score`,
- sets `summary = RiskOutput.explanation`, `recommendation = RiskOutput.recommendation`,
- sets `safety_note` to the fixed fallback note
  (`"Computer vision may be incorrect. Follow official warnings and local lifeguards."`),
- sets `assessment_source = "rule_engine_fallback"`,
- returns **HTTP 200** (a Claude failure never turns a valid deterministic
  assessment into an unavailable one),
- logs a warning containing only the exception *type* (never the API key or
  prompt).

HTTP 500 is returned only if the deterministic engine itself raises.

## 16. Request cooldown

Request cooldown / confidence-change debounce is a **Unity client** concern
(`RipFinderAssessmentCoordinator` in the Unity repo). It is **not** part of this
backend and is intentionally not implemented or invented here.

## 17. Latency instrumentation

`/v1/assess` measures three durations with `time.perf_counter()` and returns
them as response headers, plus one machine-readable log line:

| Header | Measures |
|---|---|
| `X-RipFinder-Risk-Ms` | deterministic `calculate_risk()` duration |
| `X-RipFinder-Claude-Ms` | Claude generation attempt duration (time to success or to failure) |
| `X-RipFinder-Backend-Ms` | total endpoint work (excludes server startup) |

Log line: `RIPFINDER_TIMING risk_ms=... claude_ms=... backend_ms=... source=...`
(no secrets, no prompt contents).

"Client round-trip" reported by the benchmark is the **client-observed HTTP
round-trip**; it includes server processing and is not network latency alone.

## 18. Commands

Unit tests (no paid Claude calls — the Anthropic call is mocked):

```
python -m pytest -q
```

Decision-surface evaluation (writes `results/risk_surface.csv`):

```
python scripts/evaluate_risk_engine.py
```

Publication decision table (reads `results/risk_surface.csv`, writes
`results/risk_surface_paper_table.csv`):

```
python scripts/build_paper_table.py
```

One live Claude sample (requires a real `ANTHROPIC_API_KEY`; **one paid call**;
writes `results/sample_claude_response.json`):

```
python scripts/capture_claude_sample.py
```

Latency benchmark — final research run (5 warm-ups + 30 measured trials, per
case). **If the server has a real `ANTHROPIC_API_KEY`, this makes paid Claude
calls.** Start the server first, then:

```
python -m uvicorn agent.api:app --host 127.0.0.1 --port 8000
python scripts/benchmark_assessment.py --warmup 5 --runs 30 \
    --url http://127.0.0.1:8000/v1/assess \
    --output results/latency.csv --summary results/latency_summary.csv
```

With the defaults this is `(5 warmup + 30 runs) * 2 cases = 70` live Claude
calls **if** the server has a real key. To benchmark the deterministic path with
**zero paid calls**, start the server with **no** `ANTHROPIC_API_KEY` (every
request falls back; `claude_ms` then measures the immediate SDK auth-failure,
not live generation).

## 19. Result file locations

| File | Produced by | Contents |
|---|---|---|
| `results/risk_surface.csv` | `scripts/evaluate_risk_engine.py` | Full decision-surface grid (88 rows). |
| `results/risk_surface_paper_table.csv` | `scripts/build_paper_table.py` | 10 curated rows for the paper. |
| `results/latency.csv` | `scripts/benchmark_assessment.py` | Per-request latency rows. |
| `results/latency_summary.csv` | `scripts/benchmark_assessment.py` | Per-case + combined latency stats. |
| `results/sample_claude_response.json` | `scripts/capture_claude_sample.py` | One live Claude response (only if a key was available). |
