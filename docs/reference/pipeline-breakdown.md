# Pipeline Breakdown — Isometric Pixel-Art City Map

A distilled, stage-by-stage analysis of the Isometric NYC methodology, written so we can
re-implement it for any city. Each stage lists what the original did, why, key parameters,
and what generalizes vs. what was NYC-specific.

## Overview of the pipeline

```
1. Source geometry        Google Maps 3D Tiles (photorealistic mesh + textures)
        │
2. Isometric render       Orthographic web renderer → 1024x1024 tile renders
        │
3. Style transfer         Fine-tuned Qwen/Image-Edit: render → pixel art
        │                 (bootstrapped with a frontier image model + ~40 training pairs)
4. Seamless assembly      Infill/inpainting strategy: mask-aware 2x2 quadrant generation
        │                 staggered against already-generated neighbors
5. Scale-out              Serverless GPU inference (Modal), plan-driven batch generation
        │
6. QA + correction        Human review with purpose-built micro-tools (water fix,
        │                 color normalization, external editor round-trip)
7. Viewer                 Deep-zoom tiled image viewer (OpenSeaDragon)
```

---

## Stage 1: Source geometry & imagery

**What they did:**
- First attempt: CityGML 3D building data (NYC 3D, 3DCityDB, NYC CityGML) rendered as a
  "whitebox" (untextured geometry) composited with top-down satellite imagery.
  - **Failed** — too much inconsistency between whitebox geometry and satellite texture;
    the image model hallucinated heavily when reconciling them.
- Final approach: **Google Maps Photorealistic 3D Tiles API** — precise geometry AND
  textures in one coherent source. Downloaded geometry per tile, rendered in a web
  renderer with an **orthographic camera**, exported tiles precisely registered to a
  fixed grid.

**Why it matters:**
- The image model is doing *style transfer*, not *scene invention*. The more complete and
  self-consistent the input render, the less the model hallucinates. Geometry + texture
  from a single source is the key insight.

**Key technical details:**
- Orthographic (not perspective) camera → true isometric look, and critically, makes
  tiles composable on a grid (no perspective distortion at tile edges).
- Coordinate projection handling was a major source of agent back-and-forth (GIS
  projections, geometry labeling schemas). Expect to spend time here.
- Renders exported at 1024x1024 per tile, registered to a fixed world-space grid.

**Generalizes?** Yes — Google 3D Tiles covers most major world cities including Toronto.
This is the piece that makes the "any city" goal feasible. CityGML availability varies
wildly by city; 3D Tiles does not.

---

## Stage 2: Tile/quadrant schema

**What they did:**
- Atomic unit: **512x512 pixel "quadrant"**.
- One model call generates a **2x2 block of quadrants (1024x1024)** from an input image
  with a mask.
- **SQLite** database stores every quadrant: coordinates + optional metadata (e.g. water
  classification, generation status, source generation batch).
- Estimated ~40k tiles for NYC.

**Why it matters:**
- Quadrant granularity < generation granularity means each generation can overlap
  previously generated content, which enables the infill strategy (Stage 4).
- Boring tech (SQLite, files on disk) — deliberately chosen. Domain modeling and data
  storage called out as critical.

---

## Stage 3: Style model

**What they did:**
1. **Prototype with a frontier image model** (Nano Banana Pro / Gemini image gen) via
   prompt engineering until the target pixel-art style was achievable. Used a marimo
   notebook for experimentation.
   - Problems at scale: ~50% style consistency at best, slow, expensive. Fine for
     bootstrapping, not for 40k tiles.
2. **Fine-tune a small image-edit model**: Qwen/Image-Edit on oxen.ai.
   - Training set: **~40 input/output pairs** (isometric render → pixel art tile).
   - Cost: ~$12, ~4 hours. Remarkably cheap.
3. The frontier model effectively becomes the *teacher*: it produces the training pairs
   (with human curation), and the fine-tuned model does the volume work.

**Key lessons baked in from the v2 (snow) iteration:**
- **Color-normalize all training tiles** before fine-tuning. Style/color drift across the
  map is the #1 at-scale failure; the infill model can't blend contrasting styles — it
  picks one and creates a visible "front" between styles.
- **Data augmentation balance matters**: oversample water and terrain tiles in training
  data, or the model fails on them. This tuning is "more art than science" — expect to
  train several variants.
- **Water checkerboard trick**: flat water regions in training inputs were overlaid with
  a 2x2 checkerboard pattern. Rationale: an edit/diffusion model can't distinguish a flat
  color from pure noise, so it hallucinates onto blank water. The structured checkerboard
  gives it signal that "this is water → fill with a pure color."

---

## Stage 4: Infill / seamless assembly

**What they did:**
- Naive per-tile generation produces visible seams between tiles. Solution: **infill
  ("inpainting") generation**.
- Training pairs were built with a percentage of the target image **masked out**, and the
  surrounding already-stylized content present. The model learns to complete the masked
  region consistently with existing neighbors.
- Generation is **staggered**: new quadrants are always generated adjacent to (and
  partially overlapping) already-generated content, which anchors the style and content.
- Generation rule: *no quadrant may be generated such that a seam will be present* —
  i.e., a generation must either be fully anchored by existing neighbors on its shared
  edges or be a fresh "anchor" placement per the plan.
- Post-generation, **anchor tiles are color-normalized** (excluding water pixels from the
  color balance calculation — water skews the statistics).

**Hard-won warning:** the tile-planning algorithm (which quadrants can be generated in
what order, optimal packing of 2x2 generation windows against the seam constraint) was
**the hardest thing to get coding agents to build correctly**. "Some algorithms are
irreducibly complex." Budget serious human design time here; verify with visual test
artifacts (see micro-tools below).

---

## Stage 5: Scale-out infrastructure

**Evolution across the project:**

| Phase | Platform | Throughput/cost |
|---|---|---|
| Prototype | oxen.ai hosted inference | Slow, expensive — fine for testing |
| v1 scale | Lambda AI rented H100 VM, self-hosted inference server | <$3/hr, >200 generations/hr, overnight batches |
| v2 scale | **modal.com serverless GPU** | 50 parallel instances, tens of thousands of tiles in a few hours, cheap |

**Supporting machinery built for scale:**
- Retry logic and parallel model queues.
- Plan-driven batches: human spends a few minutes creating a generation plan, then the
  system runs unattended (overnight in v1, hours in v2).
- Model swappability + custom prompting/negative prompting per run.

**Takeaway:** serverless GPU (Modal or equivalent) from the start. It made v2 essentially
one-shot the entire map, versus weeks of overnight runs for v1.

---

## Stage 6: QA & correction

**What they did / learned:**
- **Automated AI review does not work (as of the write-up)**: even frontier multimodal
  models could not reliably detect seams or bad tree textures, and even when they could,
  not at viable scale/speed. Plan for **human review** as a first-class pipeline stage.
- Micro-tools built to make manual QA tractable:
  - **Bounds app**: map overlay showing generated/in-progress tiles on a real city map;
    evolved into a boundary polygon editor defining the export edge of the map.
  - **Water classifier**: flags quadrants that partially/fully contain water (used for
    both training augmentation and automatic post-generation water color correction).
  - **Automatic color-picker-based water correction** inside the generation app.
  - **Export/import round-trip to a photo editor** (Affinity) for fully manual fixes.
  - **Consistency debug tool** for color normalization across the map.
- The pathological content types: **water** (flat color ≈ noise to a diffusion model) and
  **trees** (structure-vs-texture separation failure). Expect these; mitigations in
  Stage 3 reduce but don't eliminate manual fixing.

---

## Stage 7: Viewer

**What they did:**
- **OpenSeaDragon** deep-zoom viewer serving the map at all zoom levels (gigapixel-style
  image pyramid).
- Flagged as *one of the hardest parts for coding agents*: high-performance graphics,
  zoom/coordinate-space math, caching/performance, and touch interaction are poorly
  handled by agent browser-control feedback loops. The author leaned on prior personal
  expertise here.
- v2 added a **snow shader layer** with a debug tool for tuning — layers over the base
  map are cheap once the tile pyramid exists.

---

## Cross-cutting method: how the software was built

- Nearly zero hand-written code; everything via coding agents (Claude Code, Gemini CLI,
  Cursor). Human effort went into **specs, domain modeling, and verification**.
- Engineering principles that still apply (verbatim from the write-up):
  1. Make small, isolated changes and test them.
  2. Domain modeling and data storage are critical.
  3. Simple and boring tech is better.
  4. Iteration is better than up-front design.
- **Micro-tool pattern**: CLI tool → shared library → application. CLI tools are easy for
  agents to build/test/debug and enforce loose coupling; promote to a library when
  integrating.
- **Visual test artifacts**: unit tests for the tiling library emit an image per test
  showing the scenario and result, hosted on a static debug HTML page. Vastly better than
  reading thousands of lines of test code. Use this pattern for any spatial/geometric
  logic.
- Agents will **re-implement existing logic** if it isn't factored into a discoverable
  shared library — watch for duplication of core tiling/seam logic.
