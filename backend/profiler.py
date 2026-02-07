"""Profiler: compute distance-weighted digital profiles for grid points.

Optimized for large grids (16k+ points):
- Coarse lat/lon bounding-box pre-filter before haversine (10x faster).
- Batch DB writes (every 500 profiles).
- Progress logging.
"""

import math
import time
from collections import defaultdict

import config
import db
from grid import haversine

import logging

logger = logging.getLogger(__name__)

# Pre-compute the lat/lon degree span for max_influence_m at Gurgaon's latitude.
# This avoids calling haversine on POIs that are obviously too far away.
_DEG_PER_M_LAT = 1.0 / 111_320.0  # ~constant
_DEG_PER_M_LON = 1.0 / (111_320.0 * math.cos(math.radians(28.44)))  # at Gurgaon lat
_LAT_MARGIN = config.MAX_INFLUENCE_M * _DEG_PER_M_LAT * 1.1  # 10% safety margin
_LON_MARGIN = config.MAX_INFLUENCE_M * _DEG_PER_M_LON * 1.1


def _gaussian_decay(d: float, sigma: float = config.SIGMA_M) -> float:
    return math.exp(-(d * d) / (2 * sigma * sigma))


def _popularity_factor(user_ratings_total: int | None) -> float:
    if not user_ratings_total:
        return 1.0
    return 1.0 + math.log(1 + user_ratings_total)


def _primary_type(types: list[str]) -> str | None:
    """Return the first type that matches our configured POI types."""
    for t in types:
        if t in config.TYPE_IMPORTANCE:
            return t
    return None


def compute_profile(grid_point: dict, nearby_pois: list[tuple[dict, float]]) -> dict:
    """Compute a digital profile for a single grid point.

    nearby_pois: pre-filtered list of (poi, distance_m) tuples.
    """
    gp_lat, gp_lon = grid_point["lat"], grid_point["lon"]

    # Sort by distance
    nearby_pois.sort(key=lambda x: x[1])

    # --- POI summary ---
    counts: dict[str, int] = defaultdict(int)
    nearest_list = []
    for poi, d in nearby_pois[:10]:
        ptype = _primary_type(poi["types"]) or (poi["types"][0] if poi["types"] else "unknown")
        nearest_list.append({
            "place_id": poi["place_id"],
            "name": poi["name"],
            "type": ptype,
            "distance_m": round(d, 1),
        })
    for poi, _ in nearby_pois:
        ptype = _primary_type(poi["types"])
        if ptype:
            counts[ptype] += 1

    poi_summary = {"nearest": nearest_list, "counts": dict(counts)}

    # --- Accumulate weighted scores ---
    age_scores: dict[str, float] = defaultdict(float)
    interest_scores: dict[str, float] = defaultdict(float)
    footfall_total = 0.0
    total_influence = 0.0
    landuse_scores: dict[str, float] = defaultdict(float)

    for poi, d in nearby_pois:
        ptype = _primary_type(poi["types"])
        if not ptype:
            continue
        decay = _gaussian_decay(d)
        importance = config.TYPE_IMPORTANCE.get(ptype, 1.0)
        pop = _popularity_factor(poi.get("user_ratings_total"))
        base_weight = importance * decay * pop

        total_influence += base_weight
        footfall_total += pop * decay

        for bucket, w in config.TYPE_TO_AGE_WEIGHTS.get(ptype, {}).items():
            age_scores[bucket] += base_weight * w

        for cat, w in config.TYPE_TO_INTEREST_WEIGHTS.get(ptype, {}).items():
            interest_scores[cat] += base_weight * w

        lu = config.TYPE_TO_LANDUSE.get(ptype, "other")
        landuse_scores[lu] += base_weight

    # --- Normalize ---
    def normalize(scores: dict[str, float]) -> dict[str, float]:
        total = sum(scores.values())
        if total == 0:
            return {k: 0.0 for k in scores}
        return {k: round(v / total, 2) for k, v in scores.items()}

    age_profile = {b: 0.0 for b in config.AGE_BUCKETS}
    age_profile.update(normalize(age_scores))

    interests = {c: 0.0 for c in config.INTEREST_CATEGORIES}
    interests.update(normalize(interest_scores))

    footfall_proxy = round(min(1.0, footfall_total / 20.0), 2) if footfall_total > 0 else 0.0
    confidence = round(min(1.0, total_influence / 15.0), 2) if total_influence > 0 else 0.0

    geo_attrs = sorted(landuse_scores, key=landuse_scores.get, reverse=True)[:3] if landuse_scores else []

    audience = {
        "age_profile": age_profile,
        "interests": interests,
        "footfall_proxy": footfall_proxy,
        "confidence": confidence,
    }

    return {
        "grid_point_id": grid_point["id"],
        "lat": gp_lat,
        "lon": gp_lon,
        "poi_summary": poi_summary,
        "geographic_attributes": geo_attrs,
        "audience": audience,
        "model_metadata": {
            "sigma_m": config.SIGMA_M,
            "max_influence_m": config.MAX_INFLUENCE_M,
        },
    }


def compute_all_profiles() -> int:
    """Compute and store profiles for all grid points.

    Uses coarse bounding-box pre-filter + batched DB writes for scale.
    """
    grid_points = db.get_all_grid_points()
    all_pois = db.get_all_pois()

    if not grid_points:
        logger.warning("No grid points found.")
        return 0

    logger.info("Computing profiles for %d grid points with %d POIs...", len(grid_points), len(all_pois))
    start_time = time.time()

    # Pre-extract POI lat/lons for fast bounding-box filter
    poi_coords = [(p, p["lat"], p["lon"]) for p in all_pois]

    count = 0
    batch: list[tuple[str, dict, dict, dict]] = []
    BATCH_SIZE = 500

    for idx, gp in enumerate(grid_points):
        gp_lat, gp_lon = gp["lat"], gp["lon"]

        # Coarse bounding-box filter (avoids haversine for distant POIs)
        candidates = []
        for poi, plat, plon in poi_coords:
            if abs(plat - gp_lat) <= _LAT_MARGIN and abs(plon - gp_lon) <= _LON_MARGIN:
                d = haversine(gp_lat, gp_lon, plat, plon)
                if d <= config.MAX_INFLUENCE_M:
                    candidates.append((poi, d))

        profile = compute_profile(gp, candidates)
        batch.append((
            gp["id"],
            profile["geographic_attributes"],
            profile["audience"],
            profile["poi_summary"],
        ))
        count += 1

        # Batch write
        if len(batch) >= BATCH_SIZE:
            _flush_batch(batch)
            elapsed = time.time() - start_time
            logger.info(
                "Progress: %d/%d profiles (%.0f/sec)",
                count, len(grid_points), count / elapsed,
            )
            batch = []

    # Flush remaining
    if batch:
        _flush_batch(batch)

    elapsed = time.time() - start_time
    logger.info("Computed %d profiles in %.1fs (%.0f/sec)", count, elapsed, count / elapsed if elapsed > 0 else 0)
    return count


def _flush_batch(batch: list[tuple[str, dict, dict, dict]]) -> None:
    """Write a batch of profiles to the database."""
    for gp_id, geo_attrs, audience, poi_summary in batch:
        db.upsert_profile(gp_id, geo_attrs=geo_attrs, audience=audience, poi_summary=poi_summary)
