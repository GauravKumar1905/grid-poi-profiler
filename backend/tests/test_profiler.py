"""Tests for profiler logic."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from profiler import _gaussian_decay, _popularity_factor, compute_profile
import config


def test_decay_zero_distance():
    assert _gaussian_decay(0) == 1.0


def test_decay_at_sigma():
    val = _gaussian_decay(config.SIGMA_M)
    expected = math.exp(-0.5)
    assert abs(val - expected) < 1e-6


def test_decay_decreases():
    assert _gaussian_decay(100) > _gaussian_decay(500)


def test_popularity_factor_none():
    assert _popularity_factor(None) == 1.0


def test_popularity_factor_positive():
    assert _popularity_factor(100) > 1.0
    assert _popularity_factor(1000) > _popularity_factor(100)


def test_compute_profile_empty_pois():
    gp = {"id": "g_0_0", "lat": 28.4084, "lon": 77.0417}
    profile = compute_profile(gp, [])
    assert profile["grid_point_id"] == "g_0_0"
    assert profile["audience"]["confidence"] == 0.0
    assert profile["audience"]["footfall_proxy"] == 0.0
    assert all(v == 0.0 for v in profile["audience"]["age_profile"].values())


def test_compute_profile_with_nearby_school():
    from grid import offset_point
    gp = {"id": "g_0_0", "lat": 28.4084, "lon": 77.0417}
    school_lat, school_lon = offset_point(28.4084, 77.0417, 100, 0)
    pois = [{
        "place_id": "test_school_1",
        "name": "Test School",
        "lat": school_lat,
        "lon": school_lon,
        "types": ["school"],
        "rating": 4.0,
        "user_ratings_total": 50,
    }]
    profile = compute_profile(gp, pois)
    age = profile["audience"]["age_profile"]
    # School should boost 0-12 bucket
    assert age["0-12"] > 0
    assert profile["audience"]["confidence"] > 0
    assert "education" in profile["geographic_attributes"]


def test_compute_profile_distance_effect():
    """Closer POI should have more influence than far one."""
    from grid import offset_point
    gp = {"id": "g_0_0", "lat": 28.4084, "lon": 77.0417}

    near_lat, near_lon = offset_point(28.4084, 77.0417, 50, 0)
    far_lat, far_lon = offset_point(28.4084, 77.0417, 800, 0)

    pois_near = [{
        "place_id": "near", "name": "Near School",
        "lat": near_lat, "lon": near_lon,
        "types": ["school"], "rating": 4.0, "user_ratings_total": 50,
    }]
    pois_far = [{
        "place_id": "far", "name": "Far School",
        "lat": far_lat, "lon": far_lon,
        "types": ["school"], "rating": 4.0, "user_ratings_total": 50,
    }]

    profile_near = compute_profile(gp, pois_near)
    profile_far = compute_profile(gp, pois_far)

    assert profile_near["audience"]["confidence"] > profile_far["audience"]["confidence"]
