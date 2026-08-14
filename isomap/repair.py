"""Rectangle repair: fix artifacts in committed map regions.

  python -m isomap.repair export <city> <x0> <y0> <x1> <y1> [--name NAME]
      Coords are map-relative pixels (as shown in the viewer). Exports to
      debug/repair/: the current stylized crop, the base render crop, and the
      repair CANVAS (stylized margin ring as anchor + base render in the
      selected rect) + prompt. All from committed tiles + saved render tiles —
      no API requests.

  python -m isomap.repair commit <city> <name> <output_png>
      Align the web-app output, seam-cut along all four margin edges, write
      back only the affected tiles, reassemble map + pyramid.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .config import load_city
from .infill import align_output, seam_cut_horizontal
from .store import QuadrantStore
from .tilelib import QState

REPO = Path(__file__).resolve().parent.parent
REPAIR = REPO / "debug" / "repair"
P = 512  # px per tile
MARGIN = 256  # anchor ring width around the selection

REPAIR_PROMPT = """This image is a section of an isometric pixel-art map of Toronto. The OUTER MARGIN of the image is finished pixel art. The INNER RECTANGLE is a photorealistic isometric 3D render showing what that area actually contains.

Redraw the inner rectangle as pixel art that matches the outer margin's style exactly and faithfully depicts every building, road, and detail in the photorealistic render. This is a repair: the render is the ground truth for WHAT exists; the margin is the ground truth for HOW it should look.

Requirements:
- Do NOT change the outer margin
- Every structure in the render must appear, correctly placed
- Match palette, pixel density, dithering, lighting of the margin exactly
- Boundaries between margin and redrawn area must be invisible
- No text, no UI elements; fill the entire frame"""

# appended only when the render crop actually contains water — mentioning
# water in a waterless prompt makes the model invent a lake (2026-08-11)
WATER_NOTE = """
- The water in this image: flat consistent blue with subtle 2x2 dither, no invented objects"""


def _map_bounds(city) -> tuple[int, int]:
    with QuadrantStore(city.db_path) as store:
        gs = store.load_grid_state()
    coords = gs.quadrants(QState.GENERATED)
    return min(c[0] for c in coords), min(c[1] for c in coords)


def _compose(tile_dir: Path, prefix: str, px0: int, py0: int, px1: int, py1: int) -> Image.Image:
    """Compose an absolute-tile-space pixel rect from 512px tiles on disk."""
    img = Image.new("RGB", (px1 - px0, py1 - py0), (16, 16, 16))
    for tj in range(py0 // P, (py1 - 1) // P + 1):
        for ti in range(px0 // P, (px1 - 1) // P + 1):
            f = tile_dir / f"{prefix}{ti}_{tj}.png"
            if f.exists():
                img.paste(Image.open(f).convert("RGB"), (ti * P - px0, tj * P - py0))
    return img


def cmd_export(args) -> None:
    from .pyramid import PYR_ORIGIN

    city = load_city(args.city)
    # viewer px are FIXED pyramid-frame coords -> absolute tile-space px
    ax0 = args.x0 + PYR_ORIGIN[0] * P
    ay0 = args.y0 + PYR_ORIGIN[1] * P
    ax1 = args.x1 + PYR_ORIGIN[0] * P
    ay1 = args.y1 + PYR_ORIGIN[1] * P
    name = args.name or f"r{ax0}_{ay0}_{ax1}_{ay1}"
    # clamp margins to the committed map so canvases never carry black bands
    # (an off-map black margin reads as "finished pixel art" to the model)
    with QuadrantStore(city.db_path) as store:
        gs = store.load_grid_state()
    cs = gs.quadrants(QState.GENERATED)
    bx0 = min(c[0] for c in cs) * P
    by0 = min(c[1] for c in cs) * P
    bx1 = (max(c[0] for c in cs) + 1) * P
    by1 = (max(c[1] for c in cs) + 1) * P
    ml = min(MARGIN, ax0 - bx0)
    mt = min(MARGIN, ay0 - by0)
    mr = min(MARGIN, bx1 - ax1)
    mb = min(MARGIN, by1 - ay1)
    ex0, ey0, ex1, ey1 = ax0 - ml, ay0 - mt, ax1 + mr, ay1 + mb

    REPAIR.mkdir(parents=True, exist_ok=True)
    map_crop = _compose(city.city_dir / "map_tiles", "t", ex0, ey0, ex1, ey1)
    render_crop = _compose(city.city_dir / "render_tiles", "t", ex0, ey0, ex1, ey1)
    map_crop.save(REPAIR / f"{name}_map.png")
    render_crop.save(REPAIR / f"{name}_render.png")

    canvas = map_crop.copy()
    canvas.paste(render_crop.crop((ml, mt, ex1 - ex0 - mr, ey1 - ey0 - mb)), (ml, mt))
    canvas.save(REPAIR / f"{name}_canvas.png")
    # ground-truth water test over the repair rect (screen px -> lon/lat -> OSM)
    from .render import ScreenFrame
    from .water import _load, is_water

    frame = ScreenFrame(city)
    data = _load(city)
    hits, n = 0, 12
    for i in range(n):
        for j in range(n):
            sx = (ax0 + (ax1 - ax0) * (i + 0.5) / n) / frame.px_per_m
            sy = (ay0 + (ay1 - ay0) * (j + 0.5) / n) / frame.px_per_m
            if is_water(city, *frame.screen_to_lonlat(sx, sy), data):
                hits += 1
    wf = hits / (n * n)
    print(f"water (OSM ground truth): {wf:.1%}")
    prompt = REPAIR_PROMPT + (WATER_NOTE if wf > 0.02 else "")
    (REPAIR / f"{name}_prompt.txt").write_text(prompt)
    (REPAIR / f"{name}_meta.json").write_text(json.dumps({
        "abs_rect": [ax0, ay0, ax1, ay1], "margin": MARGIN,
        "margins": [ml, mt, mr, mb]}))
    print(json.dumps({
        "name": name,
        "canvas": f"debug/repair/{name}_canvas.png",
        "render": f"debug/repair/{name}_render.png",
        "map": f"debug/repair/{name}_map.png",
        "prompt": f"debug/repair/{name}_prompt.txt",
        "commit_cmd": f"python -m isomap.repair commit {args.city} {name} style_refs/{name}_pixel.png",
    }))


def cmd_commit(args) -> None:
    city = load_city(args.city)
    meta = json.loads((REPAIR / f"{args.name}_meta.json").read_text())
    ax0, ay0, ax1, ay1 = meta["abs_rect"]
    m = meta["margin"]
    ml, mt, mr, mb = meta.get("margins", [m, m, m, m])
    canvas = Image.open(REPAIR / f"{args.name}_canvas.png").convert("RGB")

    output = Path(args.output)
    if not output.exists():
        matches = sorted((REPO / "style_refs").glob(f"*{args.name}*"))
        if len(matches) == 1:
            output = matches[0]
            print(f"using {output.name}")
        else:
            sys.exit(f"{args.output} not found; matches: {[x.name for x in matches] or 'none'}")

    o = np.asarray(Image.open(output).convert("RGB").resize(canvas.size, Image.LANCZOS), dtype=float)
    c = np.asarray(canvas, dtype=float)
    # stale-canvas rule: seam anchors come from CURRENT tiles, not the export-
    # time map crop (see window.py commit; prevents reverting interim commits)
    anchor = np.asarray(
        _compose(city.city_dir / "map_tiles", "t",
                 ax0 - ml, ay0 - mt, ax1 + mr, ay1 + mb), dtype=float)
    o, shift = align_output(o, c)
    print(f"alignment: {shift}")
    # sanity gate: real repair outputs land within a few px; a huge shift means
    # the output doesn't match the canvas (wrong region or unstylized photoreal
    # — see the r91838 incident, 2026-08-14) and would smear garbage into the map
    if max(abs(int(shift[0])), abs(int(shift[1]))) > 64 and not args.force:
        sys.exit(f"alignment {shift} is implausible for a repair — output likely "
                 "doesn't match the canvas (wrong crop or not stylized). Nothing "
                 "was committed; inspect the output, then rerun with --force if "
                 "it is actually correct.")

    final = o.copy()
    H, W = final.shape[:2]
    for side, sm in (("top", mt), ("bottom", mb), ("left", ml), ("right", mr)):
        if sm < 96:  # map-edge side: no anchor to seam against
            print(f"seam pass '{side}': skipped (margin {sm})")
            continue
        transposed = side in ("left", "right")
        f = final.transpose(1, 0, 2) if transposed else final
        a = anchor.transpose(1, 0, 2) if transposed else anchor
        eff = {"left": "top", "right": "bottom"}.get(side, side)
        n = f.shape[0]
        band0 = sm - 96 if eff == "top" else n - sm
        band = slice(band0, band0 + 96)
        path = seam_cut_horizontal(a[band], f[band])
        for x in range(f.shape[1]):
            yc = band0 + path[x]
            if eff == "top":
                f[:yc, x] = a[:yc, x]
            else:
                f[yc:, x] = a[yc:, x]
        final = f.transpose(1, 0, 2) if transposed else f

    # write back affected tiles
    ex0, ey0 = ax0 - ml, ay0 - mt
    img = Image.fromarray(final.astype(np.uint8))
    tiles_dir = city.city_dir / "map_tiles"
    touched = 0
    for tj in range(ey0 // P, (ay1 + mb - 1) // P + 1):
        for ti in range(ex0 // P, (ax1 + mr - 1) // P + 1):
            f = tiles_dir / f"t{ti}_{tj}.png"
            if not f.exists():
                continue
            tile = Image.open(f).convert("RGB")
            sx0 = max(ex0, ti * P)
            sy0 = max(ey0, tj * P)
            sx1 = min(ax1 + mr, (ti + 1) * P)
            sy1 = min(ay1 + mb, (tj + 1) * P)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            patch = img.crop((sx0 - ex0, sy0 - ey0, sx1 - ex0, sy1 - ey0))
            tile.paste(patch, (sx0 - ti * P, sy0 - tj * P))
            tile.save(f)
            touched += 1
    print(f"updated {touched} tiles")
    # water normalization intentionally NOT run (disabled 2026-08-12)
    subprocess.run([sys.executable, "-m", "isomap.pyramid", "update", args.city,
                    str(ex0 // P), str(ey0 // P),
                    str((ax1 + mr) // P), str((ay1 + mb) // P)],
                   check=True, cwd=REPO)


def main() -> None:
    ap = argparse.ArgumentParser(prog="isomap.repair")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("export")
    sp.add_argument("city")
    for k in ("x0", "y0", "x1", "y1"):
        sp.add_argument(k, type=int)
    sp.add_argument("--name")
    sp.set_defaults(func=cmd_export)
    sp = sub.add_parser("commit")
    sp.add_argument("city")
    sp.add_argument("name")
    sp.add_argument("output")
    sp.add_argument("--force", action="store_true",
                    help="commit despite an implausible alignment shift")
    sp.set_defaults(func=cmd_commit)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
