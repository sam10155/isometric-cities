"""Grid math tests against the Toronto config."""

import pytest

from isomap.config import load_city
from isomap import gridlib


@pytest.fixture(scope="module")
def toronto():
    return load_city("toronto")


def test_seed_point_round_trip(toronto):
    lon, lat = toronto.seed_lonlat
    x, y = gridlib.lonlat_to_xy(toronto, lon, lat)
    lon2, lat2 = gridlib.xy_to_lonlat(toronto, x, y)
    assert abs(lon - lon2) < 1e-9
    assert abs(lat - lat2) < 1e-9


def test_seed_lands_at_positive_indices(toronto):
    qx, qy = gridlib.lonlat_to_quadrant(toronto, *toronto.seed_lonlat)
    assert 0 < qx < 1000
    assert 0 < qy < 1000


def test_quadrant_bounds_contain_center(toronto):
    qx, qy = gridlib.lonlat_to_quadrant(toronto, *toronto.seed_lonlat)
    b = gridlib.quadrant_bounds_xy(toronto, qx, qy)
    cx, cy = b.center
    assert gridlib.xy_to_quadrant(toronto, cx, cy) == (qx, qy)
    m = toronto.grid.meters_per_quadrant
    assert abs((b.max_x - b.min_x) - m) < 1e-6
    assert abs((b.max_y - b.min_y) - m) < 1e-6


def test_adjacent_quadrants_share_edges(toronto):
    b = gridlib.quadrant_bounds_xy(toronto, 100, 100)
    east = gridlib.quadrant_bounds_xy(toronto, 101, 100)
    south = gridlib.quadrant_bounds_xy(toronto, 100, 101)
    assert abs(b.max_x - east.min_x) < 1e-9
    assert abs(b.min_y - south.max_y) < 1e-9  # qy increases southward


def test_pilot_bbox_reasonable_size(toronto):
    rng = gridlib.bbox_lonlat_to_quadrant_range(toronto, toronto.pilot_bbox_lonlat)
    min_qx, min_qy, max_qx, max_qy = rng
    w = max_qx - min_qx + 1
    h = max_qy - min_qy + 1
    # pilot is ~5.2km x ~4.2km at 128m/quadrant → roughly 40 x 33
    assert 25 <= w <= 60
    assert 20 <= h <= 50
    assert 500 <= w * h <= 3000
