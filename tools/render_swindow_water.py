"""Render the water-probe window (180,14)-(183,17) and compose its infill
canvas: committed row 17 anchors at the BOTTOM, new rows 14-16 above."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from isomap.config import load_city
from isomap.infill import INFILL_PROMPT, compose_canvas
from isomap.render import ScreenFrame, crop_tile, render_screen_block

city = load_city("toronto")
frame = ScreenFrame(city)
manifest = json.loads(Path("cities/toronto/manifests/swindow_water.json").read_text())
WINDOW = tuple(manifest["window"])
glbs = [Path(p) for p in manifest["meshes"]]
print(f"rendering window {WINDOW} from {len(glbs)} meshes", flush=True)

img = render_screen_block(frame, *WINDOW, glbs)
out = Path("debug/renders")
img.save(out / "toronto_swindow_water_render.png")
for tj in range(WINDOW[1], WINDOW[3] + 1):
    for ti in range(WINDOW[0], WINDOW[2] + 1):
        crop_tile(frame, img, WINDOW[0], WINDOW[1], ti, tj).save(
            out / f"toronto_t{ti}_{tj}.png")
print("render + crops saved", flush=True)

anchors = {
    (ti, 17): Image.open(f"cities/toronto/map_tiles/t{ti}_17.png")
    for ti in range(180, 184)
}
renders = {
    (ti, tj): Image.open(out / f"toronto_t{ti}_{tj}.png")
    for tj in range(14, 17) for ti in range(180, 184)
}
canvas = compose_canvas(city, WINDOW, anchors, renders, scale=1)
inf = Path("debug/infill")
canvas.save(inf / "swindow_water_canvas.png")

prompt = INFILL_PROMPT + """

CRITICAL: Some buildings are cut by the boundary between the finished pixel-art region (bottom) and the photorealistic region (above it). Those partial buildings MUST continue with EXACTLY the same colors, materials, window patterns, and shading as their already-finished part. Do not reinterpret any surface that starts in the finished region.

Water: Lake Ontario and the harbour must be calm, flat pixel-art water in one consistent blue with subtle 2x2 dither shading — no noise, no random texture, no invented boats or objects that are not in the input image."""
(inf / "swindow_water_prompt.txt").write_text(prompt)
print("canvas + prompt saved", flush=True)
