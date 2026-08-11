"""Grid math: WGS84 <-> city CRS <-> quadrant coordinates.

Conventions (used everywhere downstream — renderer, tilelib, store, viewer):
- Quadrant coordinates (qx, qy) are integer grid indices.
- qx increases eastward, qy increases SOUTHWARD (image/screen convention, so that
  stitching quadrants into an image needs no flips).
- The grid origin (config origin_xy, in CRS meters) is the TOP-LEFT (north-west)
  corner of quadrant (0, 0).
- A quadrant covers [origin_x + qx*M, origin_x + (qx+1)*M) easting and
  (origin_y - (qy+1)*M, origin_y - qy*M] northing, where M = meters_per_quadrant.

Note: the isometric render of a quadrant depicts more than its ground footprint
(tall buildings lean into neighbors). The grid governs *ground* coordinates; the
renderer is responsible for consistent projection so adjacent renders remain
seamless. That is a Phase 1 concern and does not affect this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pyproj import Transformer

from .config import CityConfig


@lru_cache(maxsize=8)
def _transformers(crs: str) -> tuple[Transformer, Transformer]:
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return fwd, inv


@dataclass(frozen=True)
class QuadrantBoundsXY:
    """Ground-plane bounds of a quadrant in city CRS meters."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)


def lonlat_to_xy(city: CityConfig, lon: float, lat: float) -> tuple[float, float]:
    fwd, _ = _transformers(city.crs)
    return fwd.transform(lon, lat)


def xy_to_lonlat(city: CityConfig, x: float, y: float) -> tuple[float, float]:
    _, inv = _transformers(city.crs)
    return inv.transform(x, y)


def xy_to_quadrant(city: CityConfig, x: float, y: float) -> tuple[int, int]:
    """CRS meters -> integer quadrant indices of the quadrant containing the point."""
    g = city.grid
    qx = int((x - g.origin_x) // g.meters_per_quadrant)
    qy = int((g.origin_y - y) // g.meters_per_quadrant)
    return qx, qy


def quadrant_bounds_xy(city: CityConfig, qx: int, qy: int) -> QuadrantBoundsXY:
    g = city.grid
    m = g.meters_per_quadrant
    min_x = g.origin_x + qx * m
    max_y = g.origin_y - qy * m
    return QuadrantBoundsXY(min_x=min_x, min_y=max_y - m, max_x=min_x + m, max_y=max_y)


def lonlat_to_quadrant(city: CityConfig, lon: float, lat: float) -> tuple[int, int]:
    x, y = lonlat_to_xy(city, lon, lat)
    return xy_to_quadrant(city, x, y)


def quadrant_center_lonlat(city: CityConfig, qx: int, qy: int) -> tuple[float, float]:
    cx, cy = quadrant_bounds_xy(city, qx, qy).center
    return xy_to_lonlat(city, cx, cy)


def quadrant_rect_lonlat_region(
    city: CityConfig,
    min_qx: int,
    min_qy: int,
    max_qx: int,
    max_qy: int,
    margin_m: float = 0.0,
) -> tuple[float, float, float, float]:
    """Lon/lat bounds (west, south, east, north) of an inclusive quadrant rect,
    expanded by margin_m metres on every side.

    margin_m matters for fetching: the isometric camera shows tall geometry
    from neighboring quadrants leaning into a quadrant's frame (lean ~
    height/tan(elevation) ~ 1.73x height at 30 deg). Fetch with margin so
    renders have no missing-geometry wedges.
    """
    tl = quadrant_bounds_xy(city, min_qx, min_qy)
    br = quadrant_bounds_xy(city, max_qx, max_qy)
    min_x, max_x = tl.min_x - margin_m, br.max_x + margin_m
    min_y, max_y = br.min_y - margin_m, tl.max_y + margin_m
    lons: list[float] = []
    lats: list[float] = []
    for x, y in [(min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y)]:
        lon, lat = xy_to_lonlat(city, x, y)
        lons.append(lon)
        lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def bbox_lonlat_to_quadrant_range(
    city: CityConfig, bbox: tuple[float, float, float, float]
) -> tuple[int, int, int, int]:
    """(min_lon, min_lat, max_lon, max_lat) -> inclusive (min_qx, min_qy, max_qx, max_qy).

    Samples all four bbox corners because projection can rotate/skew the box.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    corners = [
        (min_lon, min_lat),
        (min_lon, max_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
    ]
    qs = [lonlat_to_quadrant(city, lon, lat) for lon, lat in corners]
    qxs = [q[0] for q in qs]
    qys = [q[1] for q in qs]
    return min(qxs), min(qys), max(qxs), max(qys)
