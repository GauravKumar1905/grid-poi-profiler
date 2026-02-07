"""Grid generation: 200 m square grid from GPS bounding box."""

import math
from dataclasses import dataclass

R = 6_378_137.0  # Earth radius in meters (WGS84)


@dataclass
class GridPoint:
    id: str
    i: int
    j: int
    lat: float
    lon: float


def offset_point(lat: float, lon: float, dx: float, dy: float) -> tuple[float, float]:
    """Compute new lat/lon by shifting dx meters east and dy meters north."""
    new_lat = lat + (dy / R) * (180.0 / math.pi)
    new_lon = lon + (dx / (R * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return new_lat, new_lon


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two lat/lon points (haversine formula)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def generate_grid(
    origin_lat: float,
    origin_lon: float,
    size_x: int,
    size_y: int,
    spacing_m: float = 200.0,
) -> list[GridPoint]:
    """Generate a rectangular grid of points.

    origin is the south-west corner.
    size_x = number of points along east axis (columns).
    size_y = number of points along north axis (rows).
    """
    points: list[GridPoint] = []
    for j in range(size_y):
        for i in range(size_x):
            dx = i * spacing_m
            dy = j * spacing_m
            lat, lon = offset_point(origin_lat, origin_lon, dx, dy)
            points.append(GridPoint(id=f"g_{i}_{j}", i=i, j=j, lat=lat, lon=lon))
    return points


def generate_grid_from_bbox(
    south: float,
    north: float,
    west: float,
    east: float,
    spacing_m: float = 200.0,
) -> list[GridPoint]:
    """Generate grid covering a lat/lon bounding box at the given spacing."""
    width_m = haversine(south, west, south, east)
    height_m = haversine(south, west, north, west)
    size_x = int(width_m / spacing_m) + 1
    size_y = int(height_m / spacing_m) + 1
    return generate_grid(south, west, size_x, size_y, spacing_m)
