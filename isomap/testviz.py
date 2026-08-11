"""Visual test artifacts (NYC lesson #20).

Tests of tiling logic call render_scenario() to emit a PNG showing the grid
state, the window(s) under test, and the outcome. build_debug_page() collects
all artifacts into debug/tests/index.html for at-a-glance verification.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .tilelib import GridState, Plan, QState, Rect, Window

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "debug" / "tests"

CELL = 48  # px per quadrant cell
PAD = 24

COLORS = {
    QState.EMPTY: (240, 240, 240),
    QState.PENDING: (255, 214, 102),
    QState.GENERATED: (108, 167, 108),
}
GRID_LINE = (200, 200, 200)
WINDOW_OK = (46, 92, 255)
WINDOW_BAD = (220, 38, 38)
TEXT = (30, 30, 30)


def _bounds(state: GridState, extras: list[Window | Rect]) -> Rect:
    xs: list[int] = []
    ys: list[int] = []
    for st in (QState.PENDING, QState.GENERATED):
        for (x, y) in state.quadrants(st):
            xs.append(x)
            ys.append(y)
    for e in extras:
        if isinstance(e, Window):
            xs += [e.qx, e.qx + 1]
            ys += [e.qy, e.qy + 1]
        else:
            xs += [e.min_qx, e.max_qx]
            ys += [e.min_qy, e.max_qy]
    if not xs:
        xs, ys = [0], [0]
    return Rect(min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)


def render_scenario(
    name: str,
    state: GridState,
    windows_ok: list[Window] = (),
    windows_bad: list[Window] = (),
    target: Rect | None = None,
    caption: str = "",
    out_dir: Path | None = None,
) -> Path:
    """Render a grid state + windows to debug/tests/<name>.png and return the path."""
    out_dir = out_dir or ARTIFACT_DIR
    extras: list[Window | Rect] = list(windows_ok) + list(windows_bad)
    if target:
        extras.append(target)
    b = _bounds(state, extras)

    w_px = b.width * CELL + 2 * PAD
    h_px = b.height * CELL + 2 * PAD + 20
    img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def cell_xy(qx: int, qy: int) -> tuple[int, int]:
        return PAD + (qx - b.min_qx) * CELL, PAD + (qy - b.min_qy) * CELL

    for qy in range(b.min_qy, b.max_qy + 1):
        for qx in range(b.min_qx, b.max_qx + 1):
            x0, y0 = cell_xy(qx, qy)
            d.rectangle(
                [x0, y0, x0 + CELL, y0 + CELL],
                fill=COLORS[state.get((qx, qy))],
                outline=GRID_LINE,
            )

    if target:
        x0, y0 = cell_xy(target.min_qx, target.min_qy)
        x1, y1 = cell_xy(target.max_qx + 1, target.max_qy + 1)
        d.rectangle([x0, y0, x1, y1], outline=(150, 150, 150), width=2)

    for w, color in [(w, WINDOW_OK) for w in windows_ok] + [
        (w, WINDOW_BAD) for w in windows_bad
    ]:
        x0, y0 = cell_xy(w.qx, w.qy)
        d.rectangle([x0 + 2, y0 + 2, x0 + 2 * CELL - 2, y0 + 2 * CELL - 2],
                    outline=color, width=4)

    d.text((PAD, h_px - 18), caption or name, fill=TEXT)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    img.save(path)
    return path


def render_plan(
    name: str,
    initial: GridState,
    plan: Plan,
    target: Rect,
    out_dir: Path | None = None,
) -> Path:
    """Render plan execution as a numbered sequence on the final state."""
    out_dir = out_dir or ARTIFACT_DIR
    sim = initial.copy()
    order: dict[tuple[int, int], int] = {}
    for i, w in enumerate(plan.windows):
        for q in w.quadrants():
            if sim.get(q) is QState.EMPTY:
                sim.set(q, QState.GENERATED)
                order[q] = i + 1

    path = render_scenario(
        name, sim, target=target,
        caption=f"{name}: {plan.calls} calls, {plan.new_quadrants} quadrants",
        out_dir=out_dir,
    )
    # overlay call-order numbers
    img = Image.open(path)
    d = ImageDraw.Draw(img)
    b = _bounds(sim, [target])
    for (qx, qy), n in order.items():
        x0 = PAD + (qx - b.min_qx) * CELL
        y0 = PAD + (qy - b.min_qy) * CELL
        d.text((x0 + CELL // 2 - 6, y0 + CELL // 2 - 6), str(n), fill=TEXT)
    img.save(path)
    return path


def build_debug_page(out_dir: Path | None = None) -> Path:
    out_dir = out_dir or ARTIFACT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    pngs = sorted(out_dir.glob("*.png"))
    rows = "\n".join(
        f'<figure><img src="{p.name}"><figcaption>{p.stem}</figcaption></figure>'
        for p in pngs
    )
    html = (
        "<!doctype html><meta charset='utf-8'><title>tilelib test artifacts</title>"
        "<style>body{font-family:sans-serif;background:#fafafa}"
        "figure{display:inline-block;margin:12px;padding:8px;background:#fff;"
        "border:1px solid #ddd}figcaption{font-size:12px;margin-top:4px}</style>"
        f"<h1>tilelib test artifacts ({len(pngs)})</h1>{rows}"
    )
    path = out_dir / "index.html"
    path.write_text(html)
    return path
