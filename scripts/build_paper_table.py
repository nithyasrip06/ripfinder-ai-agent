#!/usr/bin/env python3
"""Build a compact, publication-ready decision table from results/risk_surface.csv.

Selects a small set of the most informative cases (no manual retyping of any
value -- every score/level/surf value comes straight from the CSV) and writes:

    results/risk_surface_paper_table.csv

and prints the same table as GitHub-flavored Markdown.

The "Visual Term" and "Environmental Term" columns are short qualitative labels
DERIVED deterministically from the CSV's numeric columns (they are not new
measurements):

  Environmental Term  <- environmental_contribution: 0.00 none / 0.15 moderate
                         surf / 0.30 high surf
  Visual Term         <- rip_detected + confidence + detection_count

Run from the repo root:
    python scripts/build_paper_table.py
"""

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "results" / "risk_surface.csv"
OUT = REPO_ROOT / "results" / "risk_surface_paper_table.csv"

# Ordered (rip_detected, confidence, detection_count, forecast_case) selectors.
# Each is chosen to demonstrate one behaviour; all values are read from the CSV.
SELECTORS = [
    (False, 0.00, 0, "missing_forecast"),  # no detection, no forecast -> baseline
    (False, 0.00, 0, "high_surf"),         # no detection + strongest env -> still LOW
    (True, 0.55, 1, "missing_forecast"),   # visual-only evidence
    (True, 0.55, 1, "low_surf"),           # benign surf adds nothing
    (True, 0.55, 1, "moderate_surf"),      # env raises SCORE, class unchanged
    (True, 0.55, 1, "high_surf"),          # env causes CLASS transition MOD->HIGH
    (True, 0.90, 1, "missing_forecast"),   # strong visual only, just below HIGH
    (True, 0.90, 3, "missing_forecast"),   # multiple detections -> HIGH (visual only)
    (True, 0.75, 2, "moderate_surf"),      # combined visual + environmental
    (True, 0.90, 3, "high_surf"),          # combined max -> clamped 1.0
]

COLUMNS = [
    "Rip Detected",
    "Confidence",
    "Count",
    "Surf Midpoint (ft)",
    "Visual Term",
    "Environmental Term",
    "Score",
    "Risk Level",
]


def _environmental_term(env_contrib: float) -> str:
    if env_contrib >= 0.30:
        return "high surf (0.30)"
    if env_contrib >= 0.15:
        return "moderate surf (0.15)"
    return "none (0.00)"


def _visual_term(rip: bool, confidence: float, count: int) -> str:
    if not rip:
        return "no detection"
    if confidence >= 0.85:
        tier = "very-high conf"
    elif confidence >= 0.70:
        tier = "high conf"
    elif confidence >= 0.50:
        tier = "moderate conf"
    else:
        tier = "low conf"
    return f"rip / {tier} / {count} region(s)"


def load_rows():
    index = {}
    for r in csv.DictReader(open(SRC)):
        key = (
            r["rip_detected"] == "True",
            float(r["confidence"]),
            int(r["detection_count"]),
            r["forecast_case"],
        )
        index[key] = r
    return index


def build():
    index = load_rows()
    table = []
    for sel in SELECTORS:
        r = index.get(sel)
        if r is None:
            raise SystemExit(f"Selector not found in CSV: {sel}")
        rip = r["rip_detected"] == "True"
        surf = r["parsed_surf_height_midpoint_ft"]
        table.append(
            {
                "Rip Detected": "yes" if rip else "no",
                "Confidence": r["confidence"],
                "Count": r["detection_count"],
                "Surf Midpoint (ft)": surf if surf else "-",
                "Visual Term": _visual_term(
                    rip, float(r["confidence"]), int(r["detection_count"])
                ),
                "Environmental Term": _environmental_term(
                    float(r["environmental_contribution"])
                ),
                "Score": r["risk_score"],
                "Risk Level": r["risk_level"],
            }
        )
    return table


def write_csv(table):
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(table)


def print_markdown(table):
    print("| " + " | ".join(COLUMNS) + " |")
    print("|" + "|".join(["---"] * len(COLUMNS)) + "|")
    for row in table:
        print("| " + " | ".join(str(row[c]) for c in COLUMNS) + " |")


def main():
    table = build()
    write_csv(table)
    print(f"Wrote {len(table)} rows -> {OUT}\n")
    print_markdown(table)


if __name__ == "__main__":
    main()
