#!/usr/bin/env python3
"""Decision-surface evaluation for the deterministic risk engine.

Sweeps a reproducible grid over detector inputs and environmental states,
using the REAL engine implementation (no copied approximation), and writes
results/risk_surface.csv. Prints a concise, non-editorialized summary of what
the policy actually does.

Run from the repo root:
    python scripts/evaluate_risk_engine.py
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.reasoning_engine import RiskInput, calculate_risk  # noqa: E402

# --- Grid definition ---------------------------------------------------------
CONFIDENCES = [0.00, 0.25, 0.50, 0.55, 0.75, 0.90, 1.00]
COUNTS = [0, 1, 2, 3]

# Representative forecast strings that exercise the real surf-height parser.
# The parser returns the MIDPOINT of each range:
#   "1 to 2 feet" -> 1.5 (below moderate band)
#   "4 to 7 feet" -> 5.5 (moderate band; the canonical "ordinary surf" case)
#   "6 to 8 feet" -> 7.0 (high band)
FORECAST_CASES = {
    "missing_forecast": "",
    "low_surf": "Surf Height...................1 to 2 feet.",
    "moderate_surf": "Surf Height...................4 to 7 feet.",
    "high_surf": "Surf Height...................6 to 8 feet.",
}

FIELDNAMES = [
    "rip_detected",
    "confidence",
    "detection_count",
    "forecast_case",
    "parsed_surf_height_midpoint_ft",
    "visual_contribution",
    "environmental_contribution",
    "risk_score",
    "risk_level",
]


def _grid_inputs():
    """Yield (rip, confidence, count, forecast_case) grid points.

    rip_detected False coerces confidence/count to 0 (model validator), so we
    emit a single representative row per environmental state for that branch.
    rip_detected True requires count >= 1 (count 0 is invalid input).
    """
    for case in FORECAST_CASES:
        yield (False, 0.00, 0, case)
    for case in FORECAST_CASES:
        for confidence in CONFIDENCES:
            for count in COUNTS:
                if count == 0:
                    continue  # invalid when rip_detected is True
                yield (True, confidence, count, case)


def evaluate():
    rows = []
    for rip, confidence, count, case in _grid_inputs():
        data = RiskInput(
            beach="Pismo Beach",
            rip_detected=rip,
            confidence=confidence,
            detection_count=count,
            forecast=FORECAST_CASES[case],
        )
        out = calculate_risk(data)
        rows.append(
            {
                "rip_detected": rip,
                "confidence": confidence,
                "detection_count": count,
                "forecast_case": case,
                "parsed_surf_height_midpoint_ft": out.parsed_surf_height_midpoint_ft,
                "visual_contribution": out.visual_contribution,
                "environmental_contribution": out.environmental_contribution,
                "risk_score": out.risk_score,
                "risk_level": out.risk_level,
            }
        )
    return rows


def write_csv(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    print(f"\nEvaluated {len(rows)} grid points -> results/risk_surface.csv\n")

    # Unique LOW/MODERATE/HIGH boundaries (min/max score observed per level).
    print("Score range observed per risk level:")
    for level in ("LOW", "MODERATE", "HIGH"):
        scores = sorted({r["risk_score"] for r in rows if r["risk_level"] == level})
        if scores:
            print(f"  {level:<9} scores {scores[0]:.2f}..{scores[-1]:.2f}  ({len(scores)} distinct)")
        else:
            print(f"  {level:<9} (none)")

    # Compare across environmental states, holding the detector inputs fixed.
    by_detector = {}
    for r in rows:
        key = (r["rip_detected"], r["confidence"], r["detection_count"])
        by_detector.setdefault(key, {})[r["forecast_case"]] = r

    class_changes = 0
    score_only_changes = 0
    for key, cases in by_detector.items():
        levels = {c["risk_level"] for c in cases.values()}
        scores = {c["risk_score"] for c in cases.values()}
        if len(levels) > 1:
            class_changes += 1
        elif len(scores) > 1:
            score_only_changes += 1
    print("\nEnvironmental context effect (holding detector inputs fixed):")
    print(f"  detector points where environment changes the CLASS: {class_changes}")
    print(f"  detector points where environment changes only the SCORE: {score_only_changes}")

    # No visual detection + strongest environmental condition.
    print("\nNo visual detection + strongest environmental condition (high_surf):")
    for r in rows:
        if not r["rip_detected"] and r["forecast_case"] == "high_surf":
            print(
                f"  surf_midpoint={r['parsed_surf_height_midpoint_ft']} ft -> "
                f"score={r['risk_score']:.2f} level={r['risk_level']}"
            )

    # Typical 0.55 confidence, count 1, under each environmental state.
    print("\nTypical case (rip=True, confidence=0.55, count=1) per environment:")
    for case in FORECAST_CASES:
        match = next(
            r
            for r in rows
            if r["rip_detected"]
            and r["confidence"] == 0.55
            and r["detection_count"] == 1
            and r["forecast_case"] == case
        )
        print(
            f"  {case:<16} surf_mid={str(match['parsed_surf_height_midpoint_ft']):<5} "
            f"visual={match['visual_contribution']:.2f} "
            f"env={match['environmental_contribution']:.2f} "
            f"score={match['risk_score']:.2f} level={match['risk_level']}"
        )


def main():
    rows = evaluate()
    out_path = REPO_ROOT / "results" / "risk_surface.csv"
    write_csv(rows, out_path)
    summarize(rows)


if __name__ == "__main__":
    main()
