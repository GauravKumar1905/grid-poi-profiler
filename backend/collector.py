"""POI collector using Google Places API (legacy Nearby Search).

Optimized tiling strategy:
- Computes minimal tile centers covering the full bounding box + influence buffer.
- Each tile uses radius = max_influence_m (1000m).
- Supports both type-based and keyword-based searches.
- For full Gurgaon (~32km x 20km): ~486 tiles x (14 types + 3 keywords) = ~8,262 API calls.
- Results deduped by place_id, saved to DB incrementally every batch.
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone

import httpx

import config
import db
from grid import offset_point, haversine

logger = logging.getLogger(__name__)

NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


def compute_tile_centers() -> list[tuple[float, float]]:
    """Compute minimal tile centers covering bbox + max_influence buffer."""
    tile_radius = config.MAX_INFLUENCE_M
    spacing = tile_radius * math.sqrt(2) * 0.9

    width_m = haversine(config.BBOX_SOUTH, config.BBOX_WEST, config.BBOX_SOUTH, config.BBOX_EAST)
    height_m = haversine(config.BBOX_SOUTH, config.BBOX_WEST, config.BBOX_NORTH, config.BBOX_WEST)
    buffer = tile_radius

    x_min, x_max = -buffer, width_m + buffer
    y_min, y_max = -buffer, height_m + buffer

    centers = []
    y = y_min
    while y <= y_max:
        x = x_min
        while x <= x_max:
            lat, lon = offset_point(config.BBOX_SOUTH, config.BBOX_WEST, x, y)
            centers.append((lat, lon))
            x += spacing
        y += spacing
    return centers


# Map keyword searches to custom type names for profiling
KEYWORD_TO_TYPE: dict[str, str] = {
    "corporate office": "corporate_office",
    "coworking space": "coworking_space",
    "IT park": "it_park",
    "residential apartment": "residential",
    "housing society": "residential",
    "hotel": "hotel",
}


def _parse_place(result: dict, inject_type: str | None = None) -> dict:
    location = result.get("geometry", {}).get("location", {})
    types = result.get("types", [])
    if inject_type and inject_type not in types:
        types = [inject_type] + types
    return {
        "place_id": result.get("place_id", ""),
        "name": result.get("name", ""),
        "lat": location.get("lat", 0.0),
        "lon": location.get("lng", 0.0),
        "types": json.dumps(types),
        "rating": result.get("rating"),
        "user_ratings_total": result.get("user_ratings_total"),
        "raw_json": json.dumps(result),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


async def _fetch_one_tile(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    radius: float,
    poi_type: str | None,
    semaphore: asyncio.Semaphore,
    keyword: str | None = None,
) -> list[dict]:
    params = {
        "key": config.GOOGLE_MAPS_API_KEY,
        "location": f"{lat},{lon}",
        "radius": radius,
    }
    if poi_type:
        params["type"] = poi_type
    if keyword:
        params["keyword"] = keyword
    inject_type = KEYWORD_TO_TYPE.get(keyword) if keyword else None
    retries = 0
    while retries <= config.COLLECTOR_RETRY_MAX:
        async with semaphore:
            try:
                resp = await client.get(NEARBY_SEARCH_URL, params=params, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "")
                    if status == "OK":
                        return [_parse_place(p, inject_type) for p in data.get("results", [])]
                    elif status == "ZERO_RESULTS":
                        return []
                    elif status == "OVER_QUERY_LIMIT":
                        wait = 2 ** retries
                        logger.warning("Rate limited, waiting %ds", wait)
                        await asyncio.sleep(wait)
                        retries += 1
                    elif status == "REQUEST_DENIED":
                        logger.error("REQUEST_DENIED: %s", data.get("error_message", ""))
                        return []
                    else:
                        logger.error("API status=%s: %s", status, data.get("error_message", ""))
                        return []
                else:
                    logger.error("HTTP %d", resp.status_code)
                    return []
            except httpx.TimeoutException:
                retries += 1
                await asyncio.sleep(1)
    return []


async def collect_pois(grid_points: list[dict]) -> int:
    """Collect POIs using optimized tiling across the full bounding box.

    grid_points argument kept for API compat but tiling is based on config bbox.
    Supports both type-based and keyword-based searches.
    Saves to DB incrementally every 50 tiles.
    """
    tile_centers = compute_tile_centers()
    tile_radius = config.MAX_INFLUENCE_M
    total_tiles = len(tile_centers)
    keywords = getattr(config, "POI_KEYWORDS", [])
    searches_per_tile = len(config.POI_TYPES) + len(keywords)
    total_calls = total_tiles * searches_per_tile

    logger.info(
        "Starting collection: %d tiles x (%d types + %d keywords) = %d API calls",
        total_tiles, len(config.POI_TYPES), len(keywords), total_calls,
    )

    semaphore = asyncio.Semaphore(config.COLLECTOR_CONCURRENCY)
    all_pois: dict[str, dict] = {}
    calls_done = 0
    start_time = time.time()

    BATCH_SIZE = 50  # tiles per batch
    async with httpx.AsyncClient() as client:
        for batch_start in range(0, total_tiles, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_tiles)
            batch_centers = tile_centers[batch_start:batch_end]

            tasks = []
            for lat, lon in batch_centers:
                # Type-based searches
                for poi_type in config.POI_TYPES:
                    tasks.append(_fetch_one_tile(client, lat, lon, tile_radius, poi_type, semaphore))
                # Keyword-based searches (no type filter)
                for kw in keywords:
                    tasks.append(_fetch_one_tile(client, lat, lon, tile_radius, None, semaphore, keyword=kw))

            results = await asyncio.gather(*tasks)
            for batch in results:
                for poi in batch:
                    if poi["place_id"]:
                        all_pois[poi["place_id"]] = poi

            calls_done += len(tasks)
            elapsed = time.time() - start_time
            rate = calls_done / elapsed if elapsed > 0 else 0
            logger.info(
                "Progress: %d/%d tiles (%d/%d calls), %d unique POIs, %.1f calls/sec",
                batch_end, total_tiles, calls_done, total_calls,
                len(all_pois), rate,
            )

            # Save incrementally so data is not lost on crash
            if all_pois:
                db.upsert_pois(list(all_pois.values()))

    elapsed = time.time() - start_time
    logger.info(
        "Collection complete: %d unique POIs from %d API calls in %.0fs",
        len(all_pois), total_calls, elapsed,
    )
    return len(all_pois)


# --- Mock data ---

def load_mock_pois() -> int:
    """Load realistic mock POI data for demo purposes."""
    mock_data = [
        ("hospital", "Medanta Hospital", 500, 300, 4.5, 12000),
        ("hospital", "Artemis Hospital", -200, 600, 4.3, 8500),
        ("school", "DPS Gurgaon", 150, 100, 4.2, 3200),
        ("school", "Shiv Nadar School", 400, -100, 4.4, 1800),
        ("school", "GD Goenka Public School", -100, 350, 4.1, 2100),
        ("university", "Amity University", 700, 700, 3.9, 5600),
        ("university", "MDU Campus Center", -300, 800, 3.7, 2300),
        ("shopping_mall", "Ambience Mall", 300, 500, 4.3, 45000),
        ("shopping_mall", "MGF Metropolitan", -150, 200, 4.0, 18000),
        ("store", "Big Bazaar", 100, 400, 3.8, 6200),
        ("store", "Reliance Fresh", 250, 50, 3.9, 1500),
        ("store", "DMart", -200, 150, 4.0, 8900),
        ("restaurant", "Haldiram's", 50, 250, 4.1, 9500),
        ("restaurant", "Barbeque Nation", 350, 350, 4.2, 7200),
        ("restaurant", "Subway", 500, 100, 3.8, 3100),
        ("restaurant", "Domino's Pizza", -50, 450, 3.9, 4200),
        ("restaurant", "McDonald's", 200, 600, 4.0, 11000),
        ("transit_station", "HUDA City Centre Metro", 600, 200, 4.1, 15000),
        ("transit_station", "IFFCO Chowk Metro", -400, 500, 4.0, 12000),
        ("transit_station", "Sikanderpur Metro", 100, 700, 4.2, 9000),
        ("hospital", "Fortis Hospital", 800, 400, 4.4, 10000),
        ("school", "The Heritage School", 600, -50, 4.3, 2800),
        ("restaurant", "Sagar Ratna", -300, 100, 4.0, 5600),
        ("store", "Croma Electronics", 450, 550, 3.7, 3400),
        ("shopping_mall", "DLF Cyber Hub", 700, 150, 4.5, 32000),
    ]

    pois = []
    for poi_type, name, dx, dy, rating, reviews in mock_data:
        lat, lon = offset_point(config.ORIGIN_LAT, config.ORIGIN_LON, dx, dy)
        pois.append({
            "place_id": f"mock_{name.lower().replace(' ', '_')}",
            "name": name,
            "lat": lat,
            "lon": lon,
            "types": json.dumps([poi_type]),
            "rating": rating,
            "user_ratings_total": reviews,
            "raw_json": json.dumps({"mock": True}),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

    db.upsert_pois(pois)
    logger.info("Loaded %d mock POIs", len(pois))
    return len(pois)
