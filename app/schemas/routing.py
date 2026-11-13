from pydantic import BaseModel, Field
from typing import Literal, Annotated
from pydantic import StringConstraints

from app.core.routing_config import (
    DEFAULT_RADIUS_KM, DEFAULT_RECOMMENDATION_LIMIT, MAX_RADIUS_KM,
    MAX_RECOMMENDATION_LIMIT,
)


class RoutingRecommendationRequest(BaseModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    heading: float | None = Field(default=None, ge=0.0, lt=360.0)
    radius_km: float = Field(default=DEFAULT_RADIUS_KM, gt=0.0, le=MAX_RADIUS_KM)
    exclude_stations: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_RECOMMENDATION_LIMIT, ge=1, le=MAX_RECOMMENDATION_LIMIT)
    amenity_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=8)]] = Field(default_factory=list, max_length=50)
    amenity_match: Literal['all', 'any'] = 'all'
    fuel_type: str | None = Field(default=None, max_length=64)
    search: str | None = Field(default=None, max_length=128)
    service_name: str | None = Field(default=None, max_length=64)


class StationRecommendationResponse(BaseModel):
    station_id: str
    station_name: str
    address: str
    straight_line_distance_km: float
    distance_km: float
    duration_minutes: float
    bearing: float
    heading_difference: float | None
    traffic_factor: float
    traffic_level: str
    traffic_penalty: float
    uturn_count: int | None
    uturn_inferred: bool
    uturn_penalty: float
    behind_penalty: float
    score: float
    routing_source: str
    labels: list[str] = Field(default_factory=list)
    reason: str


class RoutingRecommendationResponse(BaseModel):
    recommendations: list[StationRecommendationResponse] = Field(default_factory=list)
    message: str | None = None



class RouteGeometryResponse(BaseModel):
    geometry: dict
    distance_km: float
    duration_minutes: float
    routing_source: str
    is_fallback: bool
    steps: list[dict] = Field(default_factory=list)
