# Quest (Headset) Timing — Collection Procedure

Purpose: collect **real** on-device timings from the RipFinder Unity/Quest app,
kept strictly separate from the backend `/v1/assess` latency in
`results/latency.csv`. Nothing here is measured yet — this is the procedure to
measure it on hardware.

> These are hardware-dependent measurements. They must be collected on a Meta
> Quest 3 running the RipFinder Unity build. Do **not** fabricate them.

---

## 0. Critical labeling correction — scheduled inference duration ≠ application FPS

The current HUD is **mislabeled**. In
`RipFinder-Unity/.../RipDetection/InferenceStatsUI.cs` and
`DetectionManager/Scripts/DetectionUiMenuManager.cs`, the displayed
"Frame Rate … FPS" is computed as:

```csharp
float fps = 1000f / inferenceTimeMs;   // reciprocal of the Sentis inference duration
```

where `inferenceTimeMs` is `lastInferenceDurationMs` from
`SentisInferenceRunManager.cs` — the wall-clock time of one **scheduled Sentis
inference**, run via `ScheduleIterable` and stepped `m_layersPerFrame = 25`
layers per Unity frame (so a single inference is spread across multiple frames).

**This reciprocal is NOT the application frame rate.**

- **Scheduled inference duration**: how long one model evaluation takes,
  wall-clock, from schedule start to completion. Because the schedule is spread
  across frames (25 layers/frame), it can span several rendered frames.
- **Application frame rate**: how many full render frames the app produces per
  second (`1f / Time.smoothDeltaTime`), driven by the whole render/passthrough
  pipeline, not by inference alone.

`1000 / inference_ms` answers "if the app did nothing but run this model
back-to-back, how many inferences/second" — it is an **inference throughput
estimate**, not FPS. For the paper, report it as **scheduled inference duration
(ms)** and, if a rate is wanted, **inferences per second**, never "application
FPS."

---

## 1. What to collect (minimum)

| # | Stage | What it is | Source |
|---|---|---|---|
| 1 | `inference` | Sentis scheduled inference duration (ms) | `SentisInferenceRunManager.lastInferenceDurationMs` (already computed) |
| 2 | `post_processing` | box decode / NMS / UI-marker build (ms) | Only if you instrument it (see §3) |
| 3 | `http_round_trip` | Unity-observed `/v1/assess` HTTP round-trip (ms) | `RipFinderAgentClient` (see §3) |
| 4 | `panel_render` *(optional)* | assessment-panel update/render (ms) | Only if you instrument it |

Stage 3 (Unity-observed HTTP round-trip) is the headset-side counterpart to the
backend's `client_round_trip_ms`; it additionally includes Wi-Fi transport from
the Quest to the backend host, so it is expected to be **larger** than the
loopback number in `results/latency.csv`. Keep them labeled separately.

---

## 2. Emit a machine-readable timing line

Log every sample as one greppable line so `adb logcat` capture is trivial:

```
RIPFINDER_TIMING, stage=inference, ms=12.34
RIPFINDER_TIMING, stage=post_processing, ms=3.10
RIPFINDER_TIMING, stage=http_round_trip, ms=48.7
```

The current code only *displays* the inference duration (via
`SetInferenceStats` / `UpdateStats`); it does not log it as a standalone
machine-readable line. Add the `Debug.Log` statements in §3.

---

## 3. Minimal Unity C# additions (apply on the Unity side; not applied here)

> Not applied in this workspace. The Unity project is present but must not be
> edited without explicit approval. Add these when you are ready to measure.

**Stage 1 — inference.** In `SentisInferenceRunManager.cs`, immediately after
`lastInferenceDurationMs` is assigned (right after the
`lastInferenceDurationMs = (inferenceEndTime - inferenceStartTime) * 1000f;`
line):

```csharp
Debug.Log($"RIPFINDER_TIMING, stage=inference, ms={lastInferenceDurationMs:0.00}");
```

**Stage 2 — post-processing.** Wrap the box-decode / UI-update call
(`DrawUIBoxes(...)` in the same file) with a stopwatch:

```csharp
var _sw = System.Diagnostics.Stopwatch.StartNew();
// ... existing DrawUIBoxes(...) / post-processing ...
_sw.Stop();
Debug.Log($"RIPFINDER_TIMING, stage=post_processing, ms={_sw.Elapsed.TotalMilliseconds:0.00}");
```

**Stage 3 — HTTP round-trip.** In `AIAgent/RipFinderAgentClient.cs`, inside the
`SendAssessment` coroutine, time only the network wait:

```csharp
var _sw = System.Diagnostics.Stopwatch.StartNew();
yield return request.SendWebRequest();
_sw.Stop();
Debug.Log($"RIPFINDER_TIMING, stage=http_round_trip, ms={_sw.Elapsed.TotalMilliseconds:0.00}");
```

**Stage 4 (optional) — panel render.** In `RipFinderAssessmentPanel` (where the
response text is applied to the UI), bracket the update with the same
stopwatch pattern and `stage=panel_render`.

These are all `Debug.Log` only — they do not change any detection, scoring, or
network behavior.

---

## 4. Capture from the Quest with adb

1. Connect the Quest over USB (or `adb connect <ip>` over Wi-Fi) and confirm:

   ```
   adb devices
   ```

2. Clear the log buffer, then capture only Unity lines to a file:

   ```
   adb logcat -c
   adb logcat -s Unity > quest_timing.log
   ```

   (`-s Unity` filters to the `Unity` tag, which is where `Debug.Log` lands.)

3. Put on the headset, point it at a beach/monitor scene, and let it run.

4. Stop capture with Ctrl-C once you have enough samples.

5. Extract the timing lines:

   ```
   grep RIPFINDER_TIMING quest_timing.log > quest_timing_filtered.log
   ```

---

## 5. How many samples, and warm-up

- **Discard warm-up.** The first model load and first few inferences are not
  representative (shader/kernel compilation, allocation, thermal ramp). Drop the
  first ~10 seconds (roughly the first 10–15 inference samples).
- **Collect ~20–30 post-warm-up samples per stage.** That is enough for a
  stable median and p95 without long thermal drift.
- Report per stage: **N, median, p95, min, max** — the same statistics and the
  same reproducible linear-interpolation percentile used for the backend in
  `scripts/benchmark_assessment.py`, so the two tables are comparable.

---

## 6. Reporting rules (so the paper stays honest)

- Report stage 1 as **scheduled inference duration (ms)** (and optionally
  inferences/second), never "application FPS."
- Keep the Unity-observed `http_round_trip` (stage 3) separate from the
  backend loopback `client_round_trip_ms`; the Quest number includes Wi-Fi
  transport to the backend host.
- If a stage was not instrumented, list it under "Outstanding Measurements",
  do not estimate it.
