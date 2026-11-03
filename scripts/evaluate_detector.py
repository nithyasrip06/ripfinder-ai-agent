#!/usr/bin/env python3
"""Held-out evaluation of the shipped Unity rip detector (medium.onnx).

Runs the exact ONNX model the Quest app ships, with the app's post-processing
(stretch-resize to 640x640, single-class score = channel 4, confidence >= 0.25,
class-agnostic NMS at IoU 0.5), over human-reviewed WebCOOS rip-current
datasets that post-date the model (model committed 2025-07-28; images are
2026 WebCOOS stills), and reports:

* image-level detection quality at each confidence threshold -- this is what
  the app uses: "rip detected" + highest confidence feed the risk engine;
* box-level average precision (IoU 0.5 and 0.3; rip extents are fuzzy);
* a reliability table: how often an image whose top confidence falls in a bin
  actually contains a rip;
* 95% confidence intervals from a bootstrap that resamples whole rip EVENTS
  (frames within +/-3 min of one event are near-duplicates, so frames are not
  independent).

Each metric is computed for two input encodings:
  srgb   -- normal 8-bit image values, as the model was trained;
  linear -- sRGB-decoded values, which is what Unity currently feeds the model
            for Texture2D inputs in this Linear-color-space project.

Dataset caveats (also written to the summary):
  * labels were auto-suggested by a different 2026 model (yolov8m.pt) and then
    human-reviewed; negatives were chosen where that model scored < 0.35, so
    negatives may be easier than typical frames;
  * ~85% of images contain a rip, far above real-world prevalence, so
    precision here is optimistic -- use the false-positive rate on negatives
    (prevalence-independent) when reasoning about deployment.

Run from the repo root:
    python scripts/evaluate_detector.py \\
        --model /path/to/medium.onnx \\
        --dataset ~/Documents/data-labeling-proj/staging/rip_dataset_oceancity \\
        --dataset ~/Documents/data-labeling-proj/staging/rip_dataset_carova
"""

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "results" / "detector_eval"

# --- App post-processing (SentisInferenceUiManager) --------------------------
INPUT_SIZE = 640
APP_CONF_THRESHOLD = 0.25
NMS_IOU = 0.5
CURVE_CONF_FLOOR = 0.01  # keep low-confidence boxes so curves span thresholds

# Confidence tiers used by agent/reasoning_engine.py::_visual_contribution.
ENGINE_TIERS = (0.25, 0.50, 0.70, 0.85)
SWEEP = [round(t, 2) for t in np.arange(0.25, 0.951, 0.05)]
RELIABILITY_BINS = [0.0, 0.25, 0.40, 0.50, 0.60, 0.70, 0.85, 1.01]

BOOTSTRAP_ROUNDS = 1000
SEED = 7


# --- Data ----------------------------------------------------------------------
def load_dataset(root: Path, split: str | None = None) -> list[dict]:
    # events.csv groups near-duplicate frames; without it each image is its own event.
    events = {}
    if (root / "events.csv").exists():
        with open(root / "events.csv") as f:
            for row in csv.DictReader(f):
                events[row["file"]] = row["event_id"]

    items = []
    for image in sorted((root / "images").glob(f"{split or '*'}/*")):
        if image.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        label = root / "labels" / image.parent.name / (image.stem + ".txt")
        boxes = []
        if label.exists():
            for line in label.read_text().splitlines():
                parts = line.split()
                if len(parts) == 5:
                    boxes.append([float(v) for v in parts[1:]])  # cx, cy, w, h (0-1)
        items.append({
            "dataset": root.name,
            "file": image.stem,
            "path": image,
            "event": f"{root.name}:{events.get(image.stem, image.stem)}",
            "gt": np.array(boxes, dtype=np.float32).reshape(-1, 4),
        })
    return items


# --- Model + app post-processing ----------------------------------------------
def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def preprocess(path: Path, encoding: str) -> np.ndarray:
    rgb = cv2.imread(str(path), cv2.IMREAD_COLOR)[:, :, ::-1]
    x = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    x = x.astype(np.float32) / 255.0
    if encoding == "linear":
        x = srgb_to_linear(x)
    return x.transpose(2, 0, 1)[None].astype(np.float32)


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between (N,4) and (M,4) boxes in cx, cy, w, h form."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    a1, a2 = a[:, None, :2] - a[:, None, 2:] / 2, a[:, None, :2] + a[:, None, 2:] / 2
    b1, b2 = b[None, :, :2] - b[None, :, 2:] / 2, b[None, :, :2] + b[None, :, 2:] / 2
    inter = np.clip(np.minimum(a2, b2) - np.maximum(a1, b1), 0, None).prod(-1)
    union = a[:, None, 2:].prod(-1) + b[None, :, 2:].prod(-1) - inter
    return inter / np.maximum(union, 1e-9)


def detect(session: ort.InferenceSession, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Boxes (normalized cx, cy, w, h) and scores after app-style NMS."""
    out = session.run(None, {session.get_inputs()[0].name: x})[0][0]  # (5, 8400)
    scores = out[4:].max(axis=0)
    keep = scores >= CURVE_CONF_FLOOR
    boxes = (out[:4, keep].T / INPUT_SIZE).astype(np.float32)
    scores = scores[keep]

    order = np.argsort(-scores)
    boxes, scores = boxes[order], scores[order]
    selected = []
    alive = np.ones(len(boxes), dtype=bool)
    for i in range(len(boxes)):
        if not alive[i]:
            continue
        selected.append(i)
        alive &= iou_matrix(boxes[i:i + 1], boxes)[0] <= NMS_IOU
    return boxes[selected], scores[selected]


# --- Metrics -------------------------------------------------------------------
def image_counts(items: list[dict], threshold: float) -> dict:
    tp = fp = fn = tn = 0
    for it in items:
        predicted = it["max_score"] >= threshold
        actual = len(it["gt"]) > 0
        tp += predicted and actual
        fp += predicted and not actual
        fn += (not predicted) and actual
        tn += (not predicted) and not actual
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def rates(c: dict) -> dict:
    div = lambda a, b: a / b if b else float("nan")
    return {
        "precision": div(c["tp"], c["tp"] + c["fp"]),
        "recall": div(c["tp"], c["tp"] + c["fn"]),
        "false_positive_rate": div(c["fp"], c["fp"] + c["tn"]),
    }


def average_precision(items: list[dict], iou_threshold: float) -> float:
    """VOC-style all-point AP over boxes, single class."""
    records = []
    total_gt = sum(len(it["gt"]) for it in items)
    for it in items:
        ious = iou_matrix(it["boxes"], it["gt"])
        matched = set()
        for d in range(len(it["boxes"])):  # boxes already sorted by score
            j = int(np.argmax(ious[d])) if ious.shape[1] else -1
            hit = j >= 0 and ious[d, j] >= iou_threshold and j not in matched
            if hit:
                matched.add(j)
            records.append((float(it["scores"][d]), hit))
    if total_gt == 0:
        return float("nan")
    records.sort(key=lambda r: -r[0])
    hits = np.array([r[1] for r in records], dtype=np.float32)
    tp = np.cumsum(hits)
    fp = np.cumsum(1 - hits)
    recall = tp / total_gt
    precision = tp / np.maximum(tp + fp, 1e-9)
    precision = np.maximum.accumulate(precision[::-1])[::-1]
    recall = np.concatenate([[0.0], recall])
    return float(np.sum((recall[1:] - recall[:-1]) * precision))


def bootstrap(items: list[dict], metric) -> tuple[float, float]:
    """95% CI, resampling whole events (clusters of near-duplicate frames)."""
    by_event = {}
    for it in items:
        by_event.setdefault(it["event"], []).append(it)
    events = list(by_event)
    rng = random.Random(SEED)
    values = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [it for e in rng.choices(events, k=len(events)) for it in by_event[e]]
        v = metric(sample)
        if not np.isnan(v):
            values.append(v)
    if not values:  # e.g. precision when nothing is ever predicted
        return float("nan"), float("nan")
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def fmt(value: float, ci: tuple[float, float]) -> str:
    if np.isnan(value):
        return "n/a (no detections)"
    return f"{value:.3f} ({ci[0]:.2f}–{ci[1]:.2f})"


# --- Run -----------------------------------------------------------------------
def evaluate(model: Path, datasets: list[Path], out_dir: Path, sample: int | None,
             split: str | None) -> None:
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    base = [it for d in datasets for it in load_dataset(d, split)]
    if sample is not None and sample < len(base):
        base = random.Random(SEED).sample(base, sample)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_pos = sum(len(it["gt"]) > 0 for it in base)
    n_events = len({it["event"] for it in base})
    summary = [
        "# Detector held-out evaluation (medium.onnx)",
        "",
        f"Images: {len(base)} ({n_pos} with rips, {len(base) - n_pos} without), "
        f"{sum(len(it['gt']) for it in base)} labelled boxes, {n_events} events, "
        f"datasets: {', '.join(d.name for d in datasets)}"
        + (f" (random sample of {sample})" if sample else "") + ".",
        "All label classes (bathymetry/sediment/structural) are merged into one `rip` class, "
        "matching the single-class model.",
        "",
        "Caveats: labels were auto-suggested by a different model (yolov8m.pt, 2026) and "
        "human-reviewed; negatives were chosen where that model scored < 0.35, so they may be "
        "easier than typical frames. About 85% of images contain a rip, far above real-world "
        "prevalence, so precision is optimistic; the false-positive rate on rip-free images is "
        "the prevalence-independent number. Intervals are 95% bootstrap CIs over events.",
        "",
    ]

    per_image_rows, sweep_rows, reliability_rows = [], [], []
    for encoding in ("srgb", "linear"):
        items = []
        for it in base:
            boxes, scores = detect(session, preprocess(it["path"], encoding))
            items.append({**it, "boxes": boxes, "scores": scores,
                          "max_score": float(scores[0]) if len(scores) else 0.0})
            per_image_rows.append({
                "encoding": encoding, "dataset": it["dataset"], "file": it["file"],
                "event": it["event"], "gt_boxes": len(it["gt"]),
                "max_score": round(items[-1]["max_score"], 4),
                "detections_at_0.25": int((scores >= APP_CONF_THRESHOLD).sum()),
            })

        for t in SWEEP:
            c = image_counts(items, t)
            sweep_rows.append({"encoding": encoding, "threshold": t, **c,
                               **{k: round(v, 4) for k, v in rates(c).items()}})

        for lo, hi in zip(RELIABILITY_BINS[:-1], RELIABILITY_BINS[1:]):
            in_bin = [it for it in items if lo <= it["max_score"] < hi]
            pos = sum(len(it["gt"]) > 0 for it in in_bin)
            reliability_rows.append({
                "encoding": encoding, "bin": f"[{lo:.2f}, {min(hi, 1.0):.2f})",
                "images": len(in_bin), "with_rip": pos,
                "fraction_with_rip": round(pos / len(in_bin), 4) if in_bin else "",
            })

        ap50 = average_precision(items, 0.5)
        ap30 = average_precision(items, 0.3)
        ap50_ci = bootstrap(items, lambda s: average_precision(s, 0.5))
        summary += [
            f"## Input encoding: `{encoding}`"
            + (" (what the model was trained on)" if encoding == "srgb"
               else " (what Unity currently feeds Texture2D inputs)"),
            "",
            f"Box AP@0.5 = {ap50:.3f} (95% CI {ap50_ci[0]:.3f}–{ap50_ci[1]:.3f}); "
            f"AP@0.3 = {ap30:.3f}.",
            "",
            "Image-level, at the risk engine's confidence tiers (\"rip detected\" = top "
            "confidence >= threshold):",
            "",
            "| Threshold | Precision | Recall | False-positive rate (rip-free images) |",
            "|---|---|---|---|",
        ]
        for t in ENGINE_TIERS:
            r = rates(image_counts(items, t))
            p_ci = bootstrap(items, lambda s, t=t: rates(image_counts(s, t))["precision"])
            r_ci = bootstrap(items, lambda s, t=t: rates(image_counts(s, t))["recall"])
            f_ci = bootstrap(items, lambda s, t=t: rates(image_counts(s, t))["false_positive_rate"])
            summary.append(
                f"| {t:.2f} | {fmt(r['precision'], p_ci)} | {fmt(r['recall'], r_ci)} "
                f"| {fmt(r['false_positive_rate'], f_ci)} |")

        summary += ["", "Per dataset at the app threshold (0.25):", ""]
        for d in datasets:
            sub = [it for it in items if it["dataset"] == d.name]
            r = rates(image_counts(sub, APP_CONF_THRESHOLD))
            summary.append(
                f"- `{d.name}`: precision {r['precision']:.3f}, recall {r['recall']:.3f}, "
                f"false-positive rate {r['false_positive_rate']:.3f} ({len(sub)} images)")
        summary.append("")

    write_csv(out_dir / "per_image.csv", per_image_rows)
    write_csv(out_dir / "threshold_sweep.csv", sweep_rows)
    write_csv(out_dir / "reliability.csv", reliability_rows)
    (out_dir / "SUMMARY.md").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    print(f"Wrote {out_dir}/SUMMARY.md, per_image.csv, threshold_sweep.csv, reliability.csv")


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--sample", type=int, default=None,
                        help="evaluate a fixed random sample of this many images")
    parser.add_argument("--split", default=None,
                        help="only use images/<split>/ (default: all splits)")
    args = parser.parse_args()
    evaluate(args.model, [d.expanduser() for d in args.dataset], args.out, args.sample, args.split)


if __name__ == "__main__":
    main()
