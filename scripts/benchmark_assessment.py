#!/usr/bin/env python3
"""Latency benchmark for the /v1/assess endpoint.

Sends repeated requests and records, per request, four separated timers:

    risk_ms                     server: deterministic engine (X-RipFinder-Risk-Ms)
    claude_ms                   server: Claude generation attempt (X-RipFinder-Claude-Ms)
    backend_ms                  server: total endpoint work (X-RipFinder-Backend-Ms)
    client_round_trip_ms        CLIENT-OBSERVED HTTP round-trip (measured here)

`client_round_trip_ms` is NOT "network latency": it includes transport,
serialization, AND all server processing. It is deliberately named
"client-observed HTTP round-trip".

Two request cases are benchmarked: a positive detection and a no-rip detection.

PAID-CALL WARNING
-----------------
If the target server has a valid ANTHROPIC_API_KEY, every measured AND warm-up
request is a PAID Claude call. Total live Claude calls = (warmup + runs) * 2
cases. With the defaults (5 warmup + 30 runs) that is (5+30)*2 = 70 paid calls.
To benchmark the deterministic path with ZERO paid calls, point --url at a
server started WITHOUT an ANTHROPIC_API_KEY: every request then falls back and
`claude_ms` reflects the immediate SDK auth-failure, not live generation.

Example (final research run -- 5 warm-ups + 30 measured trials per case):
    python scripts/benchmark_assessment.py --warmup 5 --runs 30 \
        --url http://127.0.0.1:8000/v1/assess \
        --output results/latency.csv --summary results/latency_summary.csv
"""

import argparse
import csv
import statistics
import time
from pathlib import Path

import requests

CASES = {
    "positive_detection": {
        "beach": "Pismo Beach",
        "rip_detected": True,
        "confidence": 0.90,
        "detection_count": 2,
        "forecast": "Surf Height...................5 to 7 feet.",
    },
    "no_rip": {
        "beach": "Pismo Beach",
        "rip_detected": False,
        "confidence": 0.0,
        "detection_count": 0,
        "forecast": "Surf Height...................1 to 2 feet.",
    },
}

HEADER_METRICS = {
    "risk_ms": "X-RipFinder-Risk-Ms",
    "claude_ms": "X-RipFinder-Claude-Ms",
    "backend_ms": "X-RipFinder-Backend-Ms",
}

# Timer columns summarized for each case and combined.
TIMERS = ["risk_ms", "claude_ms", "backend_ms", "client_round_trip_ms"]

CSV_FIELDS = [
    "case",
    "run_number",
    "success",
    "http_status",
    "risk_ms",
    "claude_ms",
    "backend_ms",
    "client_round_trip_ms",
    "assessment_source",
]

SUMMARY_FIELDS = [
    "scope",
    "metric",
    "n",
    "success_count",
    "success_rate",
    "median",
    "p95",
    "min",
    "max",
]


def percentile(values, p):
    """Reproducible linear-interpolation percentile (p in [0, 100])."""
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


def _header_float(resp, name):
    raw = resp.headers.get(name)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def run_case(url, payload, warmup, runs, case_name, timeout):
    for _ in range(warmup):
        try:
            requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException:
            pass

    records = []
    for i in range(runs):
        start = time.perf_counter()
        status = None
        source = None
        risk_ms = claude_ms = backend_ms = None
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            client_ms = (time.perf_counter() - start) * 1000.0
            status = resp.status_code
            risk_ms = _header_float(resp, HEADER_METRICS["risk_ms"])
            claude_ms = _header_float(resp, HEADER_METRICS["claude_ms"])
            backend_ms = _header_float(resp, HEADER_METRICS["backend_ms"])
            if resp.headers.get("content-type", "").startswith("application/json"):
                source = resp.json().get("assessment_source")
        except requests.RequestException as exc:
            client_ms = (time.perf_counter() - start) * 1000.0
            source = f"error:{type(exc).__name__}"
        records.append(
            {
                "case": case_name,
                "run_number": i,
                "success": status == 200,
                "http_status": status,
                "risk_ms": risk_ms,
                "claude_ms": claude_ms,
                "backend_ms": backend_ms,
                "client_round_trip_ms": round(client_ms, 3),
                "assessment_source": source,
            }
        )
    return records


def _clean(values):
    return [v for v in values if isinstance(v, (int, float))]


def _summary_rows(scope, rows):
    successes = [r for r in rows if r["success"]]
    n = len(rows)
    sc = len(successes)
    rate = round(sc / n, 4) if n else 0.0
    out = []
    for metric in TIMERS:
        vals = _clean(r[metric] for r in successes)
        if vals:
            out.append(
                {
                    "scope": scope,
                    "metric": metric,
                    "n": n,
                    "success_count": sc,
                    "success_rate": rate,
                    "median": round(statistics.median(vals), 3),
                    "p95": round(percentile(vals, 95), 3),
                    "min": round(min(vals), 3),
                    "max": round(max(vals), 3),
                }
            )
        else:
            out.append(
                {
                    "scope": scope,
                    "metric": metric,
                    "n": n,
                    "success_count": sc,
                    "success_rate": rate,
                    "median": "",
                    "p95": "",
                    "min": "",
                    "max": "",
                }
            )
    return out


def summarize(all_records):
    summary = []
    for case in CASES:
        summary.extend(_summary_rows(case, [r for r in all_records if r["case"] == case]))
    summary.extend(_summary_rows("combined", all_records))

    # Console view.
    for scope in list(CASES) + ["combined"]:
        rows = [r for r in summary if r["scope"] == scope]
        head = rows[0]
        print(f"\n=== {scope} ===")
        print(
            f"  N={head['n']}  success={head['success_count']}  "
            f"success_rate={head['success_rate']*100:.1f}%"
        )
        for r in rows:
            if r["median"] == "":
                print(f"  {r['metric']:<22} (no data)")
            else:
                print(
                    f"  {r['metric']:<22} median={r['median']:>9}  "
                    f"p95={r['p95']:>9}  min={r['min']:>9}  max={r['max']:>9}"
                )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Benchmark /v1/assess latency.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/assess")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", default="results/latency.csv")
    parser.add_argument("--summary", default="results/latency_summary.csv")
    args = parser.parse_args()

    all_records = []
    for case_name, payload in CASES.items():
        all_records.extend(
            run_case(args.url, payload, args.warmup, args.runs, case_name, args.timeout)
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_records)
    print(f"Wrote {len(all_records)} rows -> {out_path}")

    summary = summarize(all_records)
    summary_path = Path(args.summary)
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary)
    print(f"\nWrote summary -> {summary_path}")
    print(
        "\nNote: 'client_round_trip_ms' is the client-observed HTTP round-trip "
        "(transport + serialization + server processing), NOT network latency alone."
    )


if __name__ == "__main__":
    main()
