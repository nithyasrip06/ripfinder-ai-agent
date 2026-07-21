import re
import time
from typing import Optional

import requests
from pydantic import BaseModel

SRF_URL = "https://forecast.weather.gov/product.php"
CACHE_TTL_SECONDS = 15 * 60  # NWS reissues SRF a couple times a day; matches
                              # the refresh cadence of the user's existing
                              # RipFinder-WebView snapshot service.

_cache: dict[str, tuple[float, "ForecastData"]] = {}


class ForecastData(BaseModel):
    wfo_site: str
    zone_match: str
    zone_label: Optional[str] = None
    issued: Optional[str] = None
    rip_current_risk: Optional[str] = None  # "Low" | "Moderate" | "High" | None
    surf_height: Optional[str] = None
    raw_section: str


def fetch_srf_text(wfo_site: str) -> str:
    response = requests.get(
        SRF_URL,
        params={
            "site": wfo_site,
            "issuedby": wfo_site,
            "product": "SRF",
            "format": "CI",
            "version": 1,
            "glossary": 0,
        },
        timeout=15,
    )
    response.raise_for_status()

    match = re.search(r"<pre[^>]*>(.*?)</pre>", response.text, re.DOTALL)
    if not match:
        raise RuntimeError(f"No SRF product found for site={wfo_site!r} (no <pre> block in response)")

    # Strip embedded glossary <a> tags (and any other markup), keeping inner text.
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


ZONE_CODE_LINE = re.compile(r"^[A-Z]{2,3}Z[\d>-]+$", re.MULTILINE)


def extract_zone_section(full_text: str, zone_match: str) -> Optional[str]:
    # The zone-code line (e.g. "CAZ349-350-161815-") isn't always the first
    # line of a section -- the FIRST zone in a product sits after several
    # lines of WMO/product boilerplate (WMO header, product title, WFO name).
    # Scan for any line shaped like a zone code, anywhere in the section,
    # rather than assuming it's the section's first line.
    pattern = re.compile(re.escape(zone_match))
    for section in full_text.split("$$"):
        for line in ZONE_CODE_LINE.findall(section):
            if pattern.search(line):
                return re.sub(r"\n{3,}", "\n\n", section).strip()
    return None


def parse_zone_section(section: str) -> dict:
    zone_label_match = re.search(r"^[A-Z]{2}Z[\d>-]+-\s*\n(.+?)-\s*$", section, re.MULTILINE)
    issued_match = re.search(r"^\d{3,4} (AM|PM) \w+ .+ \d{4}$", section, re.MULTILINE)
    risk_match = re.search(r"Rip Current Risk\*?\.+(\w+)\.", section)
    surf_match = re.search(r"Surf Height\.+(.+?)\.\s*$", section, re.MULTILINE)
    return {
        "zone_label": zone_label_match.group(1).strip() if zone_label_match else None,
        "issued": issued_match.group(0).strip() if issued_match else None,
        "rip_current_risk": risk_match.group(1).strip() if risk_match else None,
        "surf_height": surf_match.group(1).strip() if surf_match else None,
    }


def get_forecast(wfo_site: str, zone_match: str) -> ForecastData:
    cache_key = f"{wfo_site}:{zone_match}"
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    full_text = fetch_srf_text(wfo_site)
    section = extract_zone_section(full_text, zone_match)
    if section is None:
        raise RuntimeError(f"Zone {zone_match!r} not found in {wfo_site} SRF product")

    forecast = ForecastData(
        wfo_site=wfo_site, zone_match=zone_match, raw_section=section, **parse_zone_section(section)
    )
    _cache[cache_key] = (time.time(), forecast)
    return forecast


def format_forecast_summary(forecast: ForecastData) -> str:
    # reasoning_engine.calculate_risk()'s forecast rule does a plain substring
    # match for "rip current"/"high surf"/"advisory" -- so those phrases must
    # only appear here when genuinely true, or every forecast (even a calm
    # one) would trip the rule. NWS also doesn't always include a Rip Current
    # Risk line at all (e.g. MTR/Santa Cruz often omits it even with big surf).
    parts = []
    if forecast.zone_label:
        parts.append(f"{forecast.zone_label}.")
    if forecast.surf_height:
        parts.append(f"Surf height {forecast.surf_height}.")
    if forecast.rip_current_risk:
        parts.append(f"NOAA rip current risk: {forecast.rip_current_risk}.")
    else:
        parts.append("No elevated ocean hazard flagged by NOAA for this zone at this time.")
    return " ".join(parts)


if __name__ == "__main__":
    import sys

    site = sys.argv[1] if len(sys.argv) > 1 else "LOX"
    zone = sys.argv[2] if len(sys.argv) > 2 else "340"
    data = get_forecast(site, zone)
    print(data.model_dump_json(indent=2))
    print("\nSummary:", format_forecast_summary(data))
