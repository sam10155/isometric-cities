"""Incremental deep-zoom pyramid on a FIXED coordinate frame.

Replaces assemble-whole-map + rebuild-whole-pyramid (minutes, growing with
map size) with dirty-tile propagation (seconds, constant per window):

- The pyramid canvas is a fixed superset of the city: tiles PYR_ORIGIN ..
  PYR_ORIGIN+PYR_TILES. Growth in ANY direction never shifts coordinates, so
  only changed tiles and their ancestors are recomputed. Empty regions have
  no tile files (OpenSeadragon tolerates missing tiles).
- Full-res level: pyramid tile (c, r) == map tile (PYR_ORIGIN + (c, r)),
  overlap 0. Each level up is the 2x2-child downsample.

  python -m isomap.pyramid update <city> <ti0> <tj0> <ti1> <tj1>
  python -m isomap.pyramid rebuild <city>          # one-time / recovery
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image

from .config import CityConfig, load_city
from .store import QuadrantStore
from .tilelib import QState


def _save_quantized(img: Image.Image, path: Path) -> None:
    """Palette-quantize pyramid tiles: pixel art shrinks to ~40% with no
    visible change (GitHub Pages caps the deploy artifact at 1 GB)."""
    img.quantize(colors=256, method=Image.MEDIANCUT,
                 dither=Image.FLOYDSTEINBERG).save(path, optimize=True)

P = 512
PYR_ORIGIN = (152, 0)      # map-tile coords of pyramid canvas corner
PYR_TILES = (128, 96)      # canvas size in tiles: 65536 x 49152 px
BG = (26, 39, 51)          # viewer background color

REPO = Path(__file__).resolve().parent.parent

CANVAS_W = PYR_TILES[0] * P
CANVAS_H = PYR_TILES[1] * P
MAX_LEVEL = math.ceil(math.log2(max(CANVAS_W, CANVAS_H)))  # full-res DZI level


def city_docs(city: CityConfig) -> Path:
    """Per-city publish dir: docs/<name>/ — cities never share a pyramid."""
    return REPO / "docs" / city.name


def _files(city: CityConfig) -> Path:
    return city_docs(city) / "map_files"


def write_descriptor(city: CityConfig) -> None:
    city_docs(city).mkdir(parents=True, exist_ok=True)
    (city_docs(city) / "map.dzi").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
        f'Format="png" Overlap="0" TileSize="{P}">'
        f'<Size Width="{CANVAS_W}" Height="{CANVAS_H}"/></Image>\n'
    )


def _level_dir(city: CityConfig, level: int) -> Path:
    d = _files(city) / str(level)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tile_path(city: CityConfig, level: int, c: int, r: int) -> Path:
    return _files(city) / str(level) / f"{c}_{r}.png"


def _level_grid(level: int) -> tuple[int, int]:
    scale = 2 ** (MAX_LEVEL - level)
    w = math.ceil(CANVAS_W / scale / P)
    h = math.ceil(CANVAS_H / scale / P)
    return w, h


def update(city: CityConfig, changed: set[tuple[int, int]]) -> int:
    """Propagate changed MAP tiles through the pyramid. Returns tiles written."""
    tiles_dir = city.city_dir / "map_tiles"
    _level_dir(city, MAX_LEVEL)
    written = 0

    # full-res level: copy map tiles into pyramid positions
    dirty: set[tuple[int, int]] = set()
    for ti, tj in changed:
        c, r = ti - PYR_ORIGIN[0], tj - PYR_ORIGIN[1]
        if not (0 <= c < PYR_TILES[0] and 0 <= r < PYR_TILES[1]):
            print(f"WARNING: tile ({ti},{tj}) outside pyramid frame — enlarge "
                  f"PYR_ORIGIN/PYR_TILES and rebuild")
            continue
        src = tiles_dir / f"t{ti}_{tj}.png"
        if src.exists():
            img = Image.open(src).convert("RGB")
            _save_quantized(img, _tile_path(city, MAX_LEVEL, c, r))
            written += 1
            dirty.add((c, r))

    # propagate upward: parent = 2x2 children downsampled
    level = MAX_LEVEL
    while level > 0 and dirty:
        level -= 1
        _level_dir(city, level)
        parents = {(c // 2, r // 2) for c, r in dirty}
        gw, gh = _level_grid(level)
        for c, r in parents:
            if c >= gw or r >= gh:
                continue
            tile = Image.new("RGB", (P, P), BG)
            any_child = False
            for dc in (0, 1):
                for dr in (0, 1):
                    child = _tile_path(city, level + 1, c * 2 + dc, r * 2 + dr)
                    if child.exists():
                        im = Image.open(child).convert("RGB")
                        im = im.resize((im.width // 2 or 1, im.height // 2 or 1),
                                       Image.LANCZOS)
                        tile.paste(im, (dc * (P // 2), dr * (P // 2)))
                        any_child = True
            if any_child:
                # crop to the level's actual canvas extent at the edges
                scale = 2 ** (MAX_LEVEL - level)
                lw = math.ceil(CANVAS_W / scale)
                lh = math.ceil(CANVAS_H / scale)
                tw = min(P, lw - c * P)
                th = min(P, lh - r * P)
                if tw < P or th < P:
                    tile = tile.crop((0, 0, max(tw, 1), max(th, 1)))
                _save_quantized(tile, _tile_path(city, level, c, r))
                written += 1
        dirty = parents

    write_descriptor(city)
    _write_meta(city)
    return written


def _write_meta(city: CityConfig) -> None:
    """Content bounds (pyramid px) for the viewer to fit its home view."""
    with QuadrantStore(city.db_path) as store:
        coords = store.load_grid_state().quadrants(QState.GENERATED)
    if not coords:
        return
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    meta = {
        "x": (min(xs) - PYR_ORIGIN[0]) * P,
        "y": (min(ys) - PYR_ORIGIN[1]) * P,
        "w": (max(xs) - min(xs) + 1) * P,
        "h": (max(ys) - min(ys) + 1) * P,
        "canvas_w": CANVAS_W,
        "canvas_h": CANVAS_H,
        "origin_tile": list(PYR_ORIGIN),
        "tiles": len(coords),
    }
    (city_docs(city) / "map_meta.json").write_text(json.dumps(meta))


def rebuild(city: CityConfig) -> None:
    import shutil

    if _files(city).exists():
        shutil.rmtree(_files(city))
    with QuadrantStore(city.db_path) as store:
        coords = store.load_grid_state().quadrants(QState.GENERATED)
    n = update(city, set(coords))
    print(f"rebuilt pyramid: {n} tiles written across {MAX_LEVEL + 1} levels")


def main() -> None:
    cmd = sys.argv[1]
    city = load_city(sys.argv[2] if len(sys.argv) > 2 else "toronto")
    if cmd == "rebuild":
        rebuild(city)
    elif cmd == "update":
        ti0, tj0, ti1, tj1 = (int(a) for a in sys.argv[3:7])
        changed = {(ti, tj) for ti in range(ti0, ti1 + 1)
                   for tj in range(tj0, tj1 + 1)}
        n = update(city, changed)
        print(f"pyramid: updated {n} tiles")
    else:
        sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
