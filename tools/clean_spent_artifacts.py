"""Delete regenerable artifacts for fully committed windows.

Sweeps debug/infill, debug/renders and style_refs: any file whose window is
fully GENERATED in its city's DB is spent (content lives in map_tiles).
Run after commits when disk is tight:

  .venv/bin/python tools/clean_spent_artifacts.py [--keep FILENAME ...]
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from isomap.config import load_city
from isomap.store import QuadrantStore
from isomap.tilelib import QState

KEEP = set(sys.argv[2:]) if len(sys.argv) > 2 and sys.argv[1] == "--keep" else set()

stores = {}


def committed(city, x0, y0, x1, y1):
    st = stores.setdefault(city, QuadrantStore(load_city(city).db_path))
    return all(st.get_state((ti, tj)) == QState.GENERATED
               for ti in range(x0, x1 + 1) for tj in range(y0, y1 + 1))


total = 0
for d, pat in [
    (REPO / "debug/infill",  re.compile(r"^(?:([a-z]+)_)?w(\d+)_(\d+)_(\d+)_(\d+)_")),
    (REPO / "debug/renders", re.compile(r"^([a-z]+)_(?:[a-z]+_)?w(\d+)_(\d+)_(\d+)_(\d+)_render\.png$")),
    (REPO / "style_refs",    re.compile(r"^(?:([a-z]+)_)?w(\d+)_(\d+)_(\d+)_(\d+)_.*\.(?:png|jpg)$")),
]:
    n = 0
    for f in sorted(d.iterdir()):
        if f.name in KEEP:
            continue
        m = pat.match(f.name)
        if not m:
            continue
        city = m.group(1) or "toronto"
        if committed(city, *map(int, m.groups()[1:])):
            total += f.stat().st_size
            f.unlink()
            n += 1
    print(f"{d.relative_to(REPO)}: {n} removed")
print(f"freed {total / 1e6:.0f} MB")
