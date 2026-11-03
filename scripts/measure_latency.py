#!/usr/bin/env python3
"""Server-side latency measurement for POST /v1/assess (paper artifact).

Measures three conditions, 33 trials each (first 3 discarded as warm-up ->
N=30), ~1s between trials, against a locally started FastAPI service:

  A) positive, LIVE generation:   rip_detected=1, confidence=0.55, count=1
  B) negative, LIVE generation:   rip_detected=0, confidence=0.0,  count=0
  C) positive, FORCED fallback:   same input as A, but the service is run with
     NO api key so the real generation-failure path fires (deterministic
     fallback). This uses the code's real failure path -- nothing is mocked
     inside the service.

Per trial we record: wall-clock round trip (T_rt), the two server timing
headers (T_risk = X-RipFinder-Risk-Ms, T_gen = X-RipFinder-Claude-Ms),
provenance (assessment_source), and HTTP status.

INTEGRITY (any violation HARD-FAILS the whole run, writes no output):
  * any trial in A or B whose provenance is fallback  -> fail
  * any trial in C whose provenance is model-generated -> fail
  * any non-200                                        -> fail
Live-generation results (A, B) and fallback results (C) are never mixed.

Outputs (only on a fully successful run):
  results/latency_raw.csv     -- every trial, with a warm-up flag
  results/latency_table.tex   -- booktabs table (median & p95, ms)

The live conditions require a valid ANTHROPIC_API_KEY in the environment; each
A/B trial is a paid Claude call ((warmup+measured) * 2 = 66 by default). C makes
zero paid calls. Pass --yes to actually send the live calls.
"""

import argparse
import csv
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FORECAST = REPO_ROOT / "sample_inputs" / "forecast_slo_fixture.txt"

# (label, rip_detected, confidence, detection_count, expected_source, live)
CONDITIONS = [
    ("A", "positive, live generation", True, 0.55, 1, "claude", True),
    ("B", "negative, live generation", False, 0.0, 0, "claude", True),
    ("C", "positive, forced fallback", True, 0.55, 1, "rule_engine_fallback", False),
]

RISK_HEADER = "X-RipFinder-Risk-Ms"
GEN_HEADER = "X-RipFinder-Claude-Ms"


class HardFail(RuntimeError):
    """Raised on any integrity violation; aborts the run without writing output."""


# --------------------------------------------------------------------------- #
# statistics (reproducible linear-interpolation percentile)
# --------------------------------------------------------------------------- #
def percentile(values, p):
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def median(values):
    return percentile(values, 50)


# --------------------------------------------------------------------------- #
# environment / metadata
# --------------------------------------------------------------------------- #
def detect_client_hardware():
    bits = [platform.system(), platform.release(), platform.machine()]
    try:
        cpu = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
        if cpu:
            bits.append(cpu)
    except Exception:
        proc = platform.processor()
        if proc:
            bits.append(proc)
    return " / ".join(b for b in bits if b)


# --------------------------------------------------------------------------- #
# service lifecycle
# --------------------------------------------------------------------------- #
def start_service(port, with_key):
    """Start a uvicorn instance. with_key=True passes ANTHROPIC_API_KEY through;
    with_key=False strips it so the real absent-key failure path fires."""
    env = dict(os.environ)
    if with_key:
        if not env.get("ANTHROPIC_API_KEY", "").strip():
            raise HardFail(
                "Live service requested but ANTHROPIC_API_KEY is empty."
            )
    else:
        env.pop("ANTHROPIC_API_KEY", None)  # force the real fallback path
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "agent.api:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc


def wait_healthy(port, timeout=30.0):
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise HardFail(f"Service on port {port} did not become healthy in {timeout}s.")


# --------------------------------------------------------------------------- #
# trials
# --------------------------------------------------------------------------- #
def build_payload(beach, rip, conf, count, forecast):
    return {
        "beach": beach,
        "rip_detected": rip,
        "confidence": conf,
        "detection_count": count,
        "forecast": forecast,
    }


def _header_float(resp, name):
    try:
        return float(resp.headers.get(name))
    except (TypeError, ValueError):
        return None


def run_condition(label, desc, url, payload, expected_source, trials, warmup,
                  sleep_s, timeout):
    rows = []
    for i in range(trials):
        is_warmup = i < warmup
        start = time.perf_counter()
        resp = requests.post(url, json=payload, timeout=timeout)
        t_rt_ms = (time.perf_counter() - start) * 1000.0

        status = resp.status_code
        provenance = None
        if resp.headers.get("content-type", "").startswith("application/json"):
            provenance = resp.json().get("assessment_source")

        # ---- integrity: hard-fail immediately, before writing anything ----
        if status != 200:
            raise HardFail(
                f"[{label}] trial {i}: HTTP {status} (expected 200). Body: "
                f"{resp.text[:300]}"
            )
        if provenance != expected_source:
            hint = ""
            if expected_source == "claude" and provenance == "rule_engine_fallback":
                hint = (" -- live generation did not occur; is ANTHROPIC_API_KEY "
                        "valid? Refusing to report fallback numbers as live.")
            if expected_source == "rule_engine_fallback" and provenance == "claude":
                hint = " -- the 'forced fallback' service unexpectedly reached Claude."
            raise HardFail(
                f"[{label}] trial {i}: provenance='{provenance}' but expected "
                f"'{expected_source}'{hint}"
            )

        rows.append({
            "condition": label,
            "trial_index": i,
            "warmup": is_warmup,
            "http_status": status,
            "provenance": provenance,
            "t_rt_ms": round(t_rt_ms, 3),
            "t_risk_ms": _header_float(resp, RISK_HEADER),
            "t_gen_ms": _header_float(resp, GEN_HEADER),
        })
        tag = "warmup " if is_warmup else "measure"
        print(f"  [{label}] {tag} {i + 1:2d}/{trials}  "
              f"rt={t_rt_ms:7.2f}ms  risk={rows[-1]['t_risk_ms']}  "
              f"gen={rows[-1]['t_gen_ms']}  src={provenance}")
        if i < trials - 1:
            time.sleep(sleep_s)
    return rows


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def write_raw_csv(all_rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "condition", "trial_index", "warmup", "http_status", "provenance",
            "t_rt_ms", "t_risk_ms", "t_gen_ms",
        ])
        w.writeheader()
        w.writerows(all_rows)


def _measured(rows, label, metric):
    return [r[metric] for r in rows
            if r["condition"] == label and not r["warmup"]
            and isinstance(r[metric], (int, float))]


def summarize(all_rows):
    """Return {label: {metric: (median, p95)}} over measured (non-warmup) trials."""
    out = {}
    for label, *_ in CONDITIONS:
        out[label] = {}
        for metric in ("t_rt_ms", "t_risk_ms", "t_gen_ms"):
            vals = _measured(all_rows, label, metric)
            out[label][metric] = (median(vals), percentile(vals, 95)) if vals else (None, None)
    return out


def write_tex(summary, path, n_measured, n_warmup, client_hw, network_note):
    def cell(v):
        return f"{v:.1f}" if isinstance(v, (int, float)) else "--"

    def row(label, desc):
        s = summary[label]
        return (
            f"{label}: {desc} & "
            f"{cell(s['t_rt_ms'][0])} & {cell(s['t_rt_ms'][1])} & "
            f"{cell(s['t_risk_ms'][0])} & {cell(s['t_risk_ms'][1])} & "
            f"{cell(s['t_gen_ms'][0])} & {cell(s['t_gen_ms'][1])} \\\\"
        )

    caption = (
        f"End-to-end and server-side latency for POST /v1/assess. "
        f"$N={n_measured}$ per condition after {n_warmup} discarded warm-up "
        f"trials. Conditions A and B use live Claude generation; condition C "
        f"forces the deterministic fallback path (service run with no API key). "
        f"$T_{{rt}}$ is the client-observed HTTP round trip; $T_{{risk}}$ and "
        f"$T_{{gen}}$ are the server-reported rule-evaluation and "
        f"generation-attempt times. For condition C, $T_{{gen}}$ is the "
        f"fallback substitution time (Claude not successfully called), not "
        f"generation time. Client: {client_hw}. Network: {network_note}."
    )

    tex = f"""% Generated by scripts/measure_latency.py -- do not edit by hand.
\\begin{{table}}
  \\centering
  \\caption{{{caption}}}
  \\label{{tab:latency}}
  \\begin{{tabular}}{{lrrrrrr}}
    \\toprule
    & \\multicolumn{{2}}{{c}}{{$T_{{rt}}$ (ms)}}
    & \\multicolumn{{2}}{{c}}{{$T_{{risk}}$ (ms)}}
    & \\multicolumn{{2}}{{c}}{{$T_{{gen}}$ (ms)}} \\\\
    \\cmidrule(lr){{2-3}} \\cmidrule(lr){{4-5}} \\cmidrule(lr){{6-7}}
    Condition & median & p95 & median & p95 & median & p95 \\\\
    \\midrule
    {row('A', 'positive, live gen')}
    {row('B', 'negative, live gen')}
    {row('C', 'positive, fallback')}
    \\bottomrule
  \\end{{tabular}}
\\end{{table}}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex)


def print_summary(summary, n_measured):
    print(f"\n=== SUMMARY (median / p95 ms, N={n_measured} measured per condition) ===")
    hdr = f"{'cond':<6}{'T_rt med':>10}{'T_rt p95':>10}{'T_risk med':>12}{'T_risk p95':>12}{'T_gen med':>11}{'T_gen p95':>11}"
    print(hdr)
    for label, desc, *_ in CONDITIONS:
        s = summary[label]
        def c(v): return f"{v:.2f}" if isinstance(v, (int, float)) else "--"
        print(f"{label:<6}{c(s['t_rt_ms'][0]):>10}{c(s['t_rt_ms'][1]):>10}"
              f"{c(s['t_risk_ms'][0]):>12}{c(s['t_risk_ms'][1]):>12}"
              f"{c(s['t_gen_ms'][0]):>11}{c(s['t_gen_ms'][1]):>11}")
    print("(condition C T_gen = fallback substitution time, not generation.)")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--network-note", required=True,
                    help='e.g. "desktop client, same LAN as service"')
    ap.add_argument("--client-hardware", default=None,
                    help="override auto-detected client hardware string")
    ap.add_argument("--trials", type=int, default=33)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--beach", default="Pismo Beach")
    ap.add_argument("--forecast-file", default=str(DEFAULT_FORECAST))
    ap.add_argument("--live-port", type=int, default=8000)
    ap.add_argument("--fallback-port", type=int, default=8001)
    ap.add_argument("--out-csv", default=str(REPO_ROOT / "results" / "latency_raw.csv"))
    ap.add_argument("--out-tex", default=str(REPO_ROOT / "results" / "latency_table.tex"))
    ap.add_argument("--yes", action="store_true",
                    help="required to actually send the live (paid) Claude calls")
    args = ap.parse_args()

    client_hw = args.client_hardware or detect_client_hardware()
    n_measured = args.trials - args.warmup

    # --- preflight: live conditions require a real key; do not fabricate ------
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    live_labels = [c[0] for c in CONDITIONS if c[6]]
    if not key:
        print(
            "FATAL: conditions " + ", ".join(live_labels) + " require live Claude "
            "generation, but ANTHROPIC_API_KEY is not set.\n"
            "Refusing to run: live-generation latency must not be fabricated from "
            "the fallback path.\n"
            "Set a valid ANTHROPIC_API_KEY and re-run with --yes.",
            file=sys.stderr,
        )
        return 2

    forecast = Path(args.forecast_file).read_text()
    paid_calls = args.trials * len(live_labels)
    print(f"Plan: {len(CONDITIONS)} conditions x {args.trials} trials "
          f"({args.warmup} warm-up + {n_measured} measured), ~{args.sleep}s apart.")
    print(f"Live (paid) Claude calls: {paid_calls}  |  fallback calls: {args.trials}")
    print(f"Client hardware: {client_hw}")
    print(f"Forecast fixture: {args.forecast_file}")
    if not args.yes:
        print("\nRefusing to send live paid calls without --yes. Re-run with --yes.",
              file=sys.stderr)
        return 2

    live_proc = fb_proc = None
    all_rows = []
    try:
        live_proc = start_service(args.live_port, with_key=True)
        fb_proc = start_service(args.fallback_port, with_key=False)
        wait_healthy(args.live_port)
        wait_healthy(args.fallback_port)

        for label, desc, rip, conf, count, expected, live in CONDITIONS:
            port = args.live_port if live else args.fallback_port
            url = f"http://127.0.0.1:{port}/v1/assess"
            payload = build_payload(args.beach, rip, conf, count, forecast)
            print(f"\n--- Condition {label} ({desc}) @ {url} ---")
            all_rows.extend(run_condition(
                label, desc, url, payload, expected,
                args.trials, args.warmup, args.sleep, args.timeout,
            ))
    except HardFail as exc:
        print(f"\nHARD-FAIL: {exc}\nNo output written.", file=sys.stderr)
        return 1
    finally:
        for p in (live_proc, fb_proc):
            if p is not None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()

    write_raw_csv(all_rows, Path(args.out_csv))
    summary = summarize(all_rows)
    write_tex(summary, Path(args.out_tex), n_measured, args.warmup,
              client_hw, args.network_note)
    print(f"\nWrote {Path(args.out_csv)}")
    print(f"Wrote {Path(args.out_tex)}")
    print_summary(summary, n_measured)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
