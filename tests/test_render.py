"""Renderer regression tests — run entirely from the tile cache (no API).

Skipped if the cache is empty (fresh clones). Uses the global ScreenFrame:
the core guarantee under test is cross-render registration — separately
rendered blocks must agree pixel-exactly on shared tiles.
"""

from pathlib import Path

import numpy as np
import pytest

from isomap.config import load_city
from isomap.render import ScreenFrame, crop_tile, render_screen_block

CACHE = Path(__file__).resolve().parent.parent / "cities" / "toronto" / "tile_cache"

pytestmark = pytest.mark.skipif(
    not any(CACHE.glob("*.glb")), reason="tile cache empty (no fetched meshes)"
)

CN_TOWER = (-79.3871, 43.6426)


@pytest.fixture(scope="module")
def frame():
    return ScreenFrame(load_city("toronto"))


@pytest.fixture(scope="module")
def glbs():
    return sorted(CACHE.glob("*.glb"))


def test_screen_roundtrip(frame):
    sx, sy = frame.lonlat_to_screen(*CN_TOWER)
    lon, lat = frame.screen_to_lonlat(sx, sy)
    assert abs(lon - CN_TOWER[0]) < 1e-8
    assert abs(lat - CN_TOWER[1]) < 1e-8


def test_render_has_content(frame, glbs):
    ti, tj = frame.tile_for_screen(*frame.lonlat_to_screen(*CN_TOWER))
    img = render_screen_block(frame, ti, tj, ti, tj, glbs)
    a = np.asarray(img)
    assert (a.sum(axis=2) > 30).mean() > 0.5
    assert a.std() > 20


def test_cross_render_registration(frame, glbs):
    """THE invariant: a tile cropped from two different renders is identical."""
    ti, tj = frame.tile_for_screen(*frame.lonlat_to_screen(*CN_TOWER))
    block_a = render_screen_block(frame, ti - 1, tj, ti, tj, glbs)
    block_b = render_screen_block(frame, ti, tj, ti + 1, tj, glbs)
    tile_from_a = np.asarray(crop_tile(frame, block_a, ti - 1, tj, ti, tj))
    tile_from_b = np.asarray(crop_tile(frame, block_b, ti, tj, ti, tj))
    assert np.array_equal(tile_from_a, tile_from_b)
