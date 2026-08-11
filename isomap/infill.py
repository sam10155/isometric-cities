"""Infill canvas composition — the seam mechanism.

A generation window's input canvas contains already-stylized quadrants
(anchors, locked) and photographic renders (regions to stylize). The model
continues the pixel-art into the photographic regions; afterwards
`repaste_anchors` restores anchor pixels verbatim so approved content can
never drift.

Scale convention: canvases are composed at `scale` x quadrant_px per quadrant
(default 2 — Nano Banana returns 2x, so anchors keep native stylized
resolution).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import CityConfig
from .tilelib import Coord

INFILL_PROMPT = """This image is a section of an isometric pixel-art map of Toronto that is partially complete. Part of the image is already finished pixel art in the style of classic late-90s city-building games like SimCity 2000; the rest is a photorealistic isometric 3D render that has not been stylized yet.

Complete the map: transform ONLY the photorealistic region into pixel art that seamlessly continues the existing pixel-art region.

Requirements:
- Do NOT change the already-stylized pixel-art region in any way
- Match its palette, pixel density, dithering style, lighting and level of detail exactly
- Keep every building, road, and rail line in the photorealistic region in exactly the same position
- The boundary between the existing and new pixel art must be invisible
- No text, no UI elements, no borders; fill the entire frame edge to edge"""


def compose_canvas(
    city: CityConfig,
    window: tuple[int, int, int, int],
    anchors: dict[Coord, Image.Image],
    renders: dict[Coord, Image.Image],
    scale: int = 2,
) -> Image.Image:
    """Assemble the model input for a generation window.

    window: (min_qx, min_qy, max_qx, max_qy) inclusive.
    anchors: stylized quadrant tiles (any size; resized to scale*quadrant_px).
    renders: photographic render tiles for the quadrants to generate.
    Every quadrant in the window must appear in exactly one of the two dicts.
    """
    p = city.grid.quadrant_px * scale
    min_qx, min_qy, max_qx, max_qy = window
    n_x, n_y = max_qx - min_qx + 1, max_qy - min_qy + 1
    canvas = Image.new("RGB", (n_x * p, n_y * p))
    for qy in range(min_qy, max_qy + 1):
        for qx in range(min_qx, max_qx + 1):
            q = (qx, qy)
            if q in anchors:
                tile = anchors[q]
            elif q in renders:
                tile = renders[q]
            else:
                raise ValueError(f"window quadrant {q} in neither anchors nor renders")
            tile = tile.convert("RGB").resize((p, p), Image.LANCZOS)
            canvas.paste(tile, ((qx - min_qx) * p, (qy - min_qy) * p))
    return canvas


def align_output(output: "np.ndarray", canvas: "np.ndarray") -> tuple["np.ndarray", tuple[int, int]]:
    """Undo the model's small global drift: phase-correlate luminance edges,
    shift output to match the input canvas. Returns (aligned, (dx, dy))."""
    import numpy as np

    def lum(x):
        return x @ np.array([0.299, 0.587, 0.114])

    def edges(x):
        l = lum(x)
        return (np.abs(np.diff(l, axis=1, prepend=l[:, :1]))
                + np.abs(np.diff(l, axis=0, prepend=l[:1, :])))

    ea, eb = edges(canvas), edges(output)
    Fa, Fb = np.fft.fft2(ea - ea.mean()), np.fft.fft2(eb - eb.mean())
    R = Fa * np.conj(Fb)
    R /= np.abs(R) + 1e-9
    surf = np.abs(np.fft.ifft2(R))
    pk = np.unravel_index(np.argmax(surf), surf.shape)
    dy = pk[0] if pk[0] < canvas.shape[0] // 2 else pk[0] - canvas.shape[0]
    dx = pk[1] if pk[1] < canvas.shape[1] // 2 else pk[1] - canvas.shape[1]
    return np.roll(np.roll(output, dy, axis=0), dx, axis=1), (dx, dy)


def seam_cut_horizontal(
    anchor_rows: "np.ndarray",
    output_rows: "np.ndarray",
    smooth_penalty: float = 4.0,
) -> "np.ndarray":
    """Minimum-cost left-to-right seam through the overlap band (DP).

    anchor_rows/output_rows: (band_h, W, 3) — the same band from the locked
    anchor and from the model output. Returns per-column crossover row
    (anchor above, output below). Cost = |anchor - output| at the crossover
    (cut where the two sources agree) + high-gradient avoidance + slope
    penalty (prevents jagged paths and confetti on detailed facades).
    """
    import numpy as np

    band_h, W = anchor_rows.shape[:2]
    diff = np.abs(anchor_rows - output_rows).mean(axis=2)
    # discourage cutting through busy content (edges in the anchor band)
    g = np.abs(np.diff(anchor_rows.mean(axis=2), axis=0, prepend=anchor_rows.mean(axis=2)[:1]))
    cost = diff + 0.5 * g

    total = np.full((band_h, W), np.inf)
    total[:, 0] = cost[:, 0]
    back = np.zeros((band_h, W), dtype=int)
    for x in range(1, W):
        for dyy in (-1, 0, 1):
            prev = np.roll(total[:, x - 1], dyy)
            if dyy == -1:
                prev[-1] = np.inf
            elif dyy == 1:
                prev[0] = np.inf
            cand = prev + cost[:, x] + (smooth_penalty if dyy else 0.0)
            better = cand < total[:, x]
            total[better, x] = cand[better]
            back[better, x] = dyy
    path = np.zeros(W, dtype=int)
    path[-1] = int(np.argmin(total[:, -1]))
    for x in range(W - 1, 0, -1):
        path[x - 1] = path[x] - back[path[x], x]
    return path


def repaste_anchors(
    city: CityConfig,
    generated: Image.Image,
    window: tuple[int, int, int, int],
    anchors: dict[Coord, Image.Image],
    scale: int = 2,
) -> Image.Image:
    """Restore anchor pixels verbatim over a generation output (resized to
    canvas geometry first if the model returned a different size)."""
    p = city.grid.quadrant_px * scale
    min_qx, min_qy, max_qx, max_qy = window
    n_x, n_y = max_qx - min_qx + 1, max_qy - min_qy + 1
    out = generated.convert("RGB").resize((n_x * p, n_y * p), Image.LANCZOS)
    for (qx, qy), tile in anchors.items():
        tile = tile.convert("RGB").resize((p, p), Image.LANCZOS)
        out.paste(tile, ((qx - min_qx) * p, (qy - min_qy) * p))
    return out
