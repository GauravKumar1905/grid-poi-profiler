import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# --- Turso Database ---
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

# --- Admin ---
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://localhost:3000").split(",")

# --- Grid (Full Gurgaon bounding box) ---
GRID_SPACING_M = 200

# Bounding box: SW corner is the origin, NE corner defines the extent
BBOX_SOUTH = 28.35
BBOX_NORTH = 28.53
BBOX_WEST = 76.82
BBOX_EAST = 77.15

# Legacy aliases (origin = SW corner)
ORIGIN_LAT = BBOX_SOUTH
ORIGIN_LON = BBOX_WEST

# --- Spatial ---
SIGMA_M = 200.0            # Gaussian decay σ
MAX_INFLUENCE_M = 1000.0   # max radius for POI influence
SEARCH_RADIUS_M = 400      # Places API search radius per grid point

# --- POI types to search ---
# Type-based searches (passed as `type=` param)
POI_TYPES = [
    "hospital",
    "school",
    "university",
    "shopping_mall",
    "store",
    "restaurant",
    "transit_station",
    "park",
    "gym",
    "movie_theater",
    "bar",
    "night_club",
    "place_of_worship",
    "lodging",
]

# Keyword-based searches (passed as `keyword=` param, no type filter)
# Used for POI categories that don't have a direct Google type
POI_KEYWORDS = [
    "corporate office",
    "coworking space",
    "IT park",
    "residential apartment",
    "housing society",
]

# --- Type → attribute weight mappings ---
# age buckets: 0-12, 13-17, 18-24, 25-34, 35-50, 50+
AGE_BUCKETS = ["0-12", "13-17", "18-24", "25-34", "35-50", "50+"]

TYPE_TO_AGE_WEIGHTS: dict[str, dict[str, float]] = {
    "school":          {"0-12": 0.70, "13-17": 0.30},
    "university":      {"18-24": 0.80, "25-34": 0.20},
    "shopping_mall":   {"25-34": 0.30, "35-50": 0.40, "18-24": 0.20, "13-17": 0.10},
    "store":           {"25-34": 0.40, "35-50": 0.30, "18-24": 0.20, "50+": 0.10},
    "restaurant":      {"25-34": 0.35, "18-24": 0.25, "35-50": 0.25, "13-17": 0.10, "50+": 0.05},
    "hospital":        {"35-50": 0.25, "50+": 0.30, "25-34": 0.20, "0-12": 0.10, "13-17": 0.05, "18-24": 0.10},
    "transit_station":  {"18-24": 0.30, "25-34": 0.40, "35-50": 0.20, "13-17": 0.10},
    "park":            {"0-12": 0.20, "25-34": 0.25, "35-50": 0.30, "50+": 0.15, "13-17": 0.10},
    "gym":             {"18-24": 0.35, "25-34": 0.40, "35-50": 0.20, "13-17": 0.05},
    "movie_theater":   {"13-17": 0.15, "18-24": 0.35, "25-34": 0.30, "35-50": 0.15, "0-12": 0.05},
    "bar":             {"18-24": 0.30, "25-34": 0.45, "35-50": 0.20, "50+": 0.05},
    "night_club":      {"18-24": 0.45, "25-34": 0.40, "35-50": 0.10, "13-17": 0.05},
    "place_of_worship": {"35-50": 0.30, "50+": 0.35, "25-34": 0.15, "0-12": 0.10, "13-17": 0.05, "18-24": 0.05},
    "lodging":         {"25-34": 0.35, "35-50": 0.35, "18-24": 0.15, "50+": 0.15},
    "corporate_office": {"25-34": 0.45, "35-50": 0.35, "18-24": 0.15, "50+": 0.05},
    "coworking_space":  {"18-24": 0.25, "25-34": 0.50, "35-50": 0.20, "13-17": 0.05},
    "it_park":         {"25-34": 0.50, "35-50": 0.30, "18-24": 0.15, "50+": 0.05},
    "residential":     {"0-12": 0.15, "13-17": 0.10, "25-34": 0.30, "35-50": 0.30, "50+": 0.15},
}

INTEREST_CATEGORIES = ["education", "shopping", "food", "health", "transit", "entertainment", "business", "lifestyle"]

TYPE_TO_INTEREST_WEIGHTS: dict[str, dict[str, float]] = {
    "school":          {"education": 1.0},
    "university":      {"education": 0.9, "food": 0.1},
    "shopping_mall":   {"shopping": 0.8, "entertainment": 0.2},
    "store":           {"shopping": 0.9, "food": 0.1},
    "restaurant":      {"food": 1.0},
    "hospital":        {"health": 1.0},
    "transit_station":  {"transit": 1.0},
    "park":            {"lifestyle": 0.7, "health": 0.3},
    "gym":             {"lifestyle": 0.5, "health": 0.5},
    "movie_theater":   {"entertainment": 1.0},
    "bar":             {"entertainment": 0.7, "food": 0.3},
    "night_club":      {"entertainment": 1.0},
    "place_of_worship": {"lifestyle": 1.0},
    "lodging":         {"business": 0.5, "lifestyle": 0.5},
    "corporate_office": {"business": 1.0},
    "coworking_space":  {"business": 0.9, "lifestyle": 0.1},
    "it_park":         {"business": 1.0},
    "residential":     {"lifestyle": 1.0},
}

# Dominant land-use inference
TYPE_TO_LANDUSE: dict[str, str] = {
    "school": "education",
    "university": "education",
    "shopping_mall": "commercial",
    "store": "commercial",
    "restaurant": "commercial",
    "hospital": "health",
    "transit_station": "transit",
    "park": "recreation",
    "gym": "recreation",
    "movie_theater": "entertainment",
    "bar": "entertainment",
    "night_club": "entertainment",
    "place_of_worship": "residential",
    "lodging": "hospitality",
    "corporate_office": "office",
    "coworking_space": "office",
    "it_park": "office",
    "residential": "residential",
}

# POI type importance (base weight)
TYPE_IMPORTANCE: dict[str, float] = {
    "hospital": 1.5,
    "university": 1.3,
    "school": 1.2,
    "shopping_mall": 1.4,
    "store": 0.8,
    "restaurant": 0.7,
    "transit_station": 1.0,
    "park": 0.9,
    "gym": 0.8,
    "movie_theater": 1.0,
    "bar": 0.7,
    "night_club": 0.8,
    "place_of_worship": 0.9,
    "lodging": 1.0,
    "corporate_office": 1.6,
    "coworking_space": 1.4,
    "it_park": 1.7,
    "residential": 1.3,
}

# Collector concurrency
COLLECTOR_CONCURRENCY = 10
COLLECTOR_RETRY_MAX = 3
