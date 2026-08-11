"""Render the full 4x4 downtown block (122-125, 69-72) from the manifest.
Offline — zero API requests. Writes the block image + per-quadrant crops."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isomap.config import load_city
from isomap.render import crop_quadrant, render_block

BLOCK = (122, 69, 125, 72)

city = load_city("toronto")
glbs = [Path(p) for p in json.loads(
    Path("cities/toronto/manifests/block_122_69_125_72_err4.json").read_text())]
print(f"rendering block {BLOCK} from {len(glbs)} meshes", flush=True)

img = render_block(city, *BLOCK, glbs, supersample=1)
out = Path("debug/renders")
img.save(out / "toronto_block_122_69-125_72.png")
print("saved block image", flush=True)

for qy in range(BLOCK[1], BLOCK[3] + 1):
    for qx in range(BLOCK[0], BLOCK[2] + 1):
        crop_quadrant(city, img, BLOCK[0], BLOCK[1], qx, qy).save(
            out / f"toronto_q{qx}_{qy}.png")
print("saved 16 quadrant crops", flush=True)
