"""Standalone WebCOOS research pipeline (NOT the Unity /v1/assess path).

This module is a self-contained, script-run research pipeline: it pulls real
WebCOOS camera stills, runs the ONNX detector, fetches a NOAA forecast, scores
it, and (optionally) phrases it with Claude. It is intentionally kept separate
from the Unity-facing `/v1/assess` API (`agent/api.py`), which takes structured
detection stats directly from the headset and does not import this module.

Status: this pipeline pre-dates the current `RiskInput` schema and constructs
`RiskInput(**stats, noaa_forecast=..., location=...)`, which no longer matches
`reasoning_engine.RiskInput` -- so it is not currently runnable as-is and needs
a schema update before use. It is retained (per project decision) as the
research/data-collection workflow and is NOT coupled to the API path, so it does
not affect `/v1/assess`. Do not delete it merely because Unity does not use it.
"""

import json
from pathlib import Path

from llm_agent import generate_safety_message
from noaa_forecast import format_forecast_summary, get_forecast
from reasoning_engine import RiskInput, calculate_risk
from rip_detector import DEFAULT_MODEL_PATH, detect_on_frames, load_frames_from_media, load_model
from station_config import STATION_CONFIG
from webcoos_client import fetch_recent_media, get_client

# Chosen by running `python3 webcoos_client.py`: has fresh (through today)
# one-minute-stills inventory, i.e. individual timestamped images rather
# than video files -- no video decoding needed.
CAMERA_NAME = "Walton Lighthouse, Santa Cruz, CA"
PRODUCT_NAME = "one-minute-stills"

MODEL_PATH = DEFAULT_MODEL_PATH


def build_risk_input_from_real_data(
    camera_name: str = CAMERA_NAME,
    product_name: str = PRODUCT_NAME,
    model_path: Path = MODEL_PATH,
    minutes_back: int = 30,
    interval: int = 1,
) -> RiskInput:
    client = get_client()
    media_paths = fetch_recent_media(
        client, camera_name, product_name, minutes_back=minutes_back, interval=interval
    )
    if not media_paths:
        raise RuntimeError(
            f"No media returned for camera={camera_name!r} product={product_name!r} "
            f"in the last {minutes_back} minutes."
        )

    frames = load_frames_from_media(media_paths)
    if not frames:
        raise RuntimeError(f"Downloaded {len(media_paths)} file(s) but no frames could be decoded.")

    session, class_names = load_model(model_path)
    stats = detect_on_frames(session, class_names, frames)

    if camera_name not in STATION_CONFIG:
        raise RuntimeError(
            f"No NWS zone mapping for camera {camera_name!r} -- add one to station_config.STATION_CONFIG"
        )
    wfo_site, zone_match = STATION_CONFIG[camera_name]
    forecast = get_forecast(wfo_site, zone_match)
    noaa_forecast_text = format_forecast_summary(forecast)

    return RiskInput(**stats, noaa_forecast=noaa_forecast_text, location=camera_name)


def main():
    risk_input = build_risk_input_from_real_data()

    print("\n--- REAL DETECTION STATS (WebCOOS + ONNX) ---")
    print(risk_input.model_dump_json(indent=2))

    risk_output = calculate_risk(risk_input)
    print("\n--- RULE-BASED RISK OUTPUT ---")
    print(risk_output.model_dump_json(indent=2))

    safety_message = generate_safety_message(risk_input, risk_output)
    print("\n--- CLAUDE SAFETY MESSAGE ---")
    print(json.dumps(safety_message, indent=2))


if __name__ == "__main__":
    main()
