# Detector held-out evaluation (medium.onnx)

Images: 498 (423 with rips, 75 without), 458 labelled boxes, 192 events, datasets: rip_dataset_oceancity, rip_dataset_carova.
All label classes (bathymetry/sediment/structural) are merged into one `rip` class, matching the single-class model.

Caveats: labels were auto-suggested by a different model (yolov8m.pt, 2026) and human-reviewed; negatives were chosen where that model scored < 0.35, so they may be easier than typical frames. About 85% of images contain a rip, far above real-world prevalence, so precision is optimistic; the false-positive rate on rip-free images is the prevalence-independent number. Intervals are 95% bootstrap CIs over events.

## Input encoding: `srgb` (what the model was trained on)

Box AP@0.5 = 0.000 (95% CI 0.000–0.001); AP@0.3 = 0.003.

Image-level, at the risk engine's confidence tiers ("rip detected" = top confidence >= threshold):

| Threshold | Precision | Recall | False-positive rate (rip-free images) |
|---|---|---|---|
| 0.25 | 0.836 (0.57–1.00) | 0.109 (0.07–0.15) | 0.120 (0.00–0.17) |
| 0.50 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |
| 0.70 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |
| 0.85 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |

Per dataset at the app threshold (0.25):

- `rip_dataset_oceancity`: precision 0.827, recall 0.141, false-positive rate 0.167 (360 images)
- `rip_dataset_carova`: precision 1.000, recall 0.026, false-positive rate 0.000 (138 images)

## Input encoding: `linear` (what Unity currently feeds Texture2D inputs)

Box AP@0.5 = 0.000 (95% CI 0.000–0.000); AP@0.3 = 0.001.

Image-level, at the risk engine's confidence tiers ("rip detected" = top confidence >= threshold):

| Threshold | Precision | Recall | False-positive rate (rip-free images) |
|---|---|---|---|
| 0.25 | 1.000 (1.00–1.00) | 0.012 (0.00–0.04) | 0.000 (0.00–0.00) |
| 0.50 | 1.000 (1.00–1.00) | 0.007 (0.00–0.02) | 0.000 (0.00–0.00) |
| 0.70 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |
| 0.85 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |

Per dataset at the app threshold (0.25):

- `rip_dataset_oceancity`: precision 1.000, recall 0.003, false-positive rate 0.000 (360 images)
- `rip_dataset_carova`: precision 1.000, recall 0.034, false-positive rate 0.000 (138 images)

