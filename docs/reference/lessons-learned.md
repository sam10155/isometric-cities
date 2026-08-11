# Lessons Learned — from Isometric NYC

Condensed list of every transferable lesson from the original project, grouped by theme.
Treat these as design constraints for our multi-city system.

## Input data

1. **Single-source geometry + texture beats composited sources.** Whitebox CityGML +
   separate satellite imagery had enough inconsistency to trigger heavy hallucination.
   Google Maps Photorealistic 3D Tiles (geometry and texture in one coherent render)
   fixed this. → For a "point at any city" system, 3D Tiles is the default input;
   city-specific open data is a fallback/enhancement, not the primary path.
2. **Orthographic camera from the start.** Isometric look + grid-composable tiles.
3. **GIS/coordinate projections eat time.** Budget for it; write the projection handling
   once as a well-tested library.

## Style model

4. **Frontier model as teacher, fine-tuned small model as workhorse.** Frontier image
   models are ~50/50 on style consistency and too slow/expensive for tens of thousands of
   tiles. ~40 curated input/output pairs was enough to fine-tune Qwen/Image-Edit
   (~$12, ~4h on oxen.ai).
5. **Color-normalize training data before fine-tuning, and normalize anchor tiles after
   generation.** Color/style drift across the map is the #1 at-scale failure mode. When
   the infill model sees two contrasting styles it picks one, creating a visible seam
   "front." When normalizing generated tiles, exclude water pixels from the color
   statistics.
6. **Water is pathological.** A flat color is indistinguishable from pure noise to a
   diffusion/edit model → it hallucinates onto open water. Fixes: (a) overlay a 2x2
   checkerboard on water in training inputs so the model learns "water = fill with pure
   color"; (b) maintain a water mask per quadrant and auto-correct water color after
   generation.
7. **Trees are pathological** (structure vs. texture separation). No full fix found —
   mitigate with training data augmentation and accept manual correction.
8. **Balance the training set by terrain type.** Oversample water/terrain/parks or the
   model fails on them. Expect to train several variants; it's empirical.
9. **Fine-tuning is flimsy and counterintuitive.** Keep the training-data generator as a
   tool so retraining variants is cheap.

## Generation system

10. **Quadrant schema:** 512x512 atomic quadrants; one model call = 2x2 quadrants
    (1024x1024) with a mask. SQLite for all quadrant state. Simple, boring, worked.
11. **Infill/staggered generation is the seam solution.** Train the model on
    partially-masked inputs; always generate adjacent to existing content. Core rule:
    no generation may create a seam.
12. **The tile-planning algorithm is the hardest agent task in the project.** Seam-free
    packing/ordering logic is "irreducibly complex" — agents struggled badly with it via
    specs alone. Design it carefully as a human, factor it into a single shared,
    heavily-tested library, and verify with visual test artifacts.
13. **Agents re-implement logic they can't see.** The e2e scripts silently duplicated all
    the tiling logic from the manual app. Factor core logic into shared libraries early.

## Scale & infrastructure

14. **Serverless GPU inference (modal.com) was transformational.** v1: overnight batches
    on a rented H100 (<$3/hr, ~200 gen/hr, weeks). v2: 50 parallel Modal instances,
    tens of thousands of tiles in hours. Start with Modal-style infrastructure.
15. **Plan-driven batch generation**: human writes a short plan (which region, which
    order), system executes unattended with retry logic and parallel queues.

## QA

16. **Automated AI QA doesn't work yet.** Frontier multimodal models can't reliably spot
    seams or bad trees, and can't be deployed at viable scale/speed even when they can.
    Human review is a first-class pipeline stage — invest in tools that make it fast:
    map overlay of generation status, flagging UI, one-click water correction, photo
    editor round-trip.
17. **The last 10% takes 90% of the time**, and it's mostly water, trees, and terrain.

## Working method

18. **Micro-tools at the speed of thought.** Any debug/visualization/correction tool is
    minutes away with an agent. Build them liberally; code quality doesn't matter for
    single-user throwaway tools.
19. **CLI tool → library → application** progression. CLI tools are easiest for agents to
    build and test, and enforce loose coupling.
20. **Visual test artifacts**: make spatial-logic tests emit an image showing scenario +
    result onto a static debug page. Far better than reading test code for verifying
    geometric behavior.
21. **Engineering principles survive**: small isolated tested changes; domain modeling
    and data storage are critical; simple boring tech; iterate rather than big up-front
    design.
22. **The image-model interface is weak**: no reliable pointing ("that tree"), no true
    local edits (diffusion regenerates everything), no few-shot, no annotation, weak
    masking. Don't design workflows that assume these abilities.
