# Maps each WebCOOS camera (as returned by webcoos_client.discover_cameras)
# to the NWS Weather Forecast Office + zone that issues its Surf Zone
# Forecast (SRF) -- the product agent/noaa_forecast.py fetches. Verified by
# curling forecast.weather.gov/product.php?product=SRF for each office and
# matching zone labels against each camera's actual location.
#
# (wfo_site, zone_match): zone_match is any substring unique to that zone's
# code within the office's SRF product (offices often merge several zone
# codes into one shared forecast section).
STATION_CONFIG: dict[str, tuple[str, str]] = {
    "Humboldt Bay, Arcata, CA": ("EKA", "103"),  # Northern Humboldt Coast
    "Carpinteria State Beach, CA": ("LOX", "350"),  # Santa Barbara County Southeastern Coast
    "Beachfront at Cocoa Beach, FL": ("MLB", "347"),  # Northern Brevard Barrier Islands
    "Crescent City, CA": ("EKA", "101"),  # Coastal Del Norte
    "Jupiter Inlet, FL": ("MFL", "168"),  # Coastal Palm Beach
    "40th Street beachfront, Miami, FL": ("MFL", "173"),  # Coastal Miami-Dade
    "Santa Cruz Wharf at Santa Cruz, CA": ("MTR", "529"),  # Santa Cruz County Coastal Areas
    "St. Augustine Beach Pier, St. Augustine, FL": ("JAX", "233"),  # St. Johns County
    "Point Reyes National Seashore, Point Reyes, CA": ("MTR", "505"),  # Sonoma and Marin County Coastal Areas
    "Twin Piers, Bradenton, FL": ("TBW", "155"),  # Coastal Manatee
    "Beachfront, Waikiki, HI": ("HFO", "006"),  # Oahu
    "Walton Lighthouse, Santa Cruz, CA": ("MTR", "529"),  # Santa Cruz County Coastal Areas
}
