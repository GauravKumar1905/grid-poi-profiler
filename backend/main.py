"""FastAPI application for Grid-based POI Profiling."""

import gzip
import hashlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Query, HTTPException, Header, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import config
import db
from grid import generate_grid_from_bbox, haversine
from collector import collect_pois, load_mock_pois
from profiler import compute_all_profiles, _primary_type

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _init_db_in_background() -> None:
    try:
        db.init_db()
        logger.info("Database initialized")
    except Exception:
        logger.exception("Database initialization failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # With Turso, init_db() first syncs the local replica, which can take many
    # minutes on a fresh instance. Run it in the background so the server binds
    # its port immediately (Render fails a deploy that doesn't bind in time).
    threading.Thread(target=_init_db_in_background, daemon=True).start()
    yield


app = FastAPI(title="Grid POI Profiler", version="1.0.0", lifespan=lifespan)

# CORS — allow frontend origin(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Read cache ----------
# The data only changes through the write endpoints below, so large read payloads
# are built, serialised and gzipped once, then served from memory with an ETag.
# Every write endpoint calls _invalidate_cache().

_payloads: dict[str, tuple[bytes, bytes, str]] = {}  # key -> (json, gzipped json, etag)
_objects: dict[str, object] = {}                     # key -> parsed rows reused across endpoints


def _invalidate_cache() -> None:
    _payloads.clear()
    _objects.clear()


def _memo(key: str, build: Callable[[], object]):
    if key not in _objects:
        _objects[key] = build()
    return _objects[key]


def _grid_points() -> list[dict]:
    return _memo("grid_points", db.get_all_grid_points)


def _cached_json(request: Request, key: str, build: Callable[[], dict]) -> Response:
    if key not in _payloads:
        raw = json.dumps(build(), separators=(",", ":")).encode()
        _payloads[key] = (raw, gzip.compress(raw, compresslevel=6), f'"{hashlib.md5(raw).hexdigest()}"')
    raw, gz, etag = _payloads[key]
    headers = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(raw, media_type="application/json", headers=headers)


# ---------- Admin auth for write endpoints ----------

async def verify_admin(x_api_key: str = Header(default="")):
    """Protect write endpoints with an API key. No key configured = allow (local dev)."""
    admin_key = config.ADMIN_API_KEY
    if not admin_key:
        return
    if x_api_key != admin_key:
        raise HTTPException(403, "Invalid or missing API key")


# ---------- Health check ----------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- Grid ----------

@app.get("/grid")
def get_grid(request: Request):
    return _cached_json(request, "grid", lambda: {"count": len(_grid_points()), "grid_points": _grid_points()})


@app.post("/grid/generate", dependencies=[Depends(verify_admin)])
def generate_grid_endpoint(force: bool = Query(False, description="Delete the grid and its profiles, then regenerate")):
    existing = db.get_all_grid_points()
    if existing and not force:
        return {"message": f"Grid already exists with {len(existing)} points. Use ?force=true to regenerate.", "count": len(existing), "cached": True}
    if existing:
        db.clear_grid()
    points = generate_grid_from_bbox(
        config.BBOX_SOUTH, config.BBOX_NORTH,
        config.BBOX_WEST, config.BBOX_EAST,
        config.GRID_SPACING_M,
    )
    db.upsert_grid_points([vars(p) for p in points])
    _invalidate_cache()
    return {"message": f"Generated {len(points)} grid points", "count": len(points)}


# ---------- POIs ----------

@app.get("/pois")
def get_pois(request: Request):
    def build():
        pois = db.get_all_pois()
        return {"count": len(pois), "pois": pois}
    return _cached_json(request, "pois", build)


@app.get("/pois/compact")
def get_pois_compact(request: Request):
    """Columnar POI data for the map: one array per field, types as indexes into `types`."""
    def build():
        pois = db.get_all_pois()
        types: list[str] = []
        type_index: dict[str, int] = {}
        out = {"name": [], "lat": [], "lon": [], "type": [], "rating": [], "reviews": []}
        for p in pois:
            t = _primary_type(p["types"]) or "other"
            if t not in type_index:
                type_index[t] = len(types)
                types.append(t)
            out["name"].append(p["name"])
            out["lat"].append(round(p["lat"], 6))
            out["lon"].append(round(p["lon"], 6))
            out["type"].append(type_index[t])
            out["rating"].append(p["rating"])
            out["reviews"].append(p["user_ratings_total"])
        return {"count": len(pois), "types": types, **out}
    return _cached_json(request, "pois_compact", build)


@app.post("/collect", dependencies=[Depends(verify_admin)])
async def collect_pois_endpoint(force: bool = Query(False, description="Force re-collection even if POIs exist")):
    grid_points = db.get_all_grid_points()
    if not grid_points:
        raise HTTPException(400, "No grid points. Generate grid first via POST /grid/generate")
    existing = db.get_all_pois()
    if existing and not force:
        return {"message": f"Already have {len(existing)} POIs stored. Use ?force=true to re-collect.", "count": len(existing), "cached": True}
    count = await collect_pois(grid_points)
    _invalidate_cache()
    return {"message": f"Collected {count} unique POIs", "count": count, "cached": False}


@app.post("/collect/mock", dependencies=[Depends(verify_admin)])
def collect_mock_pois_endpoint():
    count = load_mock_pois()
    _invalidate_cache()
    return {"message": f"Loaded {count} mock POIs", "count": count}


# ---------- Profiles ----------

@app.get("/profiles")
def get_profiles(request: Request):
    def build():
        profiles = db.get_all_profiles()
        return {"count": len(profiles), "profiles": profiles}
    return _cached_json(request, "profiles", build)


@app.get("/cells")
def get_cells(request: Request):
    """Columnar per-cell data: just what the map needs to draw, colour and filter hexagons.

    `geo` is an index into `geo_labels` (-1 = no profile); `age` holds
    len(age_buckets) values per cell, flattened in cell order.
    """
    def build():
        profiles = {p["grid_point_id"]: p for p in db.get_all_profiles()}
        geo_labels: list[str] = []
        geo_index: dict[str, int] = {}
        out = {"id": [], "lat": [], "lon": [], "geo": [], "age": [], "confidence": [], "footfall": []}
        for gp in _grid_points():
            p = profiles.get(gp["id"])
            attrs = p["geo_attrs"] if p else []
            audience = p["audience"] if p else {}
            geo = -1
            if attrs:
                if attrs[0] not in geo_index:
                    geo_index[attrs[0]] = len(geo_labels)
                    geo_labels.append(attrs[0])
                geo = geo_index[attrs[0]]
            age = audience.get("age_profile", {})
            out["id"].append(gp["id"])
            out["lat"].append(round(gp["lat"], 6))
            out["lon"].append(round(gp["lon"], 6))
            out["geo"].append(geo)
            out["age"].extend(age.get(b, 0.0) for b in config.AGE_BUCKETS)
            out["confidence"].append(audience.get("confidence", 0.0))
            out["footfall"].append(audience.get("footfall_proxy", 0.0))
        return {
            "count": len(out["id"]),
            "profiles": len(profiles),
            "geo_labels": geo_labels,
            "age_buckets": config.AGE_BUCKETS,
            **out,
        }
    return _cached_json(request, "cells", build)


def _profile_response(gp: dict) -> dict:
    profile = db.get_profile(gp["id"])
    if not profile:
        raise HTTPException(404, f"No profile computed for grid point {gp['id']}. Run POST /compute-profiles first.")
    return {
        "grid_point_id": gp["id"],
        "lat": gp["lat"],
        "lon": gp["lon"],
        "poi_summary": profile["poi_summary"],
        "geographic_attributes": profile["geo_attrs"],
        "audience": profile["audience"],
        "model_metadata": {"sigma_m": config.SIGMA_M, "max_influence_m": config.MAX_INFLUENCE_M},
    }


@app.get("/profile")
def get_nearest_profile(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Return the profile for the nearest grid point to the given coordinates."""
    grid_points = _grid_points()
    if not grid_points:
        raise HTTPException(400, "No grid points.")
    nearest = min(grid_points, key=lambda gp: haversine(lat, lon, gp["lat"], gp["lon"]))
    return _profile_response(nearest)


@app.get("/profile/{grid_point_id}")
def get_profile_by_id(grid_point_id: str):
    """Return the full profile for one cell (loaded on demand when a hexagon is clicked)."""
    gp = _memo("grid_by_id", lambda: {g["id"]: g for g in _grid_points()}).get(grid_point_id)
    if not gp:
        raise HTTPException(404, f"Unknown grid point {grid_point_id}")
    return _profile_response(gp)


@app.post("/compute-profiles", dependencies=[Depends(verify_admin)])
def compute_profiles_endpoint():
    count = compute_all_profiles()
    _invalidate_cache()
    return {"message": f"Computed {count} profiles", "count": count}


# ---------- Config (read-only) ----------

@app.get("/config")
async def get_config():
    return {
        "bbox": {
            "south": config.BBOX_SOUTH, "north": config.BBOX_NORTH,
            "west": config.BBOX_WEST, "east": config.BBOX_EAST,
        },
        "grid_spacing_m": config.GRID_SPACING_M,
        "grid_layout": "hex",
        "sigma_m": config.SIGMA_M,
        "max_influence_m": config.MAX_INFLUENCE_M,
        "search_radius_m": config.SEARCH_RADIUS_M,
        "poi_types": config.POI_TYPES,
    }
