"""Tests for grid generation and geo math."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from grid import generate_grid, haversine, offset_point


def test_offset_moves_east():
    lat, lon = 28.4084, 77.0417
    new_lat, new_lon = offset_point(lat, lon, 200, 0)
    # Latitude should barely change
    assert abs(new_lat - lat) < 1e-6
    # Longitude should increase (moved east)
    assert new_lon > lon


def test_offset_moves_north():
    lat, lon = 28.4084, 77.0417
    new_lat, new_lon = offset_point(lat, lon, 0, 200)
    # Longitude should barely change
    assert abs(new_lon - lon) < 1e-6
    # Latitude should increase (moved north)
    assert new_lat > lat


def test_haversine_zero_distance():
    d = haversine(28.4, 77.0, 28.4, 77.0)
    assert d == 0.0


def test_haversine_known_distance():
    # Two points ~200m apart (offset_point should give ~200m)
    lat1, lon1 = 28.4084, 77.0417
    lat2, lon2 = offset_point(lat1, lon1, 200, 0)
    d = haversine(lat1, lon1, lat2, lon2)
    assert 195 < d < 205, f"Expected ~200m, got {d}"


def test_generate_grid_count():
    points = generate_grid(28.4084, 77.0417, 3, 4, 200.0)
    assert len(points) == 12  # 3 * 4


def test_generate_grid_ids():
    points = generate_grid(28.4084, 77.0417, 2, 2, 200.0)
    ids = {p.id for p in points}
    assert ids == {"g_0_0", "g_1_0", "g_0_1", "g_1_1"}


def test_generate_grid_spacing():
    points = generate_grid(28.4084, 77.0417, 3, 3, 200.0)
    # Check distance between adjacent horizontal points
    p00 = next(p for p in points if p.id == "g_0_0")
    p10 = next(p for p in points if p.id == "g_1_0")
    d = haversine(p00.lat, p00.lon, p10.lat, p10.lon)
    assert 195 < d < 205, f"Horizontal spacing {d}m not ~200m"

    # Check distance between adjacent vertical points
    p01 = next(p for p in points if p.id == "g_0_1")
    d = haversine(p00.lat, p00.lon, p01.lat, p01.lon)
    assert 195 < d < 205, f"Vertical spacing {d}m not ~200m"


def test_generate_grid_origin():
    points = generate_grid(28.4084, 77.0417, 2, 2, 200.0)
    origin = next(p for p in points if p.id == "g_0_0")
    assert abs(origin.lat - 28.4084) < 1e-8
    assert abs(origin.lon - 77.0417) < 1e-8
