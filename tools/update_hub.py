"""Regenerate the debug hub from actual state (no more stale hand-edited links).

Staged windows = canvases in debug/infill/ whose window is NOT fully committed
in the DB. Map stats come from the DB. Run after prepares/commits:

  .venv/bin/python tools/update_hub.py
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from isomap.config import load_city
from isomap.store import QuadrantStore
from isomap.tilelib import QState
from isomap.window import water_fraction_window
from isomap.render import ScreenFrame

city = load_city("toronto")
frame = ScreenFrame(city)
with QuadrantStore(city.db_path) as store:
    gs = store.load_grid_state()
coords = gs.quadrants(QState.GENERATED)

staged = []
for f in sorted((REPO / "debug/infill").glob("w*_canvas.png")):
    m = re.match(r"w(\d+)_(\d+)_(\d+)_(\d+)_canvas$", f.stem)
    if not m:
        continue
    w = tuple(int(g) for g in m.groups())
    tiles = [(ti, tj) for tj in range(w[1], w[3] + 1) for ti in range(w[0], w[2] + 1)]
    if all(gs.get(t) is QState.GENERATED for t in tiles):
        continue  # fully committed — not staged
    try:
        wf = water_fraction_window(frame, w, n=8)
    except Exception:
        wf = None
    staged.append((f.stem.replace("_canvas", ""), wf))

items = "\n".join(
    f'<p><b>{name}</b>{f" ({wf:.0%} water)" if wf else ""}: '
    f'<a href="infill/{name}_canvas.png" download>⬇ canvas</a> · '
    f'<a href="infill/{name}_prompt.txt" target="_blank">prompt</a></p>'
    for name, wf in staged) or "<p>(nothing staged — ask Claude)</p>"

xs = [c[0] for c in coords]
ys = [c[1] for c in coords]
status = (f"{len(coords)} tiles · extent ({min(xs)},{min(ys)})–({max(xs)},{max(ys)}) · "
          f"{len(staged)} windows staged")

html = f'''<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iso-map — Toronto</title>
<style>
  body {{ font-family: sans-serif; background: #fafafa; margin: 2em auto;
         max-width: 62em; padding: 0 1em; color: #222; }}
  h1 {{ font-size: 1.4em; }}
  h2 {{ font-size: 1.1em; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 1em 1.2em; margin: 1em 0; }}
  .action {{ border-left: 4px solid #2e5cff; }}
  .muted {{ color: #667; font-size: .9em; }}
</style>
<h1>🗺️ iso-map — Isometric Pixel-Art Toronto</h1>
<p><b><a href="viewer/">Open the deep-zoom viewer</a></b> · live:
<a href="https://sam10155.github.io/isometric-cities/">sam10155.github.io/isometric-cities</a></p>

<div class="card action">
<h2>⭐ Staged windows (fresh chat each, any order)</h2>
{items}
<p class="muted">Save results into style_refs/ with the window id in the
filename (png or jpg), then tell Claude. This list is generated from disk
state — every link works.</p>
</div>

<div class="card">
<h2>Map status</h2>
<p>{status}</p>
</div>

<div class="card">
<h2>Workflows — full guide: <a href="/WORKFLOW.md">WORKFLOW.md</a></h2>
<p><b>Grow:</b> stylize staged canvas → drop into style_refs/ → tell Claude.
<b>Repair:</b> ✂ select in the viewer → stylize → drop → tell Claude.</p>
</div>

<div class="card">
<h2>Archives</h2>
<p><a href="tests/index.html">test artifacts</a> ·
<a href="infill/">infill</a> · <a href="repair/">repair</a> ·
<a href="renders/">renders</a></p>
</div>
'''
(REPO / "debug/index.html").write_text(html)
print(f"hub regenerated: {len(staged)} staged windows listed")

