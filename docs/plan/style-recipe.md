# Style Recipe — Toronto pixel art (v1, APPROVED 2026-08-07)

## Status

The style gate is passed: Nano Banana Pro produces the target look from our HD
isometric renders. Reference output: `style_refs/q123_72_v1.png` (approved by
the user), from input `debug/renders/toronto_123_72_iso_hd.png`.

## Recipe

- **Model/surface**: Gemini web app image generation (Nano Banana Pro tier),
  interactive. API equivalent: `gemini-3-pro-image` (blocked until API credits
  exist — AI Studio Pro subscription covers interactive use only).
- **Input**: 512x512 isometric render, geometric error 4.0 meshes, azimuth 225°,
  elevation 30°, 0.25 m/px (config `cities/toronto/config.yaml`).
- **Output**: 1024x1024 (model upscales 2x — bonus resolution).
- **Prompt** (verbatim):

```
Transform this isometric 3D render of downtown Toronto into detailed isometric
PIXEL ART in the style of classic late-90s city-building games like SimCity 2000
and RollerCoaster Tycoon.

Requirements:
- Keep the exact same camera angle, layout, and building positions as the input
  image — every building, road, and rail line must appear in the same place
- Crisp pixel-art aesthetic: limited color palette, clean dithering, sharp
  1-pixel edges, no anti-aliasing blur
- Bright, slightly saturated daytime colors with the charming toy-like quality
  of SimCity 2000
- Roofs, windows, and facades rendered as clean pixel-art detail, not
  photographic texture
- No text, no UI elements, no watermarks, no borders
- Fill the entire frame edge to edge
```

## Measured properties of v1

- Edge-structure correlation input↔output: **0.54** (layout well preserved —
  the property that makes seamless tiling viable).
- Top-64 colors cover 44% of output pixels (moderately clean palette; the
  fine-tune stage will normalize this further).
- The model plausibly hallucinated content in the black unfetched-margin wedges
  — harmless here, but production inputs must have full margins fetched so
  invention isn't needed.

## Next steps for the style pipeline

1. ~~Consistency probe~~ **DONE 2026-08-07**: user ran the same input + prompt
   repeatedly in the Gemini web app and got acceptable/desired results each
   time — better than the NYC ~50% baseline. Recipe considered stable.
2. Coverage probe: 3-5 different quadrant types (residential, park/ravine,
   water/lakefront, highway) through the same prompt.
3. Accumulate approved outputs in `style_refs/` (numbered) — these seed the
   fine-tuning training set (target ~40-60 pairs, color-normalized, water
   checkerboard augmentation per docs/reference/lessons-learned.md).
