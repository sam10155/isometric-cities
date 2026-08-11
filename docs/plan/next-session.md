# Next Session Plan

*Written 2026-08-07 at wind-down. Read this first; state below was verified today.*

## Where we are

**Phase 1 essentially complete + style gate passed ahead of schedule.**

Working end-to-end today: Toronto config → 3D Tiles fetch (session-billed,
cached) → offline isometric render (error-4.0 meshes, crisp) → Nano Banana Pro
pixel-art style transfer (user-approved, consistent across repeated runs).

- Approved style reference: `style_refs/q123_72_v1.png` (CN Tower quadrant).
  Recipe + prompt: `docs/plan/style-recipe.md`.
- Debug hub: serve repo root on port 9090 (`python3 -m http.server 9090 --bind
  127.0.0.1` from repo root; user tunnels 8080→9090) → `http://localhost:8080/debug/`.
- Tests: 33 passing (`.venv/bin/python -m pytest`).
- Budget: sessions 3/100 (primary billable unit), raw requests ~190/100k
  (diagnostic). `python -m isomap.cli budget`.

## Decisions locked in today

1. **Session billing model** (user-directed, matches NYC project's cost
   profile): root.json fetch = billable unit; caps in `isomap/apibudget.py`.
   **STILL UNVERIFIED against the console**: user should check Billing →
   Reports → SKU "Photorealistic 3D Tiles" (C6E1-98B2-DBD0) usage count is ~3-5,
   not ~190. If wrong → revert to request-based caps (plan doc has numbers).
2. **Gemini API is blocked for automation**: user's AI Studio Pro subscription
   is interactive-only; the API project has zero prepaid credits (429s on both
   image models). Interim workflow: user stylizes renders manually in the
   Gemini web app. `isomap/gemini.py` is ready the moment credits exist.
3. **ToS**: user accepts personal/non-distributed use of cached tile data.

## Next session agenda (in order)

1. **Coverage probe** (~30 min, a few sessions ≈ CAD 0):
   - Fetch + render 4 quadrant types that stress the known-pathological content:
     - lakefront/open water (e.g. Toronto Islands or harbour edge, ~quadrant
       south of (125, 78))
     - ravine/dense trees (Don Valley, east of downtown)
     - low-rise residential (Annex/Cabbagetown area)
     - highway (Gardiner/DVP interchange)
   - Use `isomap.cli locate toronto <lon> <lat>` to pick exact quadrants.
   - User stylizes each in the Gemini web app with the recipe prompt; save to
     `style_refs/` as `q<qx>_<qy>_v1.png`.
   - Watch specifically: water texture invention (NYC's worst failure) and
     tree handling.
2. **Fetch-margin fix** (small but required): renders currently show black
   wedges from unfetched neighbor geometry; the model invents content there.
   Extend `collect_meshes` target region by the isometric view's lean
   (~building_height/tan(30°) southward+westward) so production inputs have
   full margins. Then re-render q(123,72) and confirm no black.
3. **Multi-quadrant seam experiment** (the core technical risk of the whole
   project): fetch/render a 2x2 block of quadrants, stylize each separately in
   the web app, stitch, and look at the seams. This tells us how much the
   infill strategy has to carry before we invest in fine-tuning.
4. **If time — begin training-pair accumulation**: each approved web-app output
   is 1 of the ~40-60 pairs needed for the Qwen/Image-Edit fine-tune (Phase 3).
   Track pairs in a manifest (input path, output path, content tags).

## Deferred / parked

- Gemini API credits (~USD 10-15) — needed only when we automate generation;
  interactive workflow suffices for style/coverage/seam probes.
- Console SKU verification (item 1 above) — before any large fetch run.
- Key hygiene: both API keys were pasted into chat; restrict/rotate when
  convenient (Maps key → restrict to Map Tiles API).
- `plan --commit` CLI path writes PENDING quadrants but nothing consumes them
  yet — the generation loop (Phase 4) will.
- Fine-tuning platform choice (oxen.ai vs Modal direct) — decide at Phase 3.

## Gotchas for whoever picks this up

- Tileset JSON cache keys are tree-position-based ('json:root.3.0.0.3') —
  session-stable. Mesh .glb cache keys are URL-path-based. Don't "simplify".
- `manifests/q123_72_err4.json` lists exact cached glbs for the reference
  quadrant — renders reproduce offline with zero API requests.
- Renderer: glTF is Y-up; ECEF recovery is `(gx, -gz, gy)` in
  `render.py::load_mesh_vertices`. The seam rule R3 uses 4-neighbors
  deliberately (8-neighbor makes growth impossible — see tilelib docstring).
- Session tokens expire ~3h: `_fetch_uri` auto-refreshes root (1 request) on
  404. A 404'd request still bills — don't retry-loop on errors.

## Model research (2026-08-07): fine-tune target for Phase 3

Researched current open-weight image-edit models (verified via web search):
- **Primary: Qwen-Image-Edit-2511** — Apache 2.0, 20B, successor of the NYC
  project's model; de facto standard for paired-data style LoRAs (ostris
  ai-toolkit has dedicated 2511 support, incl. `zero_cond_t`). Lightning
  4-step LoRA → ~2-4 s/1024px tile on H100; ~$0.03/img managed (fal),
  likely <$0.01 self-hosted.
- **Parallel candidate: FLUX.2 klein 4B** — Apache 2.0, ~0.5 s/img (5-10x
  cheaper batch), runs in ~13 GB VRAM; slightly weaker edit fidelity — bake
  off on pixel-art before committing.
- Avoid: FLUX.1 Kontext dev / FLUX.2 dev & klein 9B (non-commercial license);
  OmniGen2/Step1X/HiDream/Bagel (superseded); Z-Image-Edit (weights unreleased).
- Community recipe: pixel-aligned pairs, LoRA rank 32, LR 1e-4, 1024px —
  BUT typical datasets are 300-400 pairs, not NYC's ~40. Budget for ~100-300
  pairs (cheap via the consistent Gemini web-app recipe).

## DECISION (2026-08-07, end of day): stick with Nano Banana end-to-end

No fine-tune unless seams force it. Strategy for fast + seamless:
- **Infill with locked anchors**: input canvas = stylized neighbors + new render
  region; prompt = "continue the pixel-art map, match existing style exactly";
  after generation, re-paste locked anchor pixels over the output so only the
  new region changes. tilelib planner already enforces seam-safe ordering.
- **Big windows**: generate 2K-4K outputs covering 4x4 quadrants (Pro supports
  4K) → ~4x fewer calls AND ~4x fewer seam boundaries than NYC's 2x2 scheme.
- **Color-normalize anchors** post-generation (NYC v2 lesson) to stop drift.
- **Cost path**: web-app 2x2 seam experiment first (manual, free); if good →
  ~USD 15-25 API credits → pilot region in ~90-100 calls (USD 12-25 on Pro,
  half on batch). Build: canvas composer + locked-pixel repaste + generation
  loop wiring gemini.py to the planner.
- Fallback if seams fail: Qwen-Image-Edit-2511 LoRA path (research above).

## Session 2026-08-11: bigger picture, cost-guarded

- Added `render_block()` (multi-quadrant single-pass render, pixel-exact crops
  via `crop_quadrant`), `quadrant_rect_lonlat_region()` (fetch margins), and
  session auto-refresh on 400/401/403 (not just 404).
- Fetched 4x4 downtown block (122-125, 69-72) + 256m margin at error<=8;
  STOPPED at the 1k raw-request safety line (891/mo raw, 5 sessions) with the
  east side complete, west side ~400 requests short. Coverage tool:
  tools/render_strip.py::cached_meshes pattern.
- Rendered seamless 4-quadrant strip (125, 69-72) offline: 
  debug/renders/toronto_strip_125_69-72.png + per-quadrant crops. On debug hub.
- BLOCKED ON: user verifying Billing → Reports SKU C6E1-98B2-DBD0 count
  (~5 = session billing confirmed → finish block fetch immediately;
  ~891 = per-request billing → re-cost, stay surgical).
- Next after verification: complete block fetch → render full 4x4 (2048x2048)
  → user stylizes as ONE Nano Banana generation → first multi-quadrant
  seamless pixel-art picture; then seam experiment with the strip quadrants.

## Design clarification (2026-08-11): generation unit vs bookkeeping unit

User asked whether stylization should be quadrant-at-a-time with stitching.
Resolution: STITCHING YES, PER-QUADRANT NO.
- Quadrant (512px) = bookkeeping unit only (DB, planner, crops, caching).
- Generation unit = the largest window the model handles well (target 4x4
  quadrants / 2048px; model max 4K = 8x8). Bigger windows → fewer calls and
  less seam length. Single-quadrant generation is the worst point in the
  trade-off space.
- Boundaries between windows are handled by anchored infill (locked stylized
  context in the input canvas, repasted after generation), order enforced by
  tilelib planner.
- Today's one-shot strip doubles as the anchor for the first infill stitching
  test: stylize strip → compose adjacent window canvas w/ strip edge as locked
  context → user generates in web app → verify seam programmatically.

## INFILL TEST 1 RESULTS (2026-08-11) — partial pass, core gap identified

Setup: anchor = stylized q(125,71), new = render q(125,72), fresh-chat web-app
generation (user found chat HISTORY CONTAMINATES generations — an earlier
same-chat attempt hallucinated rail tracks from the previous image; ALWAYS use
a fresh chat per generation).

Results:
- Layout: new region matches independently-stylized ground truth 0.88 — render
  drives content, no invention. Global alignment drift only (2,-2)px. Style/
  palette broadly consistent (saturation 0.38 vs 0.43).
- BUT: buildings STRADDLING the boundary get re-interpreted — a glass roof is
  bronze in the anchor, blue-gray in the continuation. Hard repaste seam ratio
  5.0; content-aware seam cut helps streets but cannot fix a building that
  changed material mid-facade.
- Root cause: zero-shot Nano Banana treats anchor pixels as soft style
  guidance, not hard constraint. (NYC solved this by fine-tuning on masked
  infill — the model LEARNED to preserve unmasked content.)
- QA lesson: gradient/seam metrics miss semantic discontinuities; verify
  visually at the join. Edge-corr also useless on dithered output — use
  low-res structural corr (0.89 on the strip).

Options, next tests (in order):
1. Prompt hardening: "partial buildings at the boundary MUST continue with
   exactly the same colors and materials" + include the expected-style example.
2. Boundary placement: route window boundaries through streets/rail/water,
   never through tall buildings (planner could snap boundaries to low-content
   rows/cols — we have the renders to compute this). Test 2 should use the
   70|71 boundary (rail corridor) as the friendly case.
3. If straddling buildings stay broken zero-shot → the documented fallback:
   fine-tune Qwen-Image-Edit-2511 on masked-infill pairs (it exists precisely
   because of this gap). Teacher pairs come from the web-app workflow.

New code: isomap/infill.py (compose_canvas, repaste_anchors, INFILL_PROMPT).
Artifacts: debug/infill/test1_* incl. final_seamcut.png.

## BILLING VERIFIED (2026-08-11): session model CONFIRMED
Cloud Billing SKU report: C6E1-98B2-DBD0 = "4 count / $0.00" while raw traffic
read 891 and our session counter read exactly 4. Root.json sessions are the
billable unit; tile fetches ride free. Map data cost for full Toronto ≈ CAD 0.
Fetch freely; keep the session counter as the primary budget guard.

## INFILL TEST 2 (2026-08-11): PASS — production seam recipe validated

Boundary at the rail corridor + hardened prompt. Straddling buildings (striped
tower, Royal York roof) continued correctly this time. Full recipe that makes
joins invisible (seam ratio 0.32, visually clean):
1. Boundary placement through low-content rows (rail/streets/water) — planner
   should snap window boundaries away from tall buildings.
2. Hardened INFILL prompt (partial buildings MUST keep identical materials) —
   in debug/infill/test2_prompt.txt; promote to isomap/infill.py default.
3. Fresh web-app chat per generation (history contaminates).
4. align_output() — phase-correlation drift correction (typically <=5px).
5. seam_cut_horizontal() — DP min-cost seam in a 96px overlap band, gradient
   avoidance + slope penalty (greedy per-column min left facade confetti;
   DP fixed it).
6. Anchor pixels kept verbatim above the seam path.
All in isomap/infill.py. Artifacts: debug/infill/test2_final_dpseam.png.

ZERO-SHOT NANO BANANA IS SUFFICIENT — no fine-tune needed on this evidence.
Next: stylize the 4x4 block (production window), then grow the map outward
window-by-window using this recipe; build the generation-loop tooling
(canvas composer feeds web-app manually for now, gemini.py when credits).

## MAP STARTED (2026-08-11): founding block committed

- Stylized 4x4 block QA: structural 0.914, alignment (0,0), native 2048.
  Style is finer-grained than the earlier strip — the BLOCK is the canonical
  style lineage; future windows anchor to it (strip/test tiles NOT committed).
- 16 quadrants committed: cities/toronto/map_tiles/q*.png (512px canonical),
  DB state GENERATED (batch block_2026-08-11_webapp).
- tools/assemble_map.py stitches committed tiles -> debug/map/toronto_map.png.
- WINDOW 2 in flight: (122,72)-(125,75) south to harbourfront — anchor row 72,
  new rows 73-75, includes the WATER coverage probe. Fetched (154 req, still
  4 sessions). Canvas + water-hardened prompt: debug/infill/window2_*.
- Crank procedure per window: fetch rows+margin -> render_block -> compose
  canvas (anchors from map_tiles + new renders) -> user generates in fresh
  web-app chat -> QA (structural corr, alignment) -> align_output +
  seam_cut_horizontal + repaste -> slice 512px tiles -> commit to DB +
  map_tiles -> assemble_map.py. Next to build: one `isomap window` CLI that
  does all mechanical steps around the manual generation.

## GEOMETRY BUG + FIX (2026-08-11 later): global screen frame

Window-2 canvas exposed two latent geometry defects:
1. ~~Mirrored camera~~ MISDIAGNOSIS (corrected same day): facade text (TELUS,
   PwC) read correctly all along; the aquarium roof art is painted to read
   from the lake side (rotated, not mirrored). The attempted "fix" itself
   mirrored the world (BMO -> "OMB") and was reverted. Correct camera:
   right = cross(f, up_hint). LESSON: chirality-check with readable FACADE
   text; roof art orientation proves nothing.
2. **Ground-space tiling under a rotated camera** — quadrants project to
   diamonds; per-render centering made each render internally consistent but
   cross-render compositions misregistered (world south = screen diagonal).
   LESSON: one global raster frame from day one; test cross-render
   registration EARLY (now enforced by test_cross_render_registration —
   separately rendered blocks must agree pixel-exactly on shared tiles).

Fix (all in isomap/render.py): ScreenFrame — global screen coords anchored at
the city grid origin's projection; tiles are SCREEN tiles (new indices t*,
CN Tower tile = (138,18)-ish; founding block (137,17)-(140,20)). Inverse
projection (iterative, handles ellipsoid drop vs tangent plane) derives fetch
regions incl. 650m building-lean expansion. render_screen_block/crop_tile
replace render_block/render_quadrant/crop_quadrant.

Consequences: DB reset; mirrored map tiles archived to
cities/toronto/archive/map_tiles_mirrored_v1/; founding block must be
RE-STYLIZED once from the corrected render (in progress). Old ground-quadrant
indices in earlier notes are obsolete — screen tiles are the map unit now.
Planner note: plan_rect's corner-anchored sweep goes Unfillable when the rect
contains a pre-existing island — planner v2 must seed growth from existing
content (matches NYC's "planning was hardest" experience).

## Corrected frame finalized (2026-08-11 end of day)

- ScreenFrame has SCREEN_OFFSET (40960, 0) so the city sits in positive tile
  space. Founding block = screen tiles (180,17)-(183,20). All 35 tests green
  incl. cross-render registration. Camera chirality verified (BMO/TD read
  correctly in debug/renders/toronto_sblock_founding.png).
- WAITING ON USER: re-stylize the founding render (debug hub has instructions
  + prompt) -> save style_refs/sblock_founding_pixel.png. Then: QA -> slice ->
  commit tiles (batch sblock_2026-08-11) -> assemble_map (update
  tools/assemble_map.py naming from q{x}_{y} to t{ti}_{tj}) -> next window
  south (harbourfront/water probe) via the validated infill recipe.
- Cost today: 0 sessions consumed beyond the standing 4; ~2.4k raw requests
  (traffic only, $0.00 verified).

## Orientation decision (2026-08-11): keep azimuth 225; angles as future option

User decision: keep the current view (camera from NE looking SW; Lake Ontario
along the TOP of the map; north = down-right). Rationale: all committed work
uses it; changing now costs a founding re-stylization.

FUTURE REQUIREMENT (user-requested): support rendering the map at other
angles later. Design implication: a camera azimuth defines a whole map
LINEAGE — its own ScreenFrame, its own tile indices, its own renders AND its
own stylized tiles (nothing transfers between orientations except the fetch
cache, which is orientation-agnostic ECEF geometry — the expensive part is
one full re-stylization per orientation). When implementing: make orientation
a named preset in city config (e.g. camera_presets: {ne: 225, lake: 45}),
key map storage + DB + manifests by preset name
(map_tiles/<preset>/t*.png), and ScreenFrame takes the preset. The 3D mesh
cache is shared across presets — fetching is already paid for.

## WATER PROBE PASSED + MAP AT 28 TILES (2026-08-11)

Water window generated, QA'd (structural 0.931, alignment (0,0)), assembled
with bottom-anchor seam cut (band = top 96px of anchor row; seam ratio 0.46)
and committed. Open water renders flat+dithered per prompt; marina boats
preserved; Rogers dome continues across the boundary. Map: 28 tiles,
(180,14)-(183,20), debug/map/toronto_map.png. All pathological-content fears
from the NYC writeup so far: handled zero-shot with the hardened prompts.
Next crank options: east (ti-) toward Yonge/St Lawrence, west (ti+) toward
Bathurst, or down (tj+) toward Queen/City Hall. Also queued: `isomap window`
CLI to automate fetch->render->canvas->commit around the manual generation;
planner v2 (seed from existing content).

## REPAIR TOOL (2026-08-11): viewer rectangle-select + repair pipeline

- Viewer (debug/viewer/) now has "Select repair region": drag a rect on the
  map -> /api/repair (tools/debug_server.py replaces plain http.server) ->
  instant export to debug/repair/: current map crop, BASE RENDER crop (from
  cities/toronto/render_tiles/, stocked by every prepare), and the repair
  canvas (stylized margin ring anchor + render in the rect) + repair prompt.
- Round trip: user stylizes canvas in web app -> style_refs/<name>_pixel.png
  -> `python -m isomap.repair commit toronto <name> <file>` -> align + 4-edge
  DP seam + write back only affected tiles + reassemble + pyramid.
- Built because window w183_23_186_26 came back with a hallucinated water
  patch (top-left; missing buildings) — likely chat contamination again.
  Map committed WITH the artifact (structural 0.870, lowest yet); repair
  pending user's rectangle selection in the viewer.

## State at 2026-08-11 end of day (v2)

- MAP: 121 tiles (180,14)-(189,26); final squaring window w186_23_189_26
  staged (user generating). ~10 windows + 3 repair applications, all seams
  invisible. Git repo initialized (main), docs/ = Pages-ready viewer+pyramid.
- Key fixes this session: stale-canvas rule (commits compose anchors fresh
  from current tiles), OSM ground-truth water detection (isomap/water.py,
  cities/toronto/water.json cached), conditional water prompt, repair tool
  (viewer rectangle -> canvas+render export -> repair commit).
- Prompt lessons (memory'd): fresh chat per generation; never mention absent
  content types.
- Next: commit squaring window (130 tiles) -> continue growth (candidates:
  north rows 27+ toward College/Queen's Park proper, west cols 190+, or
  south/lake rows 13-). Bigger arcs: automate generation via API credits
  (~USD 15 covers pilot); planner v2 (auto window choice); color
  normalization pass (NYC lesson — drift not yet visible but will come).
