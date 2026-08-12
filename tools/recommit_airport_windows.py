"""Recovery: purge water-repaint contamination from the airport region.

The rebuild-from-finals replay reintroduced contamination through the LATE
windows' anchor strips (w177_8, w174_11, w180_8 finals embedded the bad-mask
repaint state of their anchors at commit time). Fix:

1. restore rows 11-13 from the CLEAN sources:
   - w177_11_180_14 final (committed before any water processing)
   - w180_11_183_14 final (its NEW columns 181-183 only)
2. un-commit the three late airport windows (DB -> empty)
3. re-run their commits from the original style_refs outputs — fresh anchors
   are now clean; seam blends regenerate correctly.

  .venv/bin/python tools/recommit_airport_windows.py
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from isomap.config import load_city
from isomap.store import QuadrantStore

P = 512
city = load_city("toronto")
tiles = city.city_dir / "map_tiles"

# 1. clean row 11-13 restoration
src = Image.open(REPO / "debug/infill/w177_11_180_14_final.png").convert("RGB")
for j, tj in enumerate(range(11, 14)):          # rows 11-13 (skip anchor row 14)
    for i, ti in enumerate(range(177, 181)):    # cols 177-180
        src.crop((i * P, j * P, (i + 1) * P, (j + 1) * P)).save(tiles / f"t{ti}_{tj}.png")
print("restored rows 11-13 cols 177-180 from w177_11 final (pre-contamination)")

src = Image.open(REPO / "debug/infill/w180_11_183_14_final.png").convert("RGB")
for j, tj in enumerate(range(11, 14)):
    for i, ti in zip(range(1, 4), range(181, 184)):  # its new cols 181-183 only
        src.crop((i * P, j * P, (i + 1) * P, (j + 1) * P)).save(tiles / f"t{ti}_{tj}.png")
print("restored rows 11-13 cols 181-183 from w180_11 final (clean new region)")

# 2. un-commit the late airport windows
LATE = [
    ("w177_8_180_11", "style_refs/w177_8_180_11_canvas_pixel.png"),
    ("w174_11_177_14", "style_refs/w174_11_177_14_canvas_pixel.png"),
    ("w180_8_183_11", "style_refs/w180_8_183_11_canvas_pixel.png"),
]
with QuadrantStore(city.db_path) as store:
    for batch, _ in LATE:
        n = store._conn.execute(
            "DELETE FROM quadrants WHERE batch_id = ?", (batch,)).rowcount
        store._conn.commit()
        print(f"un-committed {batch}: {n} tiles")

# 3. re-commit in chronological order (fresh clean anchors each time)
for batch, out in LATE:
    w = batch[1:].split("_")
    print(f"\n=== re-committing {batch} ===")
    subprocess.run(
        [sys.executable, "-m", "isomap.window", "commit", "toronto", *w, out, "--force"],
        check=True, cwd=REPO)
