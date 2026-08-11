# The Map-Growing Workflow

The operator's manual for growing and maintaining the isometric pixel-art map.
Two loops: **grow** (add a window of new tiles) and **repair** (fix an artifact
inside committed tiles). One human generation step sits at the center of each;
everything else is tooling.

## Prerequisites (once per machine/session)

```bash
# serve the hub + viewer + repair API (background)
.venv/bin/python tools/debug_server.py &
# your side: ssh -L <localport>:localhost:9090 mytuser@10.162.90.85
#            then browse http://localhost:<localport>/debug/
```

- `.env` must contain `GOOGLE_MAPS_API_KEY` (Map Tiles API enabled).
- `cities/toronto/water.json` exists (OSM water data; re-fetch with
  `python -c "from isomap.config import load_city; from isomap.water import
  fetch_water_data; fetch_water_data(load_city('toronto'))"`).

## Loop 1: GROW

### 1. Pick the next window
- Windows are 4x4 screen tiles, e.g. `(186, 23, 189, 26)` = min_ti min_tj
  max_ti max_tj. The map's committed extent is on the hub / `isomap.cli status`.
- The window MUST overlap committed tiles in one of the supported anchor
  layouts (auto-validated): full rows at top/bottom, full columns at
  left/right, or an L-corner (e.g. top+left). 3 new rows/cols per window is
  the normal stride; corner windows fill 3x3.

### 2. Prepare
```bash
.venv/bin/python -m isomap.window prepare toronto 186 23 189 26
```
Does everything mechanical: fetches 3D tiles (session-billed ≈ free, budget-
guarded), renders the window in the global screen frame, saves per-tile
renders, composes the infill canvas (committed pixel art as anchors + fresh
render elsewhere), picks the prompt (water note only if OSM says the ground
truly has water — override with `--water/--no-water`), and prints the manual
steps. Canvas + prompt land in `debug/infill/` and on the hub.

### 3. Stylize (the human step — Gemini web app, Nano Banana Pro)
- **FRESH CHAT. Always.** Chat history contaminates generations (hallucinated
  water/rail both came from reused chats).
- Attach the canvas, paste the prompt (use the prepared prompt verbatim — it
  contains the anchor-continuation hardening; don't add content words for
  things not in the frame).
- Sanity-check the output: same aspect, anchors look continued, no invented
  lakes/railways. Regenerate in a NEW fresh chat if off.
- Save into `style_refs/` with the window name in the filename
  (e.g. `w186_23_189_26_canvas_pixel.png` — any name containing the id works).

### 4. Commit
```bash
.venv/bin/python -m isomap.window commit toronto 186 23 189 26 style_refs/w186_23_189_26_pixel.png
```
QA (structural fidelity gate 0.75; alignment vs what the model saw), DP
seam-cut on every anchor boundary (anchors always come from the CURRENT map
tiles — interim repairs are never clobbered), tile write-back, map + viewer
pyramid rebuild. Read the printed numbers: structural ≥ ~0.87 and seam ratios
< 1.0 are normal. Then check the join visually in the viewer.

### 5. Repeat
Prepare the next window immediately so a canvas is always staged.

## Loop 2: REPAIR

1. Spot an artifact in the viewer (`/debug/viewer/`).
2. Click **✂ Select repair region**, drag a rectangle around it (generous).
3. Download the exported **canvas** (stylized margin ring + base render
   inside; the render is ground truth for WHAT, the ring for HOW).
4. Stylize in a **fresh chat** with the export's prompt; save into
   `style_refs/` with the repair id in the name.
5. Commit with the command shown in the viewer panel:
   `python -m isomap.repair commit toronto <id> style_refs/<file>`.

## Rules that exist because something went wrong

| Rule | Incident |
|---|---|
| Fresh chat per generation | model copied rail/water from chat history |
| Never mention absent content in prompts | "water" note in waterless window → invented lake |
| Anchors come from current tiles at commit | window commit reverted an interim repair |
| Chirality-check with facade text, not roof art | "mirror bug" misdiagnosis |
| Water detection = OSM ground truth, not pixels | blue rooftops false-positived |

## Costs
- Map data: sessions are the billable unit (verified); a work-day is 1-3
  sessions ≈ $0.00. Budget guard: `python -m isomap.cli budget`.
- Generation: your Gemini web-app usage (AI Pro). API automation needs prepaid
  credits (~USD 15 covers the pilot region) — `isomap/gemini.py` is ready.

## Publishing
`docs/` is the GitHub Pages site (viewer + pyramid, rebuilt on every commit).
Push → Settings → Pages → main`/docs`.
