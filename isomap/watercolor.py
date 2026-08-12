"""Water color normalization (the NYC v2 lesson, adapted).

Each generation renders open water in a slightly different blue; boundaries
between generations become visible exactly where everything else is flat
(first seen: seam ratio 1.10 at the eastern harbour, 2026-08-12). Fix: snap
water pixels to ONE canonical blue while preserving dither texture.

Mechanism:
- Water mask in screen space: OSM water rings (cities/<city>/water.json)
  projected through the ScreenFrame and polygon-filled per tile. Boats, docks
  and bridges render over water, so the mask alone is not enough --
- Only pixels chromatically close to the tile's own median water color are
  corrected (boats/docks are color outliers and stay untouched).
- Correction translates the local water distribution to the canonical color
  (out = canonical + (pixel - local_median)), preserving dither patterns.

  python -m isomap.watercolor canonical   # compute+store from founding water
  python -m isomap.watercolor normalize   # normalize every committed tile
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .config import CityConfig, load_city
from .render import ScreenFrame
from .store import QuadrantStore
from .tilelib import QState

P = 512
COLOR_TOL = 42.0  # max RGB distance from local water median to be "water pixel"


def canonical_path(city: CityConfig) -> Path:
    return city.city_dir / "water_color.json"


_RINGS_PX: list | None = None  # rings projected to global screen px, once per run


def _rings_screen_px(frame: ScreenFrame, data: dict) -> list:
    """Project all water rings to global screen pixels ONCE (vectorized).
    Per-tile masking then only translates coordinates — the per-tile,
    per-vertex inverse projection was the normalize hot spot."""
    global _RINGS_PX
    if _RINGS_PX is not None:
        return _RINGS_PX
    from .tiles3d import _lonlat_to_ecef

    # Lake Ontario surface: ~74.8 m orthometric + Toronto geoid offset ~-36 m
    # = ~38.6 m ELLIPSOIDAL. Projecting rings at h=0 displaces the mask
    # ~130 px down-screen — with destructive repaint that painted water over
    # the airport island's lake edge (user-caught, 2026-08-12).
    WATER_ELLIPSOIDAL_H = 38.6

    def project(rings):
        out = []
        for ring in rings:
            ecef = np.array([_lonlat_to_ecef(lon, lat, WATER_ELLIPSOIDAL_H)
                             for lon, lat in ring])
            s = frame.ecef_to_screen(ecef)
            pts = np.column_stack([s[:, 0], s[:, 1]]) * frame.px_per_m
            out.append((pts.min(axis=0), pts.max(axis=0), pts))
        return out

    _RINGS_PX = (project(data["polygons"]), project(data.get("holes", [])))
    return _RINGS_PX


def tile_water_mask(frame: ScreenFrame, ti: int, tj: int, data: dict) -> np.ndarray:
    """Boolean (P,P) mask of OSM-water ground area within one screen tile.
    Island holes (inner rings) are subtracted — the airport taxiways were
    tinted blue when the Toronto Islands hole was missing. Cached on disk."""
    cache_dir = frame.city.city_dir / "water_masks"
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / f"t{ti}_{tj}.png"
    if cached.exists():
        return np.asarray(Image.open(cached)) > 127

    x0, y0 = ti * P, tj * P  # tile origin in global screen px
    img = Image.new("L", (P, P), 0)
    d = ImageDraw.Draw(img)
    outers, holes = _rings_screen_px(frame, data)
    for fill, rings in ((255, outers), (0, holes)):
        for mins, maxs, pts in rings:
            if maxs[0] < x0 - 50 or mins[0] > x0 + P + 50 or \
               maxs[1] < y0 - 50 or mins[1] > y0 + P + 50:
                continue
            local = [(px - x0, py - y0) for px, py in pts]
            if len(local) >= 3:
                d.polygon(local, fill=fill)
    img.save(cached)
    return np.asarray(img) > 127


def _tile_water_stats(tile: np.ndarray, mask: np.ndarray):
    """Median color of plausible water pixels (mask + blue-ish filter)."""
    if mask.sum() < 500:
        return None
    px = tile[mask]
    bluish = (px[:, 2] > px[:, 0]) & (px[:, 2] > 80)
    if bluish.sum() < 300:
        return None
    return np.median(px[bluish], axis=0)


def cmd_canonical(args) -> None:
    city = load_city(args.city)
    frame = ScreenFrame(city)
    data = json.loads((city.city_dir / "water.json").read_text())
    # founding water window: tiles (180,14)-(183,16) (first approved water)
    meds = []
    for ti in range(180, 184):
        for tj in range(14, 17):
            f = city.city_dir / "map_tiles" / f"t{ti}_{tj}.png"
            if not f.exists():
                continue
            tile = np.asarray(Image.open(f).convert("RGB"), dtype=float)
            m = tile_water_mask(frame, ti, tj, data)
            st = _tile_water_stats(tile, m)
            if st is not None:
                meds.append(st)
    canon = np.median(np.array(meds), axis=0)
    canonical_path(city).write_text(json.dumps({"rgb": [round(float(v), 1) for v in canon]}))
    print(f"canonical water color: {canon.round(1).tolist()} (from {len(meds)} tiles)")


def normalize_tile(city: CityConfig, frame: ScreenFrame, data: dict,
                   canon: np.ndarray, ti: int, tj: int) -> bool:
    f = city.city_dir / "map_tiles" / f"t{ti}_{tj}.png"
    if not f.exists():
        return False
    tile = np.asarray(Image.open(f).convert("RGB"), dtype=float)
    mask = tile_water_mask(frame, ti, tj, data)
    med = _tile_water_stats(tile, mask)
    if med is None:
        return False
    from PIL import ImageFilter

    shift = canon - med
    dist = np.abs(tile - med).sum(axis=2)
    # rim: strict color test (near shore, docks, boats close by)
    target_rim = mask & (dist < COLOR_TOL)
    # interior of the water polygon (eroded 24px): only boats are non-water
    # there, and they sit far away in color space — use a wide tolerance so
    # drifted bands/gradients are still corrected
    pmask = Image.fromarray((mask * 255).astype(np.uint8))
    interior = (np.asarray(pmask.filter(ImageFilter.MinFilter(49))) > 127) & (dist < 130)
    if target_rim.sum() + interior.sum() < 500:
        return False
    out = tile.copy()
    out[target_rim] = np.clip(tile[target_rim] + shift, 0, 255)
    # interior: PROCEDURAL REPAINT. Correcting each generation's water toward
    # canonical left a patchwork — the dither PATTERNS differ, not just the
    # colors. Interior open water is replaced wholesale with canonical blue +
    # a deterministic dither keyed to GLOBAL pixel coords, so water is
    # byte-identical across tiles and generations. Boats/docks (color
    # outliers) and the 24px shore ring keep their generated art.
    if interior.sum() > 500:
        gx = np.arange(P) + ti * P
        gy = (np.arange(P) + tj * P)[:, None]
        water = np.empty((P, P, 3))
        water[:] = canon
        # subtle 2x2 checker shading
        checker = (((gx // 2) + (gy // 2)) % 2).astype(float) * 3.0
        water += checker[:, :, None]
        # sparse lighter flecks (deterministic hash), ~1.5% of 2x2 cells
        h = ((gx // 2) * 73856093) ^ ((gy // 2) * 19349663)
        fleck = ((h % 997) < 15).astype(float) * 26.0
        water += fleck[:, :, None]
        out[interior] = np.clip(water[interior], 0, 255)
    Image.fromarray(out.astype(np.uint8)).save(f)
    return True


def cmd_normalize(args) -> None:
    city = load_city(args.city)
    frame = ScreenFrame(city)
    data = json.loads((city.city_dir / "water.json").read_text())
    canon = np.array(json.loads(canonical_path(city).read_text())["rgb"])
    with QuadrantStore(city.db_path) as store:
        coords = sorted(store.load_grid_state().quadrants(QState.GENERATED))
    if args.rect:
        r = args.rect
        coords = [(ti, tj) for ti, tj in coords
                  if r[0] <= ti <= r[2] and r[1] <= tj <= r[3]]
    n = 0
    for ti, tj in coords:
        if normalize_tile(city, frame, data, canon, ti, tj):
            n += 1
    print(f"normalized water in {n}/{len(coords)} tiles")
    # always rebuild map+pyramid here — callers (window/repair commit) rely on
    # this being the ONE rebuild, whether or not water changed
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(repo / "tools" / "assemble_map.py")], check=True)
    subprocess.run([sys.executable, str(repo / "tools" / "build_pyramid.py")], check=True)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="isomap.watercolor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, fn in [("canonical", cmd_canonical), ("normalize", cmd_normalize)]:
        sp = sub.add_parser(cmd)
        sp.add_argument("city", nargs="?", default="toronto")
        if cmd == "normalize":
            sp.add_argument("--rect", type=int, nargs=4, default=None,
                            metavar=("TI0", "TJ0", "TI1", "TJ1"),
                            help="only normalize tiles in this window")
        sp.set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
