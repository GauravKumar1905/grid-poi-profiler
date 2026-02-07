"""Pydantic models for API responses."""

from pydantic import BaseModel


class GridPointModel(BaseModel):
    id: str
    i: int
    j: int
    lat: float
    lon: float


class NearestPOI(BaseModel):
    place_id: str
    name: str
    type: str
    distance_m: float


class POISummary(BaseModel):
    nearest: list[NearestPOI]
    counts: dict[str, int]


class AudienceProfile(BaseModel):
    age_profile: dict[str, float]
    interests: dict[str, float]
    footfall_proxy: float
    confidence: float


class ModelMetadata(BaseModel):
    sigma_m: float
    max_influence_m: float


class ProfileResponse(BaseModel):
    grid_point_id: str
    lat: float
    lon: float
    poi_summary: POISummary
    geographic_attributes: list[str]
    audience: AudienceProfile
    model_metadata: ModelMetadata


class POIModel(BaseModel):
    place_id: str
    name: str
    lat: float
    lon: float
    types: list[str]
    rating: float | None = None
    user_ratings_total: int | None = None
