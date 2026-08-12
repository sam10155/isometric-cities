"""Ground-truth water testing from OpenStreetMap data.

Pixel heuristics can't tell blue-gray rooftops from water (false positive on
w186_14_189_17, 2026-08-11). This module answers "does this ground area
contain water?" from geography:

- natural=coastline ways: Lake Ontario's edge. OSM convention: water lies on
  the RIGHT of the way direction.
- natural=water ways/relations: harbours, rivers, ponds as polygons.

`fetch_water_data()` downloads once from Overpass (free, not Google) into
cities/<name>/water.json; everything after is offline.
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

from .config import CityConfig

# generous City of Toronto bbox (south, west, north, east)
TORONTO_BBOX = (43.55, -79.70, 43.90, -79.05)


def water_path(city: CityConfig) -> Path:
    return city.city_dir / "water.json"


def _stitch_rings(frags: list[list[tuple]]) -> list[list[tuple]]:
    """Assemble way fragments into closed rings by endpoint matching.
    Unclosable leftovers (ring exits the query bbox) are kept as-is closed —
    an approximation that biases toward 'water' only outside the city bbox."""
    frags = [list(f) for f in frags if len(f) >= 2]
    rings = []
    while frags:
        ring = frags.pop()
        while ring[0] != ring[-1]:
            for k, f in enumerate(frags):
                if f[0] == ring[-1]:
                    ring += f[1:]
                elif f[-1] == ring[-1]:
                    ring += f[-2::-1]
                elif f[-1] == ring[0]:
                    ring = f + ring[1:]
                elif f[0] == ring[0]:
                    ring = f[::-1] + ring[1:]
                else:
                    continue
                frags.pop(k)
                break
            else:
                ring.append(ring[0])  # force-close leftover
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def fetch_water_data(city: CityConfig, bbox=TORONTO_BBOX) -> Path:
    query = f"""
[out:json][timeout:90];
(
  way["natural"="coastline"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
  way["natural"="water"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
  relation["natural"="water"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
);
out geom;"""
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=("data=" + urllib.parse.quote(query)).encode(),
        headers={"User-Agent": "isomap/0.1 (personal art project)"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = json.loads(resp.read())

    coastlines: list[list[tuple[float, float]]] = []
    polygons: list[list[tuple[float, float]]] = []
    holes: list[list[tuple[float, float]]] = []
    for el in raw.get("elements", []):
        if el["type"] == "way" and "geometry" in el:
            pts = [(g["lon"], g["lat"]) for g in el["geometry"]]
            if el.get("tags", {}).get("natural") == "coastline":
                coastlines.append(pts)
            elif len(pts) >= 4 and pts[0] == pts[-1]:
                polygons.append(pts)
        elif el["type"] == "relation":
            # outer rings arrive as way fragments — stitch them closed
            # (Lake Ontario is a natural=water multipolygon relation).
            # INNER rings are islands (e.g. the Toronto Islands + airport!) —
            # they must be collected as holes or the island reads as water.
            frags_out = [
                [(g["lon"], g["lat"]) for g in m["geometry"]]
                for m in el.get("members", [])
                if m.get("role") == "outer" and "geometry" in m
            ]
            frags_in = [
                [(g["lon"], g["lat"]) for g in m["geometry"]]
                for m in el.get("members", [])
                if m.get("role") == "inner" and "geometry" in m
            ]
            polygons.extend(_stitch_rings(frags_out))
            holes.extend(_stitch_rings(frags_in))
    out = water_path(city)
    out.write_text(json.dumps(
        {"coastlines": coastlines, "polygons": polygons, "holes": holes}))
    print(f"water data: {len(coastlines)} coastline ways, {len(polygons)} water "
          f"polygons, {len(holes)} island holes")
    return out


def _load(city: CityConfig) -> dict:
    p = water_path(city)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing — run: python -c \"from isomap.config import load_city; "
            f"from isomap.water import fetch_water_data; fetch_water_data(load_city('{city.name}'))\""
        )
    return json.loads(p.read_text())


def _in_polygon(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _lakeward(lon: float, lat: float, coastlines: list, max_deg=0.05) -> bool:
    """True if the nearest coastline segment has this point on its water side
    (OSM: water on the right of way direction). Ignores coastlines farther
    than max_deg (~4-5 km) — inland points then default to land."""
    best_d2 = max_deg * max_deg
    best_side = None
    for way in coastlines:
        for i in range(len(way) - 1):
            (x1, y1), (x2, y2) = way[i], way[i + 1]
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            t = max(0.0, min(1.0, ((lon - x1) * dx + (lat - y1) * dy) / L2))
            px, py = x1 + t * dx, y1 + t * dy
            d2 = (lon - px) ** 2 + (lat - py) ** 2
            if d2 < best_d2:
                best_d2 = d2
                # cross product z: >0 point left of direction (land), <0 right (water)
                best_side = dx * (lat - y1) - dy * (lon - x1)
    return best_side is not None and best_side < 0


def is_water(city: CityConfig, lon: float, lat: float, data: dict | None = None) -> bool:
    data = data or _load(city)
    # islands are holes in the water multipolygon — land, whatever else says
    if any(_in_polygon(lon, lat, ring) for ring in data.get("holes", [])):
        return False
    if _lakeward(lon, lat, data["coastlines"]):
        return True
    return any(_in_polygon(lon, lat, ring) for ring in data["polygons"])


def water_fraction_region(
    city: CityConfig, west: float, south: float, east: float, north: float, n: int = 16
) -> float:
    """Fraction of an n x n lon/lat sample grid that is water (ground truth)."""
    data = _load(city)
    hits = 0
    for i in range(n):
        for j in range(n):
            lon = west + (east - west) * (i + 0.5) / n
            lat = south + (north - south) * (j + 0.5) / n
            if is_water(city, lon, lat, data):
                hits += 1
    return hits / (n * n)
