import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz
import pywebcoos
from dotenv import load_dotenv

from pywebcoos import timezones as webcoos_timezones

load_dotenv()

DEFAULT_REGION_SUFFIXES = (" CA", " FL", " HI")
DEFAULT_SAVE_DIR = Path(__file__).resolve().parent.parent / "data" / "webcoos_cache"


def get_client(verbose: bool = False) -> pywebcoos.API:
    token = os.getenv("WEBCOOS_API_TOKEN")
    if not token:
        raise RuntimeError(
            "WEBCOOS_API_TOKEN is not set. Add it to .env (same convention as ANTHROPIC_API_KEY)."
        )
    return pywebcoos.API(token, verbose=verbose)


def discover_cameras(client: pywebcoos.API, region_suffixes=DEFAULT_REGION_SUFFIXES) -> list[str]:
    names = client.get_cameras()["Camera Name"].tolist()
    if not region_suffixes:
        return names
    return [name for name in names if any(name.endswith(suffix) for suffix in region_suffixes)]


def list_products(client: pywebcoos.API, camera_name: str) -> list[str]:
    return client.get_products(camera_name)


def get_inventory_range(client: pywebcoos.API, camera_name: str, product_name: str) -> tuple[datetime, datetime]:
    # NOTE: these are coarse daily BIN boundaries (e.g. the last bin might
    # run 2026-07-16 00:00 -> 2026-07-17 00:00), not the actual timestamp of
    # the most recent real image -- a bin can be mostly empty near its edges.
    # Useful for a human-readable overview; do NOT anchor a fetch window on
    # this. Use get_latest_data_timestamp() for that.
    min_date, max_date = client.get_inventory(camera_name, product_name)
    return _parse_iso(min_date), _parse_iso(max_date)


def get_latest_data_timestamp(client: pywebcoos.API, camera_name: str, product_name: str) -> datetime:
    # get_inventory()'s public [min_date, max_date] are bin boundaries, not
    # real data timestamps -- the last bin's "Data End" can be many hours
    # before its "Bin End". Replicate the same private call chain
    # client.get_inventory() uses internally to reach the underlying
    # dataframe (which has no public accessor) and read the true latest
    # "Data End" among bins that actually have data.
    feeds = client._get_camera_feeds(camera_name, client.assets_json)
    products = client._get_camera_products("raw-video-data", feeds, camera_name)
    _, df_inv = client._get_service_slug(
        product_name, products, "raw-video-data", camera_name, client.api_base_url, client.HEADERS
    )
    with_data = df_inv[df_inv["Has Data?"] == 1]
    if with_data.empty:
        raise RuntimeError(f"No bins with data for camera={camera_name!r} product={product_name!r}")
    return _parse_iso(with_data["Data End"].max())


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _camera_timezone(client: pywebcoos.API, camera_name: str) -> str:
    # Mirrors pywebcoos.API._local2ISO's own lookup order, using only public/
    # semi-public surface: assets_json's per-camera timezone property first,
    # falling back to deriving it from a ", ST" suffix in the camera name,
    # falling back to UTC.
    for asset in client.assets_json["results"]:
        if asset["data"]["common"]["label"] == camera_name:
            timezone = asset["data"]["properties"].get("timezone")
            if timezone:
                return timezone
            break
    try:
        return webcoos_timezones.from_name(camera_name)
    except ValueError:
        return "UTC"


def fetch_recent_media(
    client: pywebcoos.API,
    camera_name: str,
    product_name: str,
    minutes_back: int = 30,
    interval: int = 1,
    save_dir: Path = DEFAULT_SAVE_DIR,
) -> list[Path]:
    # Anchor the window to the product's own latest REAL data point, not
    # wall-clock "now" and not the coarse inventory bin boundary (a bin can
    # be mostly empty near its edges -- see get_latest_data_timestamp).
    #
    # This timestamp is UTC, but client.download() expects LOCAL time
    # strings (it does its own local->UTC conversion internally via
    # _local2ISO). So it must be converted to the camera's local time before
    # formatting, or the query window would be silently shifted by the
    # camera's UTC offset.
    max_date_utc = get_latest_data_timestamp(client, camera_name, product_name)
    if max_date_utc.tzinfo is None:
        max_date_utc = max_date_utc.replace(tzinfo=timezone.utc)

    local_tz = pytz.timezone(_camera_timezone(client, camera_name))
    max_date_local = max_date_utc.astimezone(local_tz)
    start_local = max_date_local - timedelta(minutes=minutes_back)

    start_str = start_local.strftime("%Y%m%d%H%M")
    stop_str = max_date_local.strftime("%Y%m%d%H%M")

    try:
        filenames = client.download(
            camera_name, product_name, start_str, stop_str, interval, str(save_dir)
        )
    except Exception as error:
        raise RuntimeError(
            f"Failed to fetch media for camera={camera_name!r} product={product_name!r} "
            f"window=[{start_str}, {stop_str}]: {error}"
        ) from error

    return [Path(f) for f in filenames]


if __name__ == "__main__":
    client = get_client(verbose=True)
    cameras = discover_cameras(client)
    print(f"Found {len(cameras)} cameras in {DEFAULT_REGION_SUFFIXES}:")
    for camera_name in cameras:
        print(f"\n=== {camera_name} ===")
        try:
            products = list_products(client, camera_name)
        except Exception as error:
            print(f"  could not list products: {error}")
            continue
        for product_name in products:
            try:
                min_date, max_date = get_inventory_range(client, camera_name, product_name)
                print(f"  {product_name}: {min_date} to {max_date}")
            except Exception as error:
                print(f"  {product_name}: inventory unavailable ({error})")
