"""Tests for FastAPI endpoints."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

# Override DB path to use a temp database
import db as db_module
db_module.DB_PATH = Path(__file__).parent / "test_grid.db"

from main import app

client = TestClient(app)


def setup_function():
    """Reset test database before each test."""
    if db_module.DB_PATH.exists():
        db_module.DB_PATH.unlink()
    db_module.init_db()


def teardown_function():
    if db_module.DB_PATH.exists():
        db_module.DB_PATH.unlink()


def test_dashboard():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Grid POI Profiler" in resp.text


def test_config():
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "origin" in data
    assert data["grid_spacing_m"] == 200


def test_grid_empty():
    resp = client.get("/grid")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_grid_generate():
    resp = client.post("/grid/generate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0

    resp2 = client.get("/grid")
    assert resp2.json()["count"] == data["count"]


def test_profile_requires_grid():
    resp = client.get("/profile?lat=28.41&lon=77.04")
    assert resp.status_code == 400


def test_collect_requires_grid():
    resp = client.post("/collect")
    assert resp.status_code == 400


def test_pois_empty():
    resp = client.get("/pois")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
