"""One-off recovery: undo water repaint applied with the h=0 offset mask.

The old mask (rings projected at ellipsoidal h=0) sat ~130px down-screen of
the true water surface, so the procedural repaint painted water over land
along some shorelines (notably the airport island's channel edge). This tool
restores, for every committed tile, the pixels that the OLD mask's repaint
region covered but the NEW (h=38.6) mask says are land — sourcing pixels from
the tile's window final (debug/infill/<batch>_final.png), the pre-normalize
authoritative art.

  .venv/bin/python tools/fix_water_offset.py          # dry run (report only)
  .venv/bin/python tools/fix_water_offset.py --apply
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isomap.config import load_city
from isomap.render import ScreenFrame
from isomap.store import QuadrantStore
from isomap.tilelib import QState
from isomap.tiles3d import _lonlat_to_ecef
import isomap.watercolor as wc

P = 512
APPLY = "--apply" in sys.argv

city = load_city("toronto")
frame = ScreenFrame(city)
data = json.loads((city.city_dir / "water.json").read_text())


def rings_at(h):
    def project(rings):
        out = []
        for ring in rings:
            ecef = np.array([_lonlat_to_ecef(lon, lat, h) for lon, lat in ring])
            s = frame.ecef_to_screen(ecef)
            pts = np.column_stack([s[:, 0], s[:, 1]]) * frame.px_per_m
            out.append((pts.min(axis=0), pts.max(axis=0), pts))
        return out

    return project(data["polygons"]), project(data.get("holes", []))


OLD = rings_at(0.0)


def mask_from(rings, ti, tj):
    x0, y0 = ti * P, tj * P
    img = Image.new("L", (P, P), 0)
    d = ImageDraw.Draw(img)
    outers, holes = rings
    for fill, rr in ((255, outers), (0, holes)):
        for mins, maxs, pts in rr:
            if maxs[0] < x0 - 50 or mins[0] > x0 + P + 50 or \
               maxs[1] < y0 - 50 or mins[1] > y0 + P + 50:
                continue
            d.polygon([(px - x0, py - y0) for px, py in pts], fill=fill)
    return img


# batch -> source image + window origin for restoring pixels
def batch_source(batch: str):
    m = re.match(r"w(\d+)_(\d+)_(\d+)_(\d+)$", batch or "")
    if m:
        f = Path(f"debug/infill/{batch}_final.png")
        if f.exists():
            return Image.open(f).convert("RGB"), int(m[1]), int(m[2])
    if batch == "sblock_2026-08-11":
        f = Path("style_refs/toronto_sblock_founding_pixel.png")
        if f.exists():
            return Image.open(f).convert("RGB"), 180, 17
    if batch and batch.startswith("swindow_water"):
        f = Path("debug/infill/swindow_water_final.png")
        if f.exists():
            return Image.open(f).convert("RGB"), 180, 14
    return None


with QuadrantStore(city.db_path) as store:
    rows = store._conn.execute(
        "SELECT qx, qy, batch_id FROM quadrants WHERE state='generated'").fetchall()

fixed = skipped = 0
for ti, tj, batch in sorted(rows):
    old_mask_img = mask_from(OLD, ti, tj)
    old_interior = np.asarray(old_mask_img.filter(ImageFilter.MinFilter(49))) > 127
    if not old_interior.any():
        continue
    new_mask = wc.tile_water_mask(frame, ti, tj, data)  # h=38.6, cached
    damage = old_interior & ~new_mask
    if damage.sum() < 50:
        continue
    src = batch_source(batch)
    if src is None:
        print(f"t{ti}_{tj}: {damage.sum():6d} px damaged, NO SOURCE (batch {batch})")
        skipped += 1
        continue
    img, wti, wtj = src
    ox, oy = (ti - wti) * P, (tj - wtj) * P
    if ox < 0 or oy < 0 or ox + P > img.width or oy + P > img.height:
        print(f"t{ti}_{tj}: outside source bounds (batch {batch})")
        skipped += 1
        continue
    patch = np.asarray(img.crop((ox, oy, ox + P, oy + P)), dtype=np.uint8)
    f = city.city_dir / "map_tiles" / f"t{ti}_{tj}.png"
    tile = np.asarray(Image.open(f).convert("RGB"), dtype=np.uint8).copy()
    tile[damage] = patch[damage]
    print(f"t{ti}_{tj}: restoring {damage.sum():6d} px from {batch}"
          f"{' [APPLIED]' if APPLY else ''}")
    if APPLY:
        Image.fromarray(tile).save(f)
    fixed += 1

print(f"\n{fixed} tiles {'fixed' if APPLY else 'would be fixed'}, {skipped} skipped")
if not APPLY:
    print("dry run — rerun with --apply")
