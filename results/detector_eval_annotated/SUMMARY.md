# Detector held-out evaluation (medium.onnx)

Images: 600 (498 with rips, 102 without), 725 labelled boxes, 600 events, datasets: yolov8_dataset (random sample of 600).
All label classes (bathymetry/sediment/structural) are merged into one `rip` class, matching the single-class model.

Caveats: labels were auto-suggested by a different model (yolov8m.pt, 2026) and human-reviewed; negatives were chosen where that model scored < 0.35, so they may be easier than typical frames. About 85% of images contain a rip, far above real-world prevalence, so precision is optimistic; the false-positive rate on rip-free images is the prevalence-independent number. Intervals are 95% bootstrap CIs over events.

## Input encoding: `srgb` (what the model was trained on)

Box AP@0.5 = 0.058 (95% CI 0.039–0.078); AP@0.3 = 0.074.

Image-level, at the risk engine's confidence tiers ("rip detected" = top confidence >= threshold):

| Threshold | Precision | Recall | False-positive rate (rip-free images) |
|---|---|---|---|
| 0.25 | 0.791 (0.74–0.84) | 0.440 (0.40–0.48) | 0.569 (0.47–0.67) |
| 0.50 | 0.865 (0.80–0.92) | 0.231 (0.20–0.26) | 0.176 (0.10–0.25) |
| 0.70 | 1.000 (1.00–1.00) | 0.006 (0.00–0.01) | 0.000 (0.00–0.00) |
| 0.85 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |

Per dataset at the app threshold (0.25):

- `yolov8_dataset`: precision 0.791, recall 0.440, false-positive rate 0.569 (600 images)

## Input encoding: `linear` (what Unity currently feeds Texture2D inputs)

Box AP@0.5 = 0.070 (95% CI 0.051–0.090); AP@0.3 = 0.094.

Image-level, at the risk engine's confidence tiers ("rip detected" = top confidence >= threshold):

| Threshold | Precision | Recall | False-positive rate (rip-free images) |
|---|---|---|---|
| 0.25 | 0.791 (0.72–0.86) | 0.243 (0.21–0.28) | 0.314 (0.22–0.40) |
| 0.50 | 0.898 (0.80–0.98) | 0.088 (0.06–0.11) | 0.049 (0.01–0.10) |
| 0.70 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |
| 0.85 | n/a (no detections) | 0.000 (0.00–0.00) | 0.000 (0.00–0.00) |

Per dataset at the app threshold (0.25):

- `yolov8_dataset`: precision 0.791, recall 0.243, false-positive rate 0.314 (600 images)

