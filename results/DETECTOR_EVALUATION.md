# Detector evaluation: shipped Unity model (`medium.onnx`)

Produced by `scripts/evaluate_detector.py`, which runs the exact ONNX file the
Quest app ships, with the app's post-processing: stretch-resize to 640×640,
confidence = class score, cutoff 0.25, class-agnostic NMS at IoU 0.5. Full
tables, with 95% bootstrap CIs, are in `detector_eval/` and
`detector_eval_annotated/`.

## Datasets
| Set | Images | With rip | Notes |
|---|---|---|---|
| WebCOOS beach cameras (Ocean City MD + Carova NC) | 498 | 423 | 2026 stills, after the model was added (2025-07-28), so they are guaranteed held-out. Human-reviewed. CIs resample whole rip events. |
| `annotated_images_dataset` validation split (random 600) | 600 | ~480 | 640×640 rip imagery. Training provenance of `medium.onnx` is unknown, so overlap with its training data cannot be ruled out. If anything, this flatters the model. |

All label classes are merged into one `rip` class, to match the single-class model.

## Results (image level, sRGB input, "rip detected" = top confidence ≥ threshold)
| Threshold | WebCOOS recall | WebCOOS false-positive rate | Annotated recall | Annotated false-positive rate |
|---|---|---|---|---|
| 0.25 (app cutoff) | 0.11 | 0.12 | 0.44 | 0.57 |
| 0.50 | 0.00 | 0.00 | 0.23 | 0.18 |
| 0.70 | 0.00 | 0.00 | 0.01 | 0.00 |
| 0.85 | 0.00 | 0.00 | 0.00 | 0.00 |

Box AP@0.5 is about 0.00 on WebCOOS and 0.06 on the annotated set.

## Findings
1. **The detector is weak, and very weak on fixed beach-camera views.**
   - At the app's 0.25 cutoff it misses 89% of rips in the WebCOOS frames.
   - When it fires, the box is usually not on the rip. On Ocean City it repeatedly fires on the same lower-right region of the frame.
   - On the annotated set it finds 44% of rips but also fires on 57% of rip-free images, close to no discrimination.
2. **Its confidence almost never exceeds ~0.65.** The risk engine's confidence tiers at 0.70 and 0.85 (+0.20 / +0.30) are effectively unreachable. In practice the confidence bonus is 0 or +0.10. The tiers are not miscalibrated so much as unused.
3. **Unity feeds the model darker input than it was trained on.**
   - The project uses Linear color space, so Sentis `TextureConverter.ToTensor` receives sRGB-decoded values.
   - Reproduced exactly: `rip_test.png` scores 0.65 with normal input, 0.54–0.55 decoded, and Unity logged 0.549.
   - This roughly **halves recall**: 0.44 → 0.24 on the annotated set at 0.25.
   - Confirmed for Texture2D test images. It has **not** been verified for the live Quest passthrough `WebCamTexture`; check on the headset before changing the live path.
4. **Stretching frames to a square distorts wide images.** Beach cameras are 16:9 and the Quest camera is 4:3. A letterbox test did not rescue `medium.onnx`, so this is secondary to finding 1. It still matters for any retrained model, because Ultralytics trains with letterboxing.

## What this means for the paper
- Do not claim detection accuracy for `medium.onnx`. Present the detector as a placeholder component of the pipeline, and report these numbers, or omit detector accuracy and state that it was not validated.
- The system contribution stands: the deterministic rules make the decision, the LLM only writes the text, there is a fallback, and NOAA integration is on-device. It does not depend on this detector being good.
- The risk-engine confidence tiers should be recalibrated **after** a better detector is in place. Tuning them to this model would just encode its weakness.

## Recommended next steps
1. **Train or select a better detector and evaluate it with this script.** The WebCOOS sets are held out only for models that never saw them. The 2026 `yolov8m.pt` was used to auto-label them, so it is not a fair test on those images.
2. **Fix the color-space mismatch** once headset logs confirm the live feed is affected. Gamma-encode the input before inference, or have Sentis read the texture without sRGB decoding.
3. **Match the training preprocessing** (letterbox) in Unity for any retrained model.
