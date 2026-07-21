import ast
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "Bathy Model.onnx"
INPUT_SIZE = 640
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".ts", ".webm"}

# Per-class weight applied before collapsing a frame's class scores into one
# scalar rip score. sediment_rip contributes at reduced weight; any class not
# listed here (e.g. background) contributes nothing.
CLASS_WEIGHT = {"rip": 1.0, "sediment_rip": 0.3}

DETECTION_THRESHOLD = 0.5


def inspect_model(model_path: Path) -> dict:
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    meta = session.get_modelmeta().custom_metadata_map
    return {
        "inputs": [(i.name, i.shape, i.type) for i in session.get_inputs()],
        "outputs": [(o.name, o.shape, o.type) for o in session.get_outputs()],
        "class_names": _parse_class_names(meta),
    }


def _parse_class_names(meta: dict) -> dict[int, str]:
    if "names" not in meta:
        return {0: "rip"}
    return ast.literal_eval(meta["names"])


def load_model(model_path: Path = DEFAULT_MODEL_PATH) -> tuple[ort.InferenceSession, dict[int, str]]:
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    class_names = _parse_class_names(session.get_modelmeta().custom_metadata_map)
    return session, class_names


def load_frames_from_media(paths: list[Path], max_frames: int = 30) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for path in paths:
        if len(frames) >= max_frames:
            break
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            frames.extend(_sample_video_frames(path, max_frames - len(frames)))
        else:
            frame = cv2.imread(str(path))
            if frame is not None:
                frames.append(frame)
    return frames[:max_frames]


def _sample_video_frames(video_path: Path, count: int) -> list[np.ndarray]:
    if count <= 0:
        return []
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return []
    indices = np.linspace(0, total - 1, num=min(count, total), dtype=int)
    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def preprocess_frame(frame: np.ndarray, input_size: int = INPUT_SIZE) -> np.ndarray:
    resized = cv2.resize(frame, (input_size, input_size))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
    return np.expand_dims(chw, axis=0)


def run_inference(session: ort.InferenceSession, frame: np.ndarray) -> np.ndarray:
    input_name = session.get_inputs()[0].name
    tensor = preprocess_frame(frame)
    outputs = session.run(None, {input_name: tensor})
    return outputs[0]  # raw YOLOv8 detect output, shape (1, 4 + num_classes, num_anchors)


def class_scores(raw_output: np.ndarray, class_names: dict[int, str]) -> dict[str, float]:
    # channels 0-3 are box coords (cx, cy, w, h); class scores start at channel 4,
    # already sigmoid-activated by the exported Detect head. Max over anchors
    # gives "was this class seen anywhere in the frame", which is all a
    # frame-level scalar needs -- no box decoding or NMS required.
    return {
        name: float(np.max(raw_output[0, 4 + idx, :]))
        for idx, name in class_names.items()
    }


def frame_rip_score(raw_output: np.ndarray, class_names: dict[int, str]) -> float:
    scores = class_scores(raw_output, class_names)
    weighted = sum(score * CLASS_WEIGHT.get(name, 0.0) for name, score in scores.items())
    return min(weighted, 1.0)


def score_frames(session: ort.InferenceSession, class_names: dict[int, str], frames: list[np.ndarray]) -> list[float]:
    return [frame_rip_score(run_inference(session, frame), class_names) for frame in frames]


def detect_on_frames(
    session: ort.InferenceSession,
    class_names: dict[int, str],
    frames: list[np.ndarray],
    threshold: float = DETECTION_THRESHOLD,
) -> dict:
    frame_scores = score_frames(session, class_names, frames)

    if not frame_scores:
        return {"detection_confidence": 0.0, "detection_last_30_frames": 0, "detection_count": 0}

    top_k = sorted(frame_scores, reverse=True)[:3]
    detection_confidence = round(sum(top_k) / len(top_k), 4)

    positive = [score >= threshold for score in frame_scores]
    detection_last_30_frames = sum(positive)

    detection_count = 0
    in_streak = False
    for is_positive in positive:
        if is_positive and not in_streak:
            detection_count += 1
            in_streak = True
        elif not is_positive:
            in_streak = False

    return {
        "detection_confidence": detection_confidence,
        "detection_last_30_frames": detection_last_30_frames,
        "detection_count": detection_count,
    }


if __name__ == "__main__":
    models_dir = Path(__file__).resolve().parent.parent / "models"
    for model_path in sorted(models_dir.glob("*.onnx")):
        print(f"\n--- {model_path.name} ---")
        try:
            info = inspect_model(model_path)
            print("inputs: ", info["inputs"])
            print("outputs:", info["outputs"])
            print("classes:", info["class_names"])
        except Exception as error:
            print(f"FAILED to load: {error}")
