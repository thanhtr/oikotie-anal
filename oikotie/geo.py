"""Distance math and geocoding against the Nominatim API."""

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional

from oikotie.config import MAJOR_MALLS, TRAM_STOPS, TRANSPORT_HUBS


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_tram_stop(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, slon, slat in TRAM_STOPS:
        d = haversine_m(lat, lon, slat, slon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def nearest_hub(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, hlat, hlon in TRANSPORT_HUBS:
        d = haversine_m(lat, lon, hlat, hlon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def nearest_mall(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, mlat, mlon in MAJOR_MALLS:
        d = haversine_m(lat, lon, mlat, mlon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def geocode_address(address: str, city: str, geo_cache: dict) -> Optional[tuple[float, float]]:
    key = f"{address}, {city}, Finland"
    if key in geo_cache:
        return geo_cache[key]
    # Strip apartment identifier (e.g. "A 12", "B 3") to improve Nominatim match rate.
    street = re.sub(r"\s+[A-Za-z]\s+\d+$", "", address.split(",")[0]).strip()
    params = urllib.parse.urlencode({
        "street": street, "city": city, "countrycodes": "fi",
        "format": "json", "limit": 1,
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "oikotie-ratikka-scraper/1.0 tung@tekai.fi"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data:
                result: tuple[float, float] = (float(data[0]["lat"]), float(data[0]["lon"]))
                geo_cache[key] = result
                return result
            break  # empty result — address not found, don't retry
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s, 120s
                print(f"    geocode 429 — waiting {wait}s before retry …", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    geocode warning: {address}: {exc}", file=sys.stderr)
                break
        except Exception as exc:
            print(f"    geocode warning: {address}: {exc}", file=sys.stderr)
            break
    geo_cache[key] = None
    return None
