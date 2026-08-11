"""Assemble all committed map tiles into the current map image.

Reads cities/<city>/map_tiles/q<qx>_<qy>.png for every GENERATED quadrant in
the DB, stitches them onto a canvas, writes debug/map/toronto_map.png plus a
small overview. Run after every commit; the debug hub links the result.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from isomap.config import load_city
from isomap.store import QuadrantStore
from isomap.tilelib import QState

P = 512  # canonical stylized tile edge

city = load_city("toronto")
tiles_dir = city.city_dir / "map_tiles"

with QuadrantStore(city.db_path) as store:
    gs = store.load_grid_state()
coords = sorted(gs.quadrants(QState.GENERATED))
if not coords:
    sys.exit("no generated quadrants")

xs = [q[0] for q in coords]
ys = [q[1] for q in coords]
min_qx, max_qx, min_qy, max_qy = min(xs), max(xs), min(ys), max(ys)
W, H = (max_qx - min_qx + 1) * P, (max_qy - min_qy + 1) * P
canvas = Image.new("RGB", (W, H), (24, 24, 24))
missing = []
for qx, qy in coords:
    f = tiles_dir / f"t{qx}_{qy}.png"
    if not f.exists():
        missing.append((qx, qy))
        continue
    tile = Image.open(f).convert("RGB")
    if tile.size != (P, P):
        tile = tile.resize((P, P), Image.LANCZOS)
    canvas.paste(tile, ((qx - min_qx) * P, (qy - min_qy) * P))

out = Path("debug/map")
out.mkdir(parents=True, exist_ok=True)
canvas.save(out / "toronto_map.png")
ov = canvas.copy()
ov.thumbnail((1024, 1024), Image.LANCZOS)
ov.save(out / "toronto_map_overview.png")
print(f"map: {len(coords)} quadrants, ({min_qx},{min_qy})..({max_qx},{max_qy}), "
      f"{W}x{H}px{'; MISSING TILES: ' + str(missing) if missing else ''}")
