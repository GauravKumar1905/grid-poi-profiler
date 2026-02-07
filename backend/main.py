"""FastAPI application for Grid-based POI Profiling."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware

import config
import db
from grid import generate_grid_from_bbox, haversine
from collector import collect_pois, load_mock_pois
from profiler import compute_all_profiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Database initialized")
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
async def get_grid():
    points = db.get_all_grid_points()
    return {"count": len(points), "grid_points": points}


@app.post("/grid/generate", dependencies=[Depends(verify_admin)])
async def generate_grid_endpoint():
    existing = db.get_all_grid_points()
    if existing:
        return {"message": f"Grid already exists with {len(existing)} points.", "count": len(existing), "cached": True}
    points = generate_grid_from_bbox(
        config.BBOX_SOUTH, config.BBOX_NORTH,
        config.BBOX_WEST, config.BBOX_EAST,
        config.GRID_SPACING_M,
    )
    db.upsert_grid_points([vars(p) for p in points])
    return {"message": f"Generated {len(points)} grid points", "count": len(points)}


# ---------- POIs ----------

@app.get("/pois")
async def get_pois():
    pois = db.get_all_pois()
    return {"count": len(pois), "pois": pois}


@app.post("/collect", dependencies=[Depends(verify_admin)])
async def collect_pois_endpoint(force: bool = Query(False, description="Force re-collection even if POIs exist")):
    grid_points = db.get_all_grid_points()
    if not grid_points:
        raise HTTPException(400, "No grid points. Generate grid first via POST /grid/generate")
    existing = db.get_all_pois()
    if existing and not force:
        return {"message": f"Already have {len(existing)} POIs stored. Use ?force=true to re-collect.", "count": len(existing), "cached": True}
    count = await collect_pois(grid_points)
    return {"message": f"Collected {count} unique POIs", "count": count, "cached": False}


@app.post("/collect/mock", dependencies=[Depends(verify_admin)])
async def collect_mock_pois_endpoint():
    count = load_mock_pois()
    return {"message": f"Loaded {count} mock POIs", "count": count}


# ---------- Profiles ----------

@app.get("/profiles")
async def get_profiles():
    profiles = db.get_all_profiles()
    return {"count": len(profiles), "profiles": profiles}


@app.get("/profile")
async def get_nearest_profile(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Return the profile for the nearest grid point to the given coordinates."""
    grid_points = db.get_all_grid_points()
    if not grid_points:
        raise HTTPException(400, "No grid points.")

    nearest = min(grid_points, key=lambda gp: haversine(lat, lon, gp["lat"], gp["lon"]))
    profile = db.get_profile(nearest["id"])

    if not profile:
        raise HTTPException(404, f"No profile computed for grid point {nearest['id']}. Run POST /compute-profiles first.")

    return {
        "grid_point_id": nearest["id"],
        "lat": nearest["lat"],
        "lon": nearest["lon"],
        "poi_summary": profile["poi_summary"],
        "geographic_attributes": profile["geo_attrs"],
        "audience": profile["audience"],
        "model_metadata": {"sigma_m": config.SIGMA_M, "max_influence_m": config.MAX_INFLUENCE_M},
    }


@app.post("/compute-profiles", dependencies=[Depends(verify_admin)])
async def compute_profiles_endpoint():
    count = compute_all_profiles()
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
        "sigma_m": config.SIGMA_M,
        "max_influence_m": config.MAX_INFLUENCE_M,
        "search_radius_m": config.SEARCH_RADIUS_M,
        "poi_types": config.POI_TYPES,
    }
