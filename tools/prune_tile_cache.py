"""Prune raw 3D-tile mesh caches (user-approved 2026-08-27).

Tile fetches are FREE (sessions are the billable unit — verified); the cache
only saves re-download time on future prepares/repairs. Run when disk is
tight. Renders, map tiles and pyramids are never touched.

  .venv/bin/python tools/prune_tile_cache.py
"""

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
freed = 0
for cache in sorted(REPO.glob("cities/*/tile_cache")):
    size = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file())
    for child in cache.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    freed += size
    print(f"{cache.parent.name}: {size/1e6:.0f} MB pruned")
print(f"total freed {freed/1e9:.2f} GB")
