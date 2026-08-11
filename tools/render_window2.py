"""Render window 2 (122,72)-(125,75) and compose its infill canvas.

Anchor: committed stylized row 72 (from map_tiles). New: rendered rows 73-75.
Offline. Writes the render, the canvas for the web app, and quadrant crops.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from isomap.config import load_city
from isomap.infill import INFILL_PROMPT, compose_canvas
from isomap.render import crop_quadrant, render_block

WINDOW = (122, 72, 125, 75)

city = load_city("toronto")
glbs = set()
for m in ["block_122_69_125_72_err4.json", "rows_73_75_err4.json"]:
    glbs.update(json.loads((Path("cities/toronto/manifests") / m).read_text()))
glbs = [Path(p) for p in sorted(glbs)]
print(f"rendering window {WINDOW} from {len(glbs)} meshes", flush=True)

img = render_block(city, *WINDOW, glbs, supersample=1)
out = Path("debug/renders")
img.save(out / "toronto_window2_render.png")
for qy in range(73, 76):
    for qx in range(122, 126):
        crop_quadrant(city, img, WINDOW[0], WINDOW[1], qx, qy).save(
            out / f"toronto_q{qx}_{qy}.png")
print("render + crops saved", flush=True)

# canvas: anchor row 72 (stylized) + renders rows 73-75
anchors = {
    (qx, 72): Image.open(f"cities/toronto/map_tiles/q{qx}_72.png")
    for qx in range(122, 126)
}
renders = {
    (qx, qy): Image.open(out / f"toronto_q{qx}_{qy}.png")
    for qy in range(73, 76) for qx in range(122, 126)
}
canvas = compose_canvas(city, WINDOW, anchors, renders, scale=1)
inf = Path("debug/infill")
canvas.save(inf / "window2_canvas_122-125_72-75.png")

hardened = INFILL_PROMPT + """

CRITICAL: Some buildings are cut by the boundary between the finished pixel-art region and the photorealistic region. Those partial buildings MUST continue with EXACTLY the same colors, materials, window patterns, and shading as their already-finished part. Do not reinterpret any surface that starts in the finished region.

Water note: Lake Ontario and harbour water must be rendered as calm, flat pixel-art water in a single consistent blue with subtle 2x2 dither shading — no random texture, no noise, no invented boats or objects that are not in the input."""
(inf / "window2_prompt.txt").write_text(hardened)
print("canvas + prompt saved", flush=True)
