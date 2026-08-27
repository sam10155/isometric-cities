"""One-time palette-quantization of existing pyramid tiles.

GitHub Pages caps the deploy artifact at 1 GB; quantized pixel-art PNGs are
~40% of the RGB originals with no visible difference. New tiles are already
saved quantized by isomap/pyramid.py — run this only to convert a pyramid
built before 2026-08-27.

  .venv/bin/python tools/optimize_pyramid.py
"""

import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent

total_before = total_after = n = skipped = 0
for f in sorted(REPO.glob("docs/*/map_files/*/*.png")):
    im = Image.open(f)
    if im.mode == "P":
        skipped += 1
        continue
    before = f.stat().st_size
    im.convert("RGB").quantize(
        colors=256, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG
    ).save(f, optimize=True)
    total_before += before
    total_after += f.stat().st_size
    n += 1
    if n % 2000 == 0:
        print(f"{n} tiles: {total_before/1e6:.0f} -> {total_after/1e6:.0f} MB",
              flush=True)
print(f"done: {n} converted ({skipped} already paletted), "
      f"{total_before/1e6:.0f} -> {total_after/1e6:.0f} MB")
