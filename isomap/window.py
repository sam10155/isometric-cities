"""The generation-window crank: everything around the manual web-app step.

  python -m isomap.window prepare <city> <min_ti> <min_tj> <max_ti> <max_tj>
      Fetch + render the window, compose the infill canvas (anchors from
      map_tiles, renders elsewhere), write canvas + prompt to debug/infill/.

  python -m isomap.window commit <city> <min_ti> <min_tj> <max_ti> <max_tj> <output_png>
      QA the web-app output (structural fidelity, alignment), align it,
      seam-cut against the anchor edge, commit new tiles + updated anchor-edge
      tiles to map_tiles + DB, reassemble the map.

Anchor layout support: the window's already-GENERATED tiles must form full
rows at the top or bottom of the window (the two cases the seam machinery
handles today). Arbitrary anchor shapes are planner-v2 territory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import gridlib  # noqa: F401  (kept: CLI users often import via this module)
from .config import CityConfig, load_city
from .infill import INFILL_PROMPT, align_output, compose_canvas, seam_cut_horizontal
from .render import ScreenFrame, crop_tile, render_screen_block
from .store import QuadrantStore
from .tilelib import QState

REPO = Path(__file__).resolve().parent.parent
RENDERS = REPO / "debug" / "renders"
INFILL = REPO / "debug" / "infill"

HARDENING = """

CRITICAL: Some buildings are cut by the boundary between the finished pixel-art region and the photorealistic region. Those partial buildings MUST continue with EXACTLY the same colors, materials, window patterns, and shading as their already-finished part. Do not reinterpret any surface that starts in the finished region."""

# Included ONLY when the window render actually contains water. Discovered
# 2026-08-11 (user): mentioning water in a waterless window makes the model
# INVENT a lake. Prompts must not mention content that isn't in the frame.
WATER_NOTE = """

Water: the lake/harbour water in this image must be calm, flat pixel-art water in one consistent blue with subtle 2x2 dither shading — no noise, no random texture, no invented boats or objects that are not in the input image."""


def water_fraction_window(frame: ScreenFrame, w: tuple[int, int, int, int], n: int = 14) -> float:
    """Ground-truth water fraction of a window's visible ground footprint:
    sample the screen rect on a grid, inverse-project to lon/lat, test against
    OSM water data (isomap.water). Pixel heuristics are banned — blue-gray
    rooftops false-positive (2026-08-11)."""
    from .water import _load, is_water

    city = frame.city
    data = _load(city)
    x0, y0 = w[0] * frame.tile_m, w[1] * frame.tile_m
    x1, y1 = (w[2] + 1) * frame.tile_m, (w[3] + 1) * frame.tile_m
    hits = 0
    for i in range(n):
        for j in range(n):
            sx = x0 + (x1 - x0) * (i + 0.5) / n
            sy = y0 + (y1 - y0) * (j + 0.5) / n
            lon, lat = frame.screen_to_lonlat(sx, sy)
            if is_water(city, lon, lat, data):
                hits += 1
    return hits / (n * n)


def window_name(w: tuple[int, int, int, int]) -> str:
    return f"w{w[0]}_{w[1]}_{w[2]}_{w[3]}"


def anchor_rows(city: CityConfig, w: tuple[int, int, int, int]) -> tuple[set, str]:
    """(anchor coords, side) where side is 'top'|'bottom'|'left'|'right'.

    Anchors must form full rows at the window's top/bottom OR full columns at
    its left/right — the seam machinery handles one straight boundary."""
    with QuadrantStore(city.db_path) as store:
        gs = store.load_grid_state()
    anchors = {
        (ti, tj)
        for tj in range(w[1], w[3] + 1)
        for ti in range(w[0], w[2] + 1)
        if gs.get((ti, tj)) is QState.GENERATED
    }
    if not anchors:
        sys.exit("window has no committed anchors — refuse to generate unanchored")
    width = w[2] - w[0] + 1
    height = w[3] - w[1] + 1
    rows = sorted({tj for _, tj in anchors})
    cols = sorted({ti for ti, _ in anchors})
    full_rows = {tj for tj in rows if sum(1 for a in anchors if a[1] == tj) == width}
    full_cols = {ti for ti in cols if sum(1 for a in anchors if a[0] == ti) == height}

    def prefix(vals: set, start: int) -> list:
        out = []
        v = start
        while v in vals:
            out.append(v)
            v += 1
        return out

    def suffix(vals: set, end: int) -> list:
        out = []
        v = end
        while v in vals:
            out.append(v)
            v -= 1
        return out

    row_sides = {"top": prefix(full_rows, w[1]), "bottom": suffix(full_rows, w[3])}
    col_sides = {"left": prefix(full_cols, w[0]), "right": suffix(full_cols, w[2])}

    # try every combination of edge bands (1-4 sides), smallest first; the
    # seam machinery applies one pass per side, so any covered combo works
    from itertools import combinations

    all_sides = ("top", "bottom", "left", "right")
    for k in (1, 2, 3, 4):
        for combo in combinations(all_sides, k):
            covered = set()
            ok = True
            for s in combo:
                band = row_sides.get(s) if s in ("top", "bottom") else col_sides.get(s)
                if not band:
                    ok = False
                    break
                if s in ("top", "bottom"):
                    covered |= {(ti, tj) for tj in band for ti in range(w[0], w[2] + 1)}
                else:
                    covered |= {(ti, tj) for ti in band for tj in range(w[1], w[3] + 1)}
            if ok and covered == anchors:
                return anchors, "+".join(combo)
    sys.exit(f"unsupported anchor layout: rows {rows}, cols {cols} "
             f"(anchors must be expressible as full edge bands)")


def cmd_prepare(args) -> None:
    city = load_city(args.city)
    frame = ScreenFrame(city)
    w = (args.min_ti, args.min_tj, args.max_ti, args.max_tj)
    anchors, side = anchor_rows(city, w)
    name = window_name(w)

    from .tiles3d import Tiles3dClient

    # fetch one extra tile row+col: the canvas gets a sacrificial 256px pad on
    # the right+bottom so the Gemini watermark lands there (cropped at commit)
    region = frame.tile_fetch_region(w[0], w[1], w[2] + 1, w[3] + 1)
    client = Tiles3dClient(city.name, max_requests=args.max_requests)
    meshes = client.collect_meshes(region, target_error=8.0)
    print(f"meshes: {len(meshes)} (new requests {client.stats.network_requests}, "
          f"cache hits {client.stats.cache_hits})")
    print("sessions:", client.budget.status("map_tiles_session"))
    manifest = REPO / "cities" / city.name / "manifests" / f"{name}.json"
    manifest.write_text(json.dumps({
        "window": w, "meshes": sorted(str(m.cache_path) for m in meshes)}, indent=1))

    print("rendering window...")
    glbs = [Path(p) for p in json.loads(manifest.read_text())["meshes"]]
    img = render_screen_block(frame, w[0], w[1], w[2] + 1, w[3] + 1, glbs)
    RENDERS.mkdir(parents=True, exist_ok=True)
    img.save(RENDERS / f"toronto_{name}_render.png")

    anchor_imgs, render_imgs = {}, {}
    tiles_dir = city.city_dir / "map_tiles"
    render_tiles = city.city_dir / "render_tiles"
    render_tiles.mkdir(exist_ok=True)
    for tj in range(w[1], w[3] + 1):
        for ti in range(w[0], w[2] + 1):
            tile = crop_tile(frame, img, w[0], w[1], ti, tj)
            tile.save(render_tiles / f"t{ti}_{tj}.png")
            if (ti, tj) in anchors:
                anchor_imgs[(ti, tj)] = Image.open(tiles_dir / f"t{ti}_{tj}.png")
            else:
                render_imgs[(ti, tj)] = tile

    canvas = compose_canvas(city, w, anchor_imgs, render_imgs, scale=1)
    # sacrificial watermark pad: 256px of render content on right+bottom.
    # The Gemini app stamps its sparkle in the output's bottom-right corner;
    # with the pad, the sparkle lands on throwaway pixels (commit crops them).
    PAD = 256
    wpx, hpx = canvas.size
    padded = Image.new("RGB", (wpx + PAD, hpx + PAD))
    padded.paste(canvas, (0, 0))
    padded.paste(img.crop((wpx, 0, wpx + PAD, hpx)), (wpx, 0))
    padded.paste(img.crop((0, hpx, wpx, hpx + PAD)), (0, hpx))
    padded.paste(img.crop((wpx, hpx, wpx + PAD, hpx + PAD)), (wpx, hpx))
    canvas = padded
    INFILL.mkdir(parents=True, exist_ok=True)
    canvas.save(INFILL / f"{name}_canvas.png")
    if args.water is None:
        wf = water_fraction_window(frame, w)
        has_water = wf > 0.02
        print(f"water (OSM ground truth): {wf:.1%} -> "
              f"{'INCLUDING' if has_water else 'omitting'} water note"
              f" (override with --water/--no-water)")
    else:
        has_water = args.water
    prompt = INFILL_PROMPT + HARDENING + (WATER_NOTE if has_water else "")
    (INFILL / f"{name}_prompt.txt").write_text(prompt)
    print(f"""
READY — manual step:
  1. Fresh chat in the Gemini web app
  2. Attach debug/infill/{name}_canvas.png  (anchor rows at the {side})
  3. Prompt:   debug/infill/{name}_prompt.txt
  4. Save result to style_refs/{name}_pixel.png
  5. Run: python -m isomap.window commit {args.city} {w[0]} {w[1]} {w[2]} {w[3]} style_refs/{name}_pixel.png""")


def cmd_commit(args) -> None:
    city = load_city(args.city)
    w = (args.min_ti, args.min_tj, args.max_ti, args.max_tj)
    anchors, side = anchor_rows(city, w)
    if len(anchors) == (w[2] - w[0] + 1) * (w[3] - w[1] + 1):
        sys.exit("window is already fully committed — nothing to commit "
                 "(re-running a finished commit is a no-op; use isomap.repair "
                 "to change committed content)")
    name = window_name(w)
    p = city.grid.quadrant_px

    canvas = Image.open(INFILL / f"{name}_canvas.png").convert("RGB")
    output = Path(args.output)
    if not output.exists():
        # tolerate naming variants: any style_refs file containing the window name
        matches = sorted((REPO / "style_refs").glob(f"*{name}*"))
        if len(matches) == 1:
            output = matches[0]
            print(f"using {output.name}")
        else:
            sys.exit(f"{args.output} not found; style_refs matches: "
                     f"{[m.name for m in matches] or 'none'}")
    out = Image.open(output).convert("RGB")
    o = np.asarray(out.resize(canvas.size, Image.LANCZOS), dtype=float)
    # STALE-CANVAS RULE (bug 2026-08-11: a window commit reverted an interim
    # repair): the prepare-time canvas is only what the model SAW — use it for
    # alignment. Anchor pixels for seams/repaste must come from the CURRENT
    # map tiles, else any commit between prepare and now gets clobbered.
    tiles_now = city.city_dir / "map_tiles"
    renders_now = city.city_dir / "render_tiles"
    c_fresh = compose_canvas(
        city, w,
        {q: Image.open(tiles_now / f"t{q[0]}_{q[1]}.png") for q in anchors},
        {(ti, tj): Image.open(renders_now / f"t{ti}_{tj}.png")
         for tj in range(w[1], w[3] + 1) for ti in range(w[0], w[2] + 1)
         if (ti, tj) not in anchors},
        scale=1,
    )
    c = np.asarray(c_fresh, dtype=float)

    small_a = np.asarray(canvas.resize((128, 128), Image.LANCZOS), dtype=float)
    small_b = np.asarray(out.resize((128, 128), Image.LANCZOS), dtype=float)
    corr = np.corrcoef(small_a.flatten(), small_b.flatten())[0, 1]
    # align against the STALE canvas (what the model saw), seam against fresh
    o, shift = align_output(o, np.asarray(canvas, dtype=float))
    # crop the sacrificial watermark pad (canvas larger than the window area)
    win_w = (w[2] - w[0] + 1) * p
    win_h = (w[3] - w[1] + 1) * p
    if o.shape[1] > win_w or o.shape[0] > win_h:
        o = o[:win_h, :win_w]
    print(f"QA: structural corr {corr:.3f}, alignment {shift}")
    if corr < 0.75 and not args.force:
        sys.exit("structural fidelity below 0.75 — inspect, then rerun with "
                 "--force if the content explains it (e.g. mostly open water)")

    def seam_pass(final: np.ndarray, canvas_a: np.ndarray, one_side: str) -> np.ndarray:
        """Apply one anchor-boundary seam pass; arrays are (H, W, 3)."""
        transposed = one_side in ("left", "right")
        f = final.transpose(1, 0, 2) if transposed else final
        ca = canvas_a.transpose(1, 0, 2) if transposed else canvas_a
        eff = {"left": "top", "right": "bottom"}.get(one_side, one_side)
        if transposed:
            n_anchor = len({ti for ti, _ in anchors
                            if all((ti, tj) in anchors for tj in range(w[1], w[3] + 1))})
            n_total = w[2] - w[0] + 1
        else:
            n_anchor = len({tj for _, tj in anchors
                            if all((ti, tj) in anchors for ti in range(w[0], w[2] + 1))})
            n_total = w[3] - w[1] + 1
        if eff == "top":
            band0 = n_anchor * p - 96
        else:
            band0 = (n_total - n_anchor) * p
        band = slice(band0, band0 + 96)
        if getattr(args, "hard_seam", False):
            # zero model pixels inside anchor tiles: cut exactly at the
            # anchor/new boundary (use when the model hallucinated the
            # anchor region and even the blend band can't be trusted)
            path = np.full(f.shape[1], 96 if eff == "top" else 0, dtype=int)
        else:
            path = seam_cut_horizontal(ca[band], f[band])
        g = f.copy()
        for x in range(g.shape[1]):
            yc = band0 + path[x]
            if eff == "top":
                g[:yc, x] = ca[:yc, x]
            else:
                g[yc:, x] = ca[yc:, x]

        def row_disc(img, y):
            return np.abs(img[y + 1] - img[y]).mean()

        typical = np.mean([row_disc(g, y) for y in range(200, g.shape[0] - 200, 100)])
        seam = np.mean([np.abs(g[band0 + path[x] + 1, x] - g[band0 + path[x], x]).mean()
                        for x in range(0, g.shape[1], 4)])
        print(f"seam pass '{one_side}': ratio {seam / typical:.2f}")
        return g.transpose(1, 0, 2) if transposed else g

    final = o.copy()
    for one_side in side.split("+"):
        final = seam_pass(final, c, one_side)

    img = Image.fromarray(final.astype(np.uint8))
    img.save(INFILL / f"{name}_final.png")
    tiles_dir = city.city_dir / "map_tiles"
    with QuadrantStore(city.db_path) as store:
        n_new = 0
        for j, tj in enumerate(range(w[1], w[3] + 1)):
            for i, ti in enumerate(range(w[0], w[2] + 1)):
                img.crop((i * p, j * p, (i + 1) * p, (j + 1) * p)).save(
                    tiles_dir / f"t{ti}_{tj}.png")
                if (ti, tj) not in anchors:
                    store.set_state((ti, tj), QState.GENERATED, batch_id=name)
                    n_new += 1
        print(f"committed {n_new} new tiles; DB: {store.counts()}")

    import subprocess

    # NOTE: automatic water normalization DISABLED 2026-08-12 (user: it was
    # degrading shorelines/the airport). Committed pixels are exactly what the
    # generation produced. Revisit via isomap.watercolor if water seams return.
    # Incremental pyramid: only this window's tiles + ancestors (seconds).
    subprocess.run([sys.executable, "-m", "isomap.pyramid", "update", args.city,
                    str(w[0]), str(w[1]), str(w[2]), str(w[3])],
                   check=True, cwd=REPO)


def main() -> None:
    ap = argparse.ArgumentParser(prog="isomap.window")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, fn in [("prepare", cmd_prepare), ("commit", cmd_commit)]:
        sp = sub.add_parser(cmd)
        sp.add_argument("city")
        sp.add_argument("min_ti", type=int)
        sp.add_argument("min_tj", type=int)
        sp.add_argument("max_ti", type=int)
        sp.add_argument("max_tj", type=int)
        if cmd == "prepare":
            sp.add_argument("--max-requests", type=int, default=3000)
            sp.add_argument("--water", action="store_true", default=None,
                            help="force-include the water style note")
            sp.add_argument("--no-water", dest="water", action="store_false",
                            help="force-omit the water style note")
        else:
            sp.add_argument("output")
            sp.add_argument("--force", action="store_true",
                            help="commit despite a low structural score (after visual check)")
            sp.add_argument("--hard-seam", action="store_true",
                            help="no blend band: anchor tiles keep 100% committed "
                                 "pixels (use when the model hallucinated near anchors)")
        sp.set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
