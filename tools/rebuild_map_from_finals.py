"""Rebuild every map tile from original generation outputs — NO water ops.

Replays, in chronological commit order:
- each window batch's assembled final (debug/infill/<batch>_final.png — the
  seam-cut result saved at commit time, before any water processing),
- the founding block (style_refs/toronto_sblock_founding_pixel.png),
- the two committed repairs (re-derived from their stored canvas/meta/output).

Use after any batch-processing regret (2026-08-12: water normalization was
degrading shorelines; user asked for originals back).

  .venv/bin/python tools/rebuild_map_from_finals.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from isomap.config import load_city
from isomap.infill import align_output, seam_cut_horizontal
from isomap.store import QuadrantStore

P = 512
city = load_city("toronto")
tiles_dir = city.city_dir / "map_tiles"

# --- event list: batches in chronological order ---
with QuadrantStore(city.db_path) as store:
    batches = store._conn.execute(
        "SELECT batch_id, MIN(updated_at) t FROM quadrants "
        "WHERE state='generated' GROUP BY batch_id ORDER BY t").fetchall()

REPAIRS = [  # (chronological time, repair name, output file) — before the 08-12 windows
    ("2026-08-11 17:48", "r94668_11566_95731_12613",
     "style_refs/r94668_11566_95731_12613_render_repair.png"),
    ("2026-08-11 17:56", "r94560_10147_95717_11149",
     "style_refs/r94560_10147_95717_11149_render_repair.png"),
]

events = []
for batch, t in batches:
    events.append((t, "window", batch))
for t, name, out in REPAIRS:
    events.append((t, "repair", (name, out)))
events.sort(key=lambda e: e[0])


def window_rect(batch: str):
    m = re.match(r"w(\d+)_(\d+)_(\d+)_(\d+)$", batch)
    if m:
        return tuple(int(g) for g in m.groups())
    if batch == "sblock_2026-08-11":
        return (180, 17, 183, 20)
    if batch.startswith("swindow_water"):
        return (180, 14, 183, 17)
    return None


def batch_final(batch: str):
    for cand in (REPO / f"debug/infill/{batch}_final.png",
                 REPO / "style_refs/toronto_sblock_founding_pixel.png"
                 if batch == "sblock_2026-08-11" else None,
                 REPO / "debug/infill/swindow_water_final.png"
                 if batch.startswith("swindow_water") else None):
        if cand and cand.exists():
            return Image.open(cand).convert("RGB")
    return None


def apply_window(batch: str) -> bool:
    w = window_rect(batch)
    img = batch_final(batch)
    if w is None or img is None:
        print(f"  !! no source for batch {batch} — tiles left as-is")
        return False
    if img.size != ((w[2] - w[0] + 1) * P, (w[3] - w[1] + 1) * P):
        img = img.resize(((w[2] - w[0] + 1) * P, (w[3] - w[1] + 1) * P), Image.LANCZOS)
    for j, tj in enumerate(range(w[1], w[3] + 1)):
        for i, ti in enumerate(range(w[0], w[2] + 1)):
            img.crop((i * P, j * P, (i + 1) * P, (j + 1) * P)).save(
                tiles_dir / f"t{ti}_{tj}.png")
    return True


def compose_current(px0, py0, px1, py1):
    img = Image.new("RGB", (px1 - px0, py1 - py0), (16, 16, 16))
    for tj in range(py0 // P, (py1 - 1) // P + 1):
        for ti in range(px0 // P, (px1 - 1) // P + 1):
            f = tiles_dir / f"t{ti}_{tj}.png"
            if f.exists():
                img.paste(Image.open(f).convert("RGB"), (ti * P - px0, tj * P - py0))
    return img


def apply_repair(name: str, out_file: str) -> bool:
    meta_f = REPO / f"debug/repair/{name}_meta.json"
    canvas_f = REPO / f"debug/repair/{name}_canvas.png"
    out_f = REPO / out_file
    if not (meta_f.exists() and canvas_f.exists() and out_f.exists()):
        print(f"  !! repair {name}: missing artifacts — skipped")
        return False
    meta = json.loads(meta_f.read_text())
    ax0, ay0, ax1, ay1 = meta["abs_rect"]
    m = meta["margin"]
    canvas = Image.open(canvas_f).convert("RGB")
    o = np.asarray(Image.open(out_f).convert("RGB").resize(canvas.size, Image.LANCZOS),
                   dtype=float)
    c = np.asarray(canvas, dtype=float)
    anchor = np.asarray(compose_current(ax0 - m, ay0 - m, ax1 + m, ay1 + m), dtype=float)
    o, _ = align_output(o, c)
    final = o.copy()
    for side in ("top", "bottom", "left", "right"):
        transposed = side in ("left", "right")
        f = final.transpose(1, 0, 2) if transposed else final
        a = anchor.transpose(1, 0, 2) if transposed else anchor
        eff = {"left": "top", "right": "bottom"}.get(side, side)
        n = f.shape[0]
        band0 = m - 96 if eff == "top" else n - m
        band = slice(band0, band0 + 96)
        path = seam_cut_horizontal(a[band], f[band])
        for x in range(f.shape[1]):
            yc = band0 + path[x]
            if eff == "top":
                f[:yc, x] = a[:yc, x]
            else:
                f[yc:, x] = a[yc:, x]
        final = f.transpose(1, 0, 2) if transposed else f
    img = Image.fromarray(final.astype(np.uint8))
    ex0, ey0 = ax0 - m, ay0 - m
    for tj in range(ey0 // P, (ay1 + m - 1) // P + 1):
        for ti in range(ex0 // P, (ax1 + m - 1) // P + 1):
            f = tiles_dir / f"t{ti}_{tj}.png"
            if not f.exists():
                continue
            tile = Image.open(f).convert("RGB")
            sx0, sy0 = max(ex0, ti * P), max(ey0, tj * P)
            sx1, sy1 = min(ax1 + m, (ti + 1) * P), min(ay1 + m, (tj + 1) * P)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            tile.paste(img.crop((sx0 - ex0, sy0 - ey0, sx1 - ex0, sy1 - ey0)),
                       (sx0 - ti * P, sy0 - tj * P))
            tile.save(f)
    return True


ok = bad = 0
for t, kind, payload in events:
    if kind == "window":
        print(f"[{t}] window {payload}")
        ok_ = apply_window(payload)
    else:
        name, out = payload
        print(f"[{t}] repair {name}")
        ok_ = apply_repair(name, out)
    ok += ok_
    bad += (not ok_)

print(f"\nreplayed {ok} events, {bad} without sources")
subprocess.run([sys.executable, str(REPO / "tools" / "assemble_map.py")], check=True)
subprocess.run([sys.executable, str(REPO / "tools" / "build_pyramid.py")], check=True)
