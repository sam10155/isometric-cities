# iso-map

**🗺️ Live maps: https://sam10155.github.io/isometric-cities/** —
[Toronto](https://sam10155.github.io/isometric-cities/toronto/) ·
[Ottawa](https://sam10155.github.io/isometric-cities/ottawa/) ·
[Victoria](https://sam10155.github.io/isometric-cities/victoria/) ·
[Vancouver](https://sam10155.github.io/isometric-cities/vancouver/) ·
[Montreal](https://sam10155.github.io/isometric-cities/montreal/)

Generate isometric pixel-art maps of real cities — point the system at any city and get
a SimCity-2000-style deep-zoom map. First target: **Toronto, Canada**.

Inspired by (and methodologically based on) cannoneyed's [Isometric NYC](https://isometric.nyc)
project.

**Full operator guide: [WORKFLOW.md](WORKFLOW.md)**

## Docs

| Doc | Purpose |
|---|---|
| [docs/reference/isometric-nyc-original-writeup.md](docs/reference/isometric-nyc-original-writeup.md) | The original essay, preserved verbatim for reference |
| [docs/reference/pipeline-breakdown.md](docs/reference/pipeline-breakdown.md) | Stage-by-stage analysis of the NYC pipeline: data → render → fine-tune → infill → scale → QA → viewer |
| [docs/reference/lessons-learned.md](docs/reference/lessons-learned.md) | Every transferable lesson, numbered, as design constraints |
| [docs/plan/toronto-adaptation.md](docs/plan/toronto-adaptation.md) | Our plan: city-as-configuration architecture, Toronto specifics, phased build plan |

## Status

Five cities live (2026-09-01): **Toronto 1597 tiles** (162–204 × 2–44, incl.
the full Port Lands), **Ottawa 532**, **Victoria 256**, **Vancouver 247**,
**Montreal 169** — the four smaller cities are complete rectangles, all grown
window-by-window via the 4×4-tile prepare/commit loop (render → pixel-art gen → seam QA → deep-zoom pyramid update). Style
recipe: `docs/plan/style-recipe.md`. **Resume: `docs/plan/next-session.md`.**

```
isomap/config.py    city config loader (cities/<name>/config.yaml)
isomap/gridlib.py   WGS84 <-> city CRS <-> quadrant coordinate math
isomap/tilelib.py   quadrant states, seam rules (R1-R3), seam-free planner
isomap/store.py     SQLite quadrant state store
isomap/apibudget.py Google API session counter + hard monthly caps
isomap/tiles3d.py   3D Tiles client: cache-first, budgeted, parallel fetch
isomap/render.py    software orthographic isometric renderer (numpy/PIL)
isomap/window.py    prepare/commit loop: canvases, seam QA, force gates
isomap/pyramid.py   deep-zoom (DZI) pyramid updates for the viewers
isomap/cli.py       info / locate / plan / status / budget commands
tools/debug_server.py  local hub: staged canvases, QA views, repair API
```

Billing is session-based (root.json fetches); tile traffic rides free on the
session — `python -m isomap.cli budget` shows both counters ($0 to date).

Setup and use:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest              # tests; view debug/tests/index.html
.venv/bin/python -m isomap.cli info toronto
.venv/bin/python -m isomap.window prepare toronto 201 29 204 32
```

## Pipeline at a glance

```
Google Maps 3D Tiles ─→ orthographic isometric renders (1024x1024, grid-registered)
        ─→ fine-tuned image-edit model (frontier model bootstraps ~40-60 training pairs)
        ─→ seam-free infill generation over 512px quadrants (SQLite state, plan-driven)
        ─→ serverless GPU batch generation (Modal)
        ─→ human QA with purpose-built micro-tools
        ─→ deep-zoom viewer (OpenSeaDragon)
```

## Core design principles (carried over from NYC)

- City is configuration: boundary polygon + CRS + tuning params; everything else derived.
- Shared, visually-tested libraries for grid/tiling logic **before** any app is built.
- Water and trees are the known-pathological content — mitigations baked in from day one
  (checkerboard water augmentation, water masks, terrain-balanced training data,
  color normalization pre-train and post-generate).
- Human QA is a first-class pipeline stage; automated image QA doesn't work yet.
- Micro-tools liberally; CLI → library → app.
