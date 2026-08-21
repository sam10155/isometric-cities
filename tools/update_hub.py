"""Regenerate the debug hub from actual state (no more stale hand-edited links).

Staged windows = canvases in debug/infill/ whose window is NOT fully committed
in the DB (all cities; non-toronto canvases carry a "<city>_" prefix). Map
stats come from each city's DB. Run after prepares/commits:

  .venv/bin/python tools/update_hub.py
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from isomap.config import CITIES_DIR, load_city
from isomap.store import QuadrantStore
from isomap.tilelib import QState
from isomap.window import water_fraction_window
from isomap.render import ScreenFrame

city_names = sorted(p.parent.name for p in CITIES_DIR.glob("*/config.yaml"))

sections = []
for cn in city_names:
    city = load_city(cn)
    with QuadrantStore(city.db_path) as store:
        gs = store.load_grid_state()
    coords = gs.quadrants(QState.GENERATED)

    prefix = "" if cn == "toronto" else f"{cn}_"
    staged = []
    frame = None
    for f in sorted((REPO / "debug/infill").glob(f"{prefix}w*_canvas.png")):
        m = re.match(rf"{prefix}w(\d+)_(\d+)_(\d+)_(\d+)_canvas$", f.stem)
        if not m:
            continue
        w = tuple(int(g) for g in m.groups())
        tiles = [(ti, tj) for tj in range(w[1], w[3] + 1) for ti in range(w[0], w[2] + 1)]
        if coords and all(gs.get(t) is QState.GENERATED for t in tiles):
            continue  # fully committed — not staged
        try:
            frame = frame or ScreenFrame(city)
            wf = water_fraction_window(frame, w, n=8)
        except Exception:
            wf = None
        staged.append((f.stem.replace("_canvas", ""), wf))

    if not coords and not staged:
        sections.append(
            f"<h3>{city.display_name}</h3><p class=\"muted\">(no tiles yet — "
            f"founding window not staged)</p>")
        continue

    items = "\n".join(
        f'<p><b>{name}</b>{f" ({wf:.0%} water)" if wf else ""}: '
        f'<a href="infill/{name}_canvas.png" download>⬇ canvas</a> · '
        f'<a href="infill/{name}_prompt.txt" target="_blank">prompt</a></p>'
        for name, wf in staged) or '<p class="muted">(nothing staged)</p>'

    if coords:
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        status = (f"{len(coords)} tiles · extent ({min(xs)},{min(ys)})–"
                  f"({max(xs)},{max(ys)})")
    else:
        status = "no tiles yet"
    sections.append(
        f'<h3>{city.display_name} <span class="muted">— {status} · '
        f'<a href="viewer/?city={cn}">viewer</a></span></h3>\n{items}')

body = "\n".join(sections)
html = f'''<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iso-map — hub</title>
<style>
  body {{ font-family: sans-serif; background: #fafafa; margin: 2em auto;
         max-width: 62em; padding: 0 1em; color: #222; }}
  h1 {{ font-size: 1.4em; }}
  h2 {{ font-size: 1.1em; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  h3 {{ font-size: 1em; margin-bottom: .3em; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 1em 1.2em; margin: 1em 0; }}
  .action {{ border-left: 4px solid #2e5cff; }}
  .muted {{ color: #667; font-size: .9em; font-weight: normal; }}
</style>
<h1>🗺️ iso-map — Isometric Pixel-Art Cities</h1>
<p>Live: <a href="https://sam10155.github.io/isometric-cities/">sam10155.github.io/isometric-cities</a></p>

<div class="card action">
<h2>⭐ Staged windows (fresh chat each, any order)</h2>
{body}
<p class="muted">Save results into style_refs/ keeping the full window id in
the filename (png or jpg) — non-Toronto files keep their city prefix, e.g.
ottawa_w184_20_187_23_canvas_pixel.jpg — then tell Claude. This list is
generated from disk state — every link works.</p>
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
n = sum(s.count("<p><b>") for s in sections)
print(f"hub regenerated: {n} staged windows across {len(city_names)} cities")
