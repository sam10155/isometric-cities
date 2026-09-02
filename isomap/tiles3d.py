"""Google Photorealistic 3D Tiles client — cache-first, budget-counted.

Every network request goes through ApiBudget.spend() BEFORE it is made; every
response is cached permanently on disk, and cache hits cost nothing. A per-run
max_requests guard bounds any single operation independently of the monthly cap.

API shape (Map Tiles API, 3D Tiles):
- GET https://tile.googleapis.com/v1/3dtiles/root.json?key=KEY
  -> tileset JSON. Child content URIs include a session token that must be
     propagated (plus the key) on all subsequent requests.
- Tileset JSONs form a hierarchy: a tile's `content.uri` is either another
  .json (external tileset to fetch) or a .glb (mesh to fetch).
- Tiles carry `boundingVolume.region` = [west, south, east, north, min_h,
  max_h] (radians, WGS84) and a `geometricError` (meters); traversal descends
  while the error is above target and the region intersects the area of
  interest.

Billing calibration (open question in the plan): we count every network
request as 1 against the budget — the conservative assumption. Compare our
counter with the Google console after the first probe; if only root.json
requests are billed, our counter simply over-protects.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .apibudget import ApiBudget, api_key, tile_cache_dir

ROOT_URL = "https://tile.googleapis.com/v1/3dtiles/root.json"
BASE = "https://tile.googleapis.com"


@dataclass
class FetchStats:
    network_requests: int = 0
    cache_hits: int = 0
    bytes_fetched: int = 0


class RequestLimitReached(RuntimeError):
    pass


@dataclass
class Region:
    """WGS84 bounding region in degrees (converted from the API's radians)."""

    west: float
    south: float
    east: float
    north: float
    min_h: float = 0.0
    max_h: float = 0.0

    @classmethod
    def from_radians(cls, r: list[float]) -> "Region":
        return cls(
            west=math.degrees(r[0]),
            south=math.degrees(r[1]),
            east=math.degrees(r[2]),
            north=math.degrees(r[3]),
            min_h=r[4] if len(r) > 4 else 0.0,
            max_h=r[5] if len(r) > 5 else 0.0,
        )

    def intersects(self, other: "Region") -> bool:
        return not (
            self.east < other.west
            or other.east < self.west
            or self.north < other.south
            or other.north < self.south
        )

_WGS84_A = 6378137.0
_WGS84_E2 = 6.69437999014e-3


def _ecef_to_lonlat(x: float, y: float, z: float) -> tuple[float, float]:
    """ECEF meters -> (lon, lat) degrees. Iterative geodetic latitude; plenty
    accurate for bounding-volume pruning."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - _WGS84_E2))
    for _ in range(5):
        sin_lat = math.sin(lat)
        n = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin_lat * sin_lat)
        lat = math.atan2(z + _WGS84_E2 * n * sin_lat, p)
    return math.degrees(lon), math.degrees(lat)


def _lonlat_to_ecef(lon: float, lat: float, h: float = 0.0) -> tuple[float, float, float]:
    lon_r, lat_r = math.radians(lon), math.radians(lat)
    sin_lat, cos_lat = math.sin(lat_r), math.cos(lat_r)
    n = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin_lat * sin_lat)
    return (
        (n + h) * cos_lat * math.cos(lon_r),
        (n + h) * cos_lat * math.sin(lon_r),
        (n * (1 - _WGS84_E2) + h) * sin_lat,
    )


def sphere_intersects_obb(
    center: tuple[float, float, float], radius: float, box: list[float]
) -> bool:
    """Sphere vs 3D Tiles oriented bounding box, in ECEF meters.

    box = [cx, cy, cz, x half-axis (3), y half-axis (3), z half-axis (3)].
    Project the sphere center onto each (possibly non-unit) axis, clamp to the
    half-extent, and compare the closest point's distance to the radius.
    Exact for OBBs — no lon/lat approximation, works at every tile scale
    (Google's root boxes are planet-sized; corner-sampled lon/lat AABBs
    collapse to +-35 deg latitude and wrongly prune everything poleward).
    """
    c = box[0:3]
    d = (center[0] - c[0], center[1] - c[1], center[2] - c[2])
    closest = list(c)
    for axis in (box[3:6], box[6:9], box[9:12]):
        length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
        if length == 0:
            continue
        u = (axis[0] / length, axis[1] / length, axis[2] / length)
        dist = d[0] * u[0] + d[1] * u[1] + d[2] * u[2]
        dist = max(-length, min(length, dist))
        closest[0] += dist * u[0]
        closest[1] += dist * u[1]
        closest[2] += dist * u[2]
    dx = center[0] - closest[0]
    dy = center[1] - closest[1]
    dz = center[2] - closest[2]
    return dx * dx + dy * dy + dz * dz <= radius * radius


def target_spheres(
    target: Region, max_h: float = 650.0, step: float = 150.0
) -> list[tuple[tuple[float, float, float], float]]:
    """Cover the target's vertical extent with a stack of small spheres.

    A single bounding sphere padded 0..650 m tall has lateral reach ~= its
    radius (~400 m for a 128 m quadrant) and over-fetches a ~6-quadrant-wide
    disc. A stack of spheres every `step` metres keeps lateral reach to the
    footprint half-diagonal + step/2 (~165 m) — ~4x fewer billable fetches.
    max_h 650 covers Toronto terrain (~75 m ASL) + CN Tower (553 m).
    """
    lon_c = (target.west + target.east) / 2
    lat_c = (target.south + target.north) / 2
    corner = _lonlat_to_ecef(target.west, target.south, 0.0)
    base = _lonlat_to_ecef(lon_c, lat_c, 0.0)
    half_diag = math.dist(base, corner)
    radius = math.hypot(half_diag, step / 2) * 1.05
    spheres = []
    h = step / 2
    while h < max_h + step / 2:
        spheres.append((_lonlat_to_ecef(lon_c, lat_c, h), radius))
        h += step
    return spheres


def tile_intersects(tile: dict, target: Region) -> bool:
    """Does this tile's boundingVolume intersect the target region?

    `region` volumes: lon/lat box test. `box` volumes: exact ECEF
    sphere-vs-OBB test against the target's bounding sphere. No volume: assume
    intersecting (safe: descend)."""
    bv = tile.get("boundingVolume", {})
    if "region" in bv:
        return Region.from_radians(bv["region"]).intersects(target)
    if "box" in bv:
        return any(
            sphere_intersects_obb(center, radius, bv["box"])
            for center, radius in target_spheres(target)
        )
    return True


@dataclass
class MeshTile:
    """A collected leaf: a .glb mesh whose bounding volume intersects the target."""

    uri: str
    geometric_error: float
    cache_path: Path | None = None


class Tiles3dClient:
    def __init__(
        self,
        city_name: str,
        budget: ApiBudget | None = None,
        max_requests: int = 10,
    ):
        self.cache_dir = tile_cache_dir(city_name)
        self.budget = budget or ApiBudget()
        self.max_requests = max_requests
        self.stats = FetchStats()
        self._session: str | None = None
        # fetch workers overlap request latency; counters/budget/session are
        # serialized under locks so accounting is identical to a serial run
        self.fetch_workers = 12
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._session_gen = 0

    # -- low-level fetch with cache + budget --

    def _cache_path(self, url: str, cache_key: str | None = None) -> Path:
        """Cache location for a URL.

        cache_key overrides URL-based keying. Needed for tileset JSONs: their
        URL paths embed the session and change on every session refresh, so we
        key them by tree position (e.g. 'json:root.3.0.0.3') instead. Mesh
        .glb paths are stable across sessions and key by URL path.
        """
        parsed = urllib.parse.urlparse(url)
        key = cache_key or parsed.path
        h = hashlib.sha1(key.encode()).hexdigest()[:16]
        suffix = Path(parsed.path).suffix or ".json"
        return self.cache_dir / f"{h}{suffix}"

    def _fetch(self, url: str, cache_key: str | None = None) -> bytes:
        cache = self._cache_path(url, cache_key)
        if cache.exists():
            with self._lock:
                self.stats.cache_hits += 1
            return cache.read_bytes()

        # spend BEFORE the request; raises BudgetExceeded if it would breach.
        # Sessions (root.json fetches) are the assumed-billable unit; raw
        # requests are tracked as a diagnostic backstop. The lock keeps
        # counter accounting exact when fetch workers run concurrently.
        with self._lock:
            if self.stats.network_requests >= self.max_requests:
                raise RequestLimitReached(
                    f"per-run limit of {self.max_requests} network requests reached "
                    f"(stats: {self.stats})"
                )
            if cache_key == "json:root":
                self.budget.spend(1, api="map_tiles_session")
            self.budget.spend(1)
            self.stats.network_requests += 1

        req = urllib.request.Request(url, headers={"User-Agent": "isomap/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with self._lock:
            self.stats.bytes_fetched += len(data)
        cache.write_bytes(data)
        return data

    def _fetch_uri(self, uri: str, cache_key: str | None = None) -> bytes:
        """Fetch a tile URI; on an expired/invalid session (the API answers
        400/401/403/404 depending on how the token failed), refresh the
        session once and retry. Cache hits never touch the network.

        Session-generation counter: when many workers hit the expiry at once,
        only the first refreshes (a refresh costs a billable session); the
        rest just retry with the already-fresh token."""
        gen = self._session_gen
        try:
            return self._fetch(self._url(uri), cache_key)
        except urllib.error.HTTPError as e:
            if e.code not in (400, 401, 403, 404):
                raise
            with self._refresh_lock:
                if self._session_gen == gen:
                    self.refresh_session()
                    self._session_gen += 1
            return self._fetch(self._url(uri), cache_key)

    def _url(self, uri: str) -> str:
        """Absolutize a tile URI and attach key + session."""
        if uri.startswith("http"):
            url = uri
        else:
            url = BASE + (uri if uri.startswith("/") else "/" + uri)
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "session" in params and self._session is None:
            self._session = params["session"]
        if self._session:
            # ALWAYS override: cached tileset JSONs carry expired session
            # tokens baked into their content URIs.
            params["session"] = self._session
        params["key"] = api_key()
        return parsed._replace(query=urllib.parse.urlencode(params)).geturl()

    def refresh_session(self) -> None:
        """Re-fetch root.json bypassing cache to obtain a fresh session token
        (sessions last ~3h). Costs 1 request."""
        self._session = None
        url = self._url(ROOT_URL)
        self._cache_path(url, "json:root").unlink(missing_ok=True)
        root = json.loads(self._fetch(url, cache_key="json:root"))
        # session token appears on child content URIs
        stack = [root["root"]]
        while stack and self._session is None:
            t = stack.pop()
            uri = (t.get("content") or {}).get("uri", "")
            q = urllib.parse.urlparse(uri).query
            params = dict(urllib.parse.parse_qsl(q))
            if "session" in params:
                self._session = params["session"]
                break
            stack.extend(t.get("children") or [])

    # -- tileset traversal --

    def fetch_root(self) -> dict:
        return json.loads(self._fetch(self._url(ROOT_URL), cache_key="json:root"))

    def collect_meshes(
        self,
        target: Region,
        target_error: float = 8.0,
    ) -> list[MeshTile]:
        """Traverse the tileset, descending into tiles that intersect `target`
        until geometricError <= target_error, collecting .glb leaves.

        Fetches (budget-counted) only the tileset JSONs and glbs actually
        needed. Raises RequestLimitReached/BudgetExceeded rather than
        overrunning; everything fetched before the stop remains cached, so a
        re-run resumes for free.
        """
        root = self.fetch_root()
        meshes: list[MeshTile] = []
        # stack carries (tile, tree_path); tree paths are session-stable and
        # key the tileset-JSON cache
        stack: list[tuple[dict, str]] = [(root["root"], "root")]

        while stack:
            tile, path = stack.pop()
            if not tile_intersects(tile, target):
                continue

            err = float(tile.get("geometricError", 0.0))
            content_uri = (tile.get("content") or {}).get("uri", "")
            # suffix must ignore the ?session=... query string on content URIs
            content_kind = Path(urllib.parse.urlparse(content_uri).path).suffix
            children = tile.get("children") or []

            if content_kind == ".json":
                sub = json.loads(self._fetch_uri(content_uri, cache_key=f"json:{path}"))
                # '.j' marker: a chained external tileset at the same tree
                # node must not reuse its parent's cache key
                stack.append((sub["root"], f"{path}.j"))
                continue

            if content_kind == ".glb" and (err <= target_error or not children):
                # collect now, fetch in parallel below: glbs are ~all of the
                # request volume and independent, so overlapping their
                # latency is the whole speedup
                meshes.append(
                    MeshTile(
                        uri=content_uri,
                        geometric_error=err,
                        cache_path=self._cache_path(self._url(content_uri)),
                    )
                )
                continue

            stack.extend(
                (child, f"{path}.{i}") for i, child in enumerate(children)
            )

        with ThreadPoolExecutor(max_workers=self.fetch_workers) as pool:
            # list() drains the iterator so the first worker error
            # (RequestLimitReached/BudgetExceeded) propagates here
            list(pool.map(lambda m: self._fetch_uri(m.uri), meshes))

        return meshes
