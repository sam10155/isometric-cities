# Isometric Toronto — Adaptation Plan

Goal: a system that can be pointed at **any city in the world** and produce an isometric
pixel-art map in the style of Isometric NYC. First target: **Toronto, Canada**.

The key architectural difference from the original: the NYC project was single-city and
accreted NYC-specific assumptions. We design for **city-as-configuration** from day one —
a city is a bounding polygon + name + a handful of tuning parameters, and everything else
is derived.

## What must be parameterized per city

| Concern | NYC original | Our design |
|---|---|---|
| Geometry source | Google 3D Tiles, NYC CityGML explored | Google 3D Tiles as universal default; per-city overrides possible |
| Boundary | Hand-drawn polygon editor ("bounds app") | Same tool, but city-agnostic; seed from OSM admin boundary, refine by hand |
| Coordinate system | NYC-specific projections | Config-driven CRS per city (Toronto: MTM zone 10 / EPSG:2952 or UTM 17N / EPSG:32617); grid math in one shared library |
| Terrain mix | Lots of water, dense high-rise, flat | Detected per city; drives training-data augmentation balance |
| Style training data | ~40 NYC pairs | Per-city pairs (styles may share a base set + city-specific additions for distinctive landmarks/vegetation) |

## Toronto-specific considerations

**Geography / content mix:**
- **Lake Ontario** dominates the southern edge — a huge continuous water body, plus the
  harbour and the Toronto Islands. All the NYC water lessons apply (checkerboard training
  trick, water mask + auto color correction). The lake edge also means a large share of
  boundary tiles are pure water — clip the export polygon tightly to avoid generating
  empty lake.
- **Ravine system** (Don Valley, Humber, Rouge) — heavily treed corridors cutting through
  the city. Trees were the worst NYC failure mode; Toronto's ravines make tree handling a
  first-class concern. Oversample ravine/park tiles in training data.
- **Distinctive landmarks** needing good renders and possibly dedicated training pairs:
  CN Tower (very tall thin structure — check how the orthographic render and the model
  handle it), Rogers Centre dome, City Hall's curved towers, Casa Loma, the Gardiner
  Expressway elevated sections, streetcar-lined avenues.
- **Building mix:** dense downtown high-rise core, but vast areas of low-rise residential
  with mature street trees — different texture from Manhattan; validate style on both.
- **Seasonality:** Google 3D Tiles imagery of Toronto may be captured in a specific
  season; check tree foliage state before building training data.

**Data sources:**
- **Primary: Google Maps Photorealistic 3D Tiles API** — Toronto is covered. Same
  render-and-export approach as NYC v-final. Requires a Google Maps Platform API key;
  check current pricing/quotas for 3D Tiles renderer usage.
- Fallback/reference: City of Toronto Open Data has a **3D Massing model** (whitebox
  buildings, multiple formats) and orthophoto imagery — same category as NYC CityGML,
  same composite-inconsistency risk, so reference only.
- **OSM** for water polygons, park polygons, and the initial city boundary — feeds the
  water/tree classifiers and the bounds tool, and is available for every future city.

**Scope estimate:** City of Toronto proper is ~630 km². At NYC's tile density (~40k
quadrants for NYC's ~780 km² land area) expect a similar order of magnitude — roughly
30–40k quadrants for the full city, less if we start with a downtown-core pilot
(recommended: Bathurst→Don River, lake→Bloor first, ~25 km², a few thousand quadrants).

## Phased build plan

### Phase 0 — Foundations (city-agnostic core)
- Repo scaffolding; `cities/toronto/config.yaml` (name, CRS, boundary seed, grid origin,
  tile size, zoom).
- Shared libraries first (the NYC project's biggest process lesson):
  - `gridlib`: world grid ↔ pixel/quadrant coordinate math, CRS handling.
  - `tilelib`: quadrant schema, seam rules, generation-plan validation — with **visual
    test artifacts** (every test emits an illustrative image to a static debug page).
- SQLite schema for quadrants: coords, status, water fraction, batch id, flags.

### Phase 1 — Rendering (Toronto pixels on screen)
- Google 3D Tiles orthographic web renderer; export 1024x1024 renders registered to the
  grid. Validate registration by stitching a 4x4 block of downtown renders seamlessly.
- Bounds app: OSM Toronto boundary as the seed polygon, hand-refine, persist to DB.

### Phase 2 — Style prototype
- Marimo (or similar) notebook: prompt a frontier image model (e.g. current Gemini image
  gen / Nano Banana equivalent) on downtown Toronto renders until the pixel-art style is
  right. Lock a style reference sheet.
- Curate ~40–60 input/output training pairs across content types: high-rise core,
  low-rise residential, ravine/trees, lakefront/pure water, CN Tower, highways, rail
  corridors. **Color-normalize all pairs** (lesson #5).
- Build training pairs in two flavors from the start: full-tile and **infill-masked**
  (don't repeat NYC's sequencing — infill was retrofitted).
- Apply the **water checkerboard augmentation** from day one (lesson #6).

### Phase 3 — Fine-tune + single-tile loop
- Fine-tune Qwen/Image-Edit (oxen.ai or direct); evaluate per content type.
- Wire a minimal generate-one-block loop: pick 2x2 quadrant window → build masked input →
  call model → write quadrants to DB → view in a simple web grid viewer.

### Phase 4 — Generation app + planning
- Web app: map of quadrant states, select-and-generate, model/prompt swapping, retry.
- Tile-planning algorithm (seam-free ordering/packing). **Human-design this** (lesson
  #12); implement in `tilelib` with exhaustive visual tests.
- Water classifier (OSM water polygons + render analysis) populating quadrant metadata;
  automatic post-generation water color correction; anchor-tile color normalization
  excluding water pixels.

### Phase 5 — Scale-out
- Deploy the fine-tuned model on **Modal** (serverless GPU, N parallel instances) —
  skip the rented-VM stage entirely (lesson #14).
- Plan-driven batch runs with retries and parallel queues; generate the downtown pilot
  region end-to-end.

### Phase 6 — QA + correction
- Review/flagging UI over the generated map; one-click water fix; photo-editor
  round-trip export/import for manual repairs.
- Budget real human hours here — this is the known 90%-of-the-time tail, concentrated in
  the ravines and lakefront.

### Phase 7 — Viewer + full-city run
- Build the image pyramid; OpenSeaDragon deep-zoom viewer. Expect this to need the most
  human debugging of any app component (lesson: agents struggle with high-perf graphics
  + touch).
- Expand generation from the pilot region to the full boundary polygon.
- Optional layers later (the "snow" pattern): winter Toronto is thematically perfect.

### Phase 8 — Second city (proof of generality)
- Point the system at a second city with a different profile (e.g. a hilly or desert
  city) touching only `cities/<name>/config.yaml` + a style training pass. Whatever
  breaks defines the remaining NYC-isms to refactor out.

## API budget constraint (resolved 2026-08-07)

Google Maps Platform tier: **1,000 free requests/month, then CAD 8.4495/1k**. Rules:
- All Google API calls go through `isomap/apibudget.py` (hard cap 900/month by default;
  raising it is an explicit user decision).
- Cache every fetched tile permanently (`cities/<name>/tile_cache/`); never re-fetch.
- 3D Tiles renderer sessions: one root tileset request can serve many tile fetches —
  measure how requests are actually billed with a single-quadrant test before any batch.
- Develop the renderer against cached data for one quadrant first; batch fetches are
  planned, counted, and reported before running.

### Documentation findings (2026-08-07, from official Google docs)

- **Billing**: SKU "Map Tiles API: Photorealistic 3D Tiles" (C6E1-98B2-DBD0) bills each
  "request that returns a 3D tile" — i.e. **every .glb fetch is billable**. Tileset JSON
  requests likely aren't (they don't return a 3D tile), but we count everything.
- **Billing model decision (2026-08-07)**: we operate on the **session-billing model**
  (like the original NYC project): one root.json request opens a >=3h session and tile
  fetches ride on it; the root request is the billable unit. The console "requests"
  metric (which matched our raw counter: 143 = 143) shows *traffic*, not billing — the
  authoritative number is Billing → Reports → SKU C6E1-98B2-DBD0 usage count.
  **VERIFY on the console SKU report after the next fetch runs**; if SKU count tracks
  raw requests instead of sessions, revert apibudget caps to request-based immediately.
  Under session billing: pilot ≈ full city ≈ CAD 0 (tens of sessions, free tier 1k).
  Budget guard: sessions capped 100/month (primary), raw requests 100k/month (runaway
  backstop).
- **Sessions**: one root tileset request grants ≥3 hours of tile requests; the session
  token rides in child URIs. Reuse the session; re-fetch root only after expiry.
- **Renderer requirement**: ToS requires a renderer displaying copyright attribution
  (CesiumJS 1.91+ named). Attribution must be shown on any rendered output.
- **Policy note**: Map Tiles policies restrict pre-fetching/storing/extraction — aimed at
  data hoarding for commercial redistribution. User decision (2026-08-07): our use is
  personal and non-distributed (we cache to minimize billable requests, derive stylized
  artwork, don't redistribute tile data), so we proceed. Keep the cache private and
  volumes minimal regardless — it's also what keeps costs down.

### Cost projections (2026-08-07, from measured single-quadrant data)

Measured: CN Tower quadrant at geometric error 4.0 = 44 glb meshes covering the quadrant
plus ~165 m margin; tileset JSON overhead ~25%; ~4.3 marginal requests/quadrant once the
shared hierarchy is cached (meshes are shared between adjacent quadrants).

| Scope | Requests | Map Tiles cost (CAD 8.4495/1k after 1k free) |
|---|---|---|
| Pilot region (1,394 quadrants) | ~6k | **~CAD 42** (worst case, no mesh sharing: ~CAD 640) |
| Full City of Toronto (~35k quadrants) | ~150k | **~CAD 1,260** |

Gemini image generation (style transfer prototyping + training pairs; **no free tier** on
image models):
- gemini-2.5-flash-image (Nano Banana): $0.039/image out + ~$0.001/image in
- gemini-3-pro-image (Nano Banana Pro): ~$0.134/image (1-2K), batch ~$0.067
- Style prototyping (~50-100 generations w/ Pro): **~USD 7-13**
- Training pairs (~60 w/ Pro at 1K): **~USD 8** — teacher-model usage is cheap.
- (Generating ALL tiles with Pro instead of fine-tuning: 35k x $0.134 ≈ USD 4.7k +
  retries — this is why the NYC project fine-tuned a small model; ours will too.)

## Open questions to resolve early
1. Toronto 3D Tiles imagery quality/capture season (checked visually in Phase 1).
2. Fine-tuning platform: oxen.ai again, or train directly on Modal to keep one platform?
3. Exact quadrant ground resolution (m/pixel) — drives tile count, cost, and how legible
   individual houses are; prototype 2–3 options on the same downtown block.
4. Whether one global style model can serve multiple cities, or each city needs its own
   fine-tune (affects Phase 8 design).
