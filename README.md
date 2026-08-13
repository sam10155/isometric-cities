# iso-map

**🗺️ Live map: https://sam10155.github.io/isometric-cities/**

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

Phase 0 + Phase 1 complete, style gate passed (2026-08-07). The full chain works:
3D Tiles fetch (session-billed, cached) → offline isometric render → Nano Banana
Pro pixel-art transfer. Approved style reference: `style_refs/q123_72_v1.png`;
recipe in `docs/plan/style-recipe.md`. **Resume: `docs/plan/next-session.md`.**

```
isomap/config.py    city config loader (cities/<name>/config.yaml)
isomap/gridlib.py   WGS84 <-> city CRS <-> quadrant coordinate math
isomap/tilelib.py   quadrant states, seam rules (R1-R3), seam-free planner
isomap/store.py     SQLite quadrant state store
isomap/apibudget.py Google API request counter + hard monthly cap (900)
isomap/tiles3d.py   3D Tiles client: cache-first, budget-counted traversal
isomap/render.py    software orthographic isometric renderer (numpy/PIL)
isomap/testviz.py   visual test artifacts -> debug/tests/index.html
isomap/cli.py       info / locate / plan / status / budget commands
```

API usage so far: 34/900 this month (`python -m isomap.cli budget`).

Setup and use:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest              # 28 tests; view debug/tests/index.html
.venv/bin/python -m isomap.cli info toronto
.venv/bin/python -m isomap.cli plan toronto --pilot
```

Next: Phase 1 — Google 3D Tiles orthographic renderer + bounds app
(see [docs/plan/toronto-adaptation.md](docs/plan/toronto-adaptation.md)).

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
