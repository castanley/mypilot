"""Offline reverse geocoding: nearest city to a lat/lon, from a bundled GeoNames cities1000 dataset.

Fully offline — the dataset ships in the image (app/geodata/cities1000.tsv.gz); NO outbound network
call is ever made (matches the no-outbound-secrets posture: no live geocode API, no SSRF/cost/latency
surface). The data is GeoNames cities1000 (cities with population >= 1000), reduced to
name/lat/lon/country/admin1 and gzipped (~2.4 MB). GeoNames is licensed CC-BY 4.0 — see the
attribution in docs/about.md.

Lookup is a nearest-neighbour by great-circle distance. To avoid scanning all ~170k cities per call,
cities are indexed into 1-degree longitude bins; a query scans only its own bin plus the neighbouring
bins within the current best radius. Pure stdlib (no numpy/scipy dependency). The dataset loads once
lazily and is cached for the process."""

from __future__ import annotations

import gzip
import math
import os
from functools import lru_cache

_DATASET = os.path.join(os.path.dirname(__file__), "geodata", "cities1000.tsv.gz")
_EARTH_M = 6_371_000.0
_LON_BIN = 1.0  # degrees per longitude bucket


class _City:
    __slots__ = ("name", "lat", "lon", "country", "admin1")

    def __init__(self, name: str, lat: float, lon: float, country: str, admin1: str):
        self.name = name
        self.lat = lat
        self.lon = lon
        self.country = country
        self.admin1 = admin1


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.pi / 180.0
    dlat = (lat2 - lat1) * r
    dlon = (lon2 - lon1) * r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(min(1.0, a)))


@lru_cache(maxsize=1)
def _index() -> dict[int, list[_City]]:
    """Load the dataset once into {lon_bin: [cities]}. Empty dict if the file is absent (geocoding
    then simply returns None — a missing dataset degrades to "no city", never an error)."""
    bins: dict[int, list[_City]] = {}
    try:
        with gzip.open(_DATASET, "rt", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                name, lat_s, lon_s, country, admin1 = parts[0], parts[1], parts[2], parts[3], parts[4]
                try:
                    lat, lon = float(lat_s), float(lon_s)
                except ValueError:
                    continue
                bins.setdefault(int(math.floor(lon / _LON_BIN)), []).append(
                    _City(name, lat, lon, country, admin1)
                )
    except (OSError, EOFError):
        return {}
    return bins


def nearest_city(lat: float | None, lon: float | None, *, max_km: float = 100.0) -> str | None:
    """Return a human label ("City" or "City, ST" for US) for the city nearest to (lat, lon), or None
    when there's no fix, no dataset, or nothing within ``max_km`` (open ocean / remote area — better
    to show nothing than a city 300 km away). Scans the query's longitude bin outward until the bins
    can't hold anything closer than the current best."""
    if lat is None or lon is None:
        return None
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    bins = _index()
    if not bins:
        return None

    center = int(math.floor(lon / _LON_BIN))
    best: _City | None = None
    best_m = float("inf")
    # Expand the longitude window outward. Stop once the nearest possible city in the next ring
    # (its bin edge, in metres at this latitude) can't beat the current best.
    m_per_deg_lon = 111_320.0 * max(math.cos(math.radians(lat)), 1e-6)
    for ring in range(0, 181):  # up to the whole globe, but breaks out almost immediately in practice
        edge_m = (ring - 1) * _LON_BIN * m_per_deg_lon
        if best is not None and edge_m > best_m:
            break
        touched = False
        for b in ({center - ring, center + ring} if ring else {center}):
            for c in bins.get(b, ()):
                touched = True
                d = _haversine_m(lat, lon, c.lat, c.lon)
                if d < best_m:
                    best_m, best = d, c
        # if we've wrapped past all populated bins and found nothing new for a while, the edge test
        # above will terminate; `touched` avoids an infinite empty scan on a sparse hemisphere.
        if ring > 3 and not touched and best is not None:
            break

    if best is None or best_m > max_km * 1000.0:
        return None
    # US cities get "City, ST" (admin1 = the 2-letter state); elsewhere just the city name to avoid
    # showing opaque numeric admin codes.
    if best.country == "US" and best.admin1 and best.admin1.isalpha() and len(best.admin1) == 2:
        return f"{best.name}, {best.admin1}"
    return best.name
