"""Render the founding block in the corrected global screen frame."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isomap.config import load_city
from isomap.render import ScreenFrame, crop_tile, render_screen_block

city = load_city("toronto")
frame = ScreenFrame(city)
manifest = json.loads(Path("cities/toronto/manifests/sblock_founding.json").read_text())
BLOCK = tuple(manifest["block"])
glbs = [Path(p) for p in manifest["meshes"]]
print(f"rendering screen block {BLOCK} from {len(glbs)} meshes", flush=True)

img = render_screen_block(frame, *BLOCK, glbs)
out = Path("debug/renders")
img.save(out / "toronto_sblock_founding.png")
for tj in range(BLOCK[1], BLOCK[3] + 1):
    for ti in range(BLOCK[0], BLOCK[2] + 1):
        crop_tile(frame, img, BLOCK[0], BLOCK[1], ti, tj).save(
            out / f"toronto_t{ti}_{tj}.png")
print("block + 16 tile crops saved", flush=True)
