"""Tests for the hexagonal grid lattice."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from grid import generate_grid_from_bbox, generate_hex_grid, haversine, offset_point


def _by_id(points):
    return {p.id: p for p in points}


def test_hex_grid_count():
    points = generate_hex_grid(28.4084, 77.0417, 3, 4, 200.0)
    assert len(points) == 12


def test_hex_neighbours_are_equidistant():
    pts = _by_id(generate_hex_grid(28.4084, 77.0417, 3, 3, 200.0))
    centre = pts["g_1_1"]  # odd row, shifted east
    # Pointy-top, odd-row-offset neighbours of (1, 1)
    neighbour_ids = ["g_0_1", "g_2_1", "g_1_0", "g_2_0", "g_1_2", "g_2_2"]
    for nid in neighbour_ids:
        n = pts[nid]
        d = haversine(centre.lat, centre.lon, n.lat, n.lon)
        assert 198 < d < 202, f"{nid} is {d:.1f}m from centre, expected ~200m"


def test_hex_row_spacing():
    pts = _by_id(generate_hex_grid(28.4084, 77.0417, 2, 2, 200.0))
    dy = haversine(pts["g_0_0"].lat, pts["g_0_0"].lon, pts["g_0_1"].lat, pts["g_0_0"].lon)
    assert abs(dy - 200 * math.sqrt(3) / 2) < 1.0


def test_every_point_within_hex_circumradius():
    """Any location inside the lattice is within spacing/sqrt(3) of a centre (full coverage)."""
    points = generate_hex_grid(28.4084, 77.0417, 6, 6, 200.0)
    circumradius = 200.0 / math.sqrt(3)
    for dx in range(150, 900, 37):
        for dy in range(150, 800, 41):
            lat, lon = offset_point(28.4084, 77.0417, dx, dy)
            nearest = min(haversine(lat, lon, p.lat, p.lon) for p in points)
            assert nearest <= circumradius + 0.5


def test_bbox_grid_is_hex():
    points = generate_grid_from_bbox(28.40, 28.41, 77.00, 77.01, 200.0)
    pts = _by_id(points)
    # Odd rows are shifted east relative to even rows
    assert pts["g_0_1"].lon > pts["g_0_0"].lon
