"""Overlay the water mask (red) on committed map tiles for visual QA.

  .venv/bin/python tools/water_mask_debug.py <ti0> <tj0> <ti1> <tj1> [out.png]

Writes a sheet to debug/renders/water_mask_debug.png by default. Use whenever
water normalization misbehaves — a red wash over land means the mask is wrong
(missing island holes, misaligned rings, ...).
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isomap.config import load_city
from isomap.render import ScreenFrame
import isomap.watercolor as wc

ti0, tj0, ti1, tj1 = (int(a) for a in sys.argv[1:5])
out_path = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("debug/renders/water_mask_debug.png")

city = load_city("toronto")
frame = ScreenFrame(city)
data = json.loads((city.city_dir / "water.json").read_text())

cols, rows = ti1 - ti0 + 1, tj1 - tj0 + 1
sheet = Image.new("RGB", (cols * 512, rows * 512), (30, 30, 30))
for tj in range(tj0, tj1 + 1):
    for ti in range(ti0, ti1 + 1):
        f = city.city_dir / "map_tiles" / f"t{ti}_{tj}.png"
        if not f.exists():
            continue
        a = np.asarray(Image.open(f).convert("RGB"), dtype=float)
        m = wc.tile_water_mask(frame, ti, tj, data)
        a[m] = a[m] * 0.5 + np.array([255, 0, 0]) * 0.5
        sheet.paste(Image.fromarray(a.astype(np.uint8)),
                    ((ti - ti0) * 512, (tj - tj0) * 512))
sheet.save(out_path)
print(f"wrote {out_path} ({cols}x{rows} tiles)")
