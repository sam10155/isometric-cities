"""Build a Deep Zoom (DZI) pyramid from the assembled map for the viewer.

Reads debug/map/toronto_map.png, writes debug/viewer/map.dzi +
debug/viewer/map_files/<level>/<col>_<row>.png. Run after assemble_map.py.
"""

import sys
from pathlib import Path

from PIL import Image

TILE = 512
OVERLAP = 1

repo = Path(__file__).resolve().parent.parent
src = repo / "debug" / "map" / "toronto_map.png"
out = repo / "docs"
files = out / "map_files"

img = Image.open(src).convert("RGB")
W, H = img.size

# level N = full resolution; level 0 = 1px. DZI counts levels from the top.
levels = 0
d = max(W, H)
while d > 1:
    d = (d + 1) // 2
    levels += 1

(out).mkdir(parents=True, exist_ok=True)
(out / "map.dzi").write_text(
    f'<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
    f'Format="png" Overlap="{OVERLAP}" TileSize="{TILE}">'
    f'<Size Width="{W}" Height="{H}"/></Image>\n'
)

level_img = img
for level in range(levels, -1, -1):
    lw, lh = level_img.size
    ldir = files / str(level)
    ldir.mkdir(parents=True, exist_ok=True)
    cols = (lw + TILE - 1) // TILE
    rows = (lh + TILE - 1) // TILE
    for r in range(rows):
        for c in range(cols):
            x0 = max(c * TILE - OVERLAP, 0)
            y0 = max(r * TILE - OVERLAP, 0)
            x1 = min((c + 1) * TILE + OVERLAP, lw)
            y1 = min((r + 1) * TILE + OVERLAP, lh)
            level_img.crop((x0, y0, x1, y1)).save(ldir / f"{c}_{r}.png")
    if level:
        level_img = level_img.resize(((lw + 1) // 2, (lh + 1) // 2), Image.LANCZOS)

print(f"pyramid: {W}x{H}, {levels + 1} levels -> {files}")
