"""Render the cached east-column strip (125, 69-72) as one seamless image.

Offline: uses only cached meshes, zero API requests. Writes the strip plus
per-quadrant crops to debug/renders/.
"""

import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isomap.config import load_city
from isomap import gridlib
from isomap.render import crop_quadrant, render_block
from isomap.tiles3d import Region, tile_intersects

CACHE = Path("cities/toronto/tile_cache")
STRIP = (125, 69, 125, 72)  # min_qx, min_qy, max_qx, max_qy


def nk(k: str) -> str:
    return hashlib.sha1(k.encode()).hexdigest()[:16]


def cached_meshes(city, target: Region) -> set[Path]:
    root = json.loads((CACHE / (nk("json:root") + ".json")).read_text())
    have: set[Path] = set()
    stack = [(root["root"], "root")]
    while stack:
        t, p = stack.pop()
        if not tile_intersects(t, target):
            continue
        uri = (t.get("content") or {}).get("uri", "")
        upath = urllib.parse.urlparse(uri).path
        kids = t.get("children") or []
        if upath.endswith(".json"):
            f = CACHE / (nk(f"json:{p}") + ".json")
            if f.exists():
                stack.append((json.loads(f.read_text())["root"], f"{p}.j"))
            continue
        if upath.endswith(".glb") and (
            float(t.get("geometricError", 0)) <= 8.0 or not kids
        ):
            f = CACHE / (hashlib.sha1(upath.encode()).hexdigest()[:16] + ".glb")
            if f.exists():
                have.add(f)
            continue
        stack.extend((c, f"{p}.{i}") for i, c in enumerate(kids))
    return have


def main() -> None:
    city = load_city("toronto")
    w, s, e, n = gridlib.quadrant_rect_lonlat_region(city, *STRIP, margin_m=256.0)
    glbs = sorted(cached_meshes(city, Region(west=w, south=s, east=e, north=n)))
    print(f"rendering strip {STRIP} from {len(glbs)} cached meshes", flush=True)

    img = render_block(city, *STRIP, glbs, supersample=1)
    out = Path("debug/renders")
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / "toronto_strip_125_69-72.png")
    print("saved strip", flush=True)

    for qy in range(STRIP[1], STRIP[3] + 1):
        tile = crop_quadrant(city, img, STRIP[0], STRIP[1], STRIP[0], qy)
        tile.save(out / f"toronto_q125_{qy}.png")
    print("saved per-quadrant crops", flush=True)


if __name__ == "__main__":
    main()
