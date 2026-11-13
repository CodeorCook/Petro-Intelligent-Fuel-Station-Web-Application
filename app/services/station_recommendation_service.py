import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.routing_config import (
    BEHIND_PENALTY, DISTANCE_WEIGHT, DURATION_WEIGHT, TRAFFIC_WEIGHT,
    UTURN_BASE_PENALTY,
)
from app.models import TramXang
from app.schemas.routing import RoutingRecommendationRequest
from app.services.routing_service import (
    OSRMRoutingProvider, RoutingProvider, calculate_bearing,
    calculate_heading_difference, haversine_distance,
)
from app.services.traffic_service import lookup_traffic_factor
from app.services.station_visibility import public_station_query
from app.services.station_discovery import filter_station_query


NO_STATION_MESSAGE = "Không tìm thấy trạm xăng phù hợp trong bán kính hiện tại."


class RoutingRecommendationError(Exception):
    pass


def recommend_stations(
    db: Session,
    request: RoutingRecommendationRequest,
    routing_provider: RoutingProvider | None = None,
) -> dict[str, Any]:
    provider = routing_provider or OSRMRoutingProvider()
    excluded = set(request.exclude_stations)
    try:
        # TODO: Replace the full scan with a PostGIS/geospatial pre-filter when
        # the station dataset becomes large.
        query = filter_station_query(db, public_station_query(), amenity_ids=request.amenity_ids,
            amenity_match=request.amenity_match, fuel_type=request.fuel_type,
            search=request.search, service_name=request.service_name)
        stations = db.scalars(query).all()
        candidates: list[dict[str, Any]] = []
        for station in stations:
            # Exclusions are applied before any distance/routing work.
            if station.tx_ma in excluded:
                continue
            station_lat = float(station.tx_vido)
            station_lon = float(station.tx_kinhdo)
            straight_distance = haversine_distance(
                request.latitude, request.longitude, station_lat, station_lon
            )
            if straight_distance > request.radius_km:
                continue
            route = provider.get_route_metrics(
                request.latitude, request.longitude, station_lat, station_lon
            )
            bearing = calculate_bearing(
                request.latitude, request.longitude, station_lat, station_lon
            )
            heading_difference = (
                calculate_heading_difference(bearing, request.heading)
                if request.heading is not None
                else None
            )
            behind_penalty = calculate_behind_penalty(heading_difference)
            traffic = _lookup_station_traffic(db, route.road_names, station.tx_trucduong)
            traffic_factor = max(1.0, float(traffic["he_so"]))
            duration = route.duration_minutes
            if not route.duration_includes_traffic:
                duration *= traffic_factor
            uturn_penalty, uturn_inferred = calculate_uturn_penalty(
                route.uturn_count,
                route.is_fallback,
                bool(station.tx_coconluon),
                heading_difference,
            )
            traffic_penalty = max(0.0, traffic_factor - 1.0) * TRAFFIC_WEIGHT
            # Penalties are additive because a smaller score is better.
            score = (
                DISTANCE_WEIGHT * route.distance_km
                + DURATION_WEIGHT * duration
                + uturn_penalty
                + traffic_penalty
                + behind_penalty
            )
            candidates.append(
                {
                    "station_id": station.tx_ma,
                    "station_name": station.tx_ten,
                    "address": station.tx_diachi,
                    "straight_line_distance_km": straight_distance,
                    "distance_km": route.distance_km,
                    "duration_minutes": duration,
                    "bearing": bearing,
                    "heading_difference": heading_difference,
                    "traffic_factor": traffic_factor,
                    "traffic_level": traffic["muc_do"],
                    "traffic_penalty": traffic_penalty,
                    "uturn_count": route.uturn_count,
                    "uturn_inferred": uturn_inferred,
                    "uturn_penalty": uturn_penalty,
                    "behind_penalty": behind_penalty,
                    "score": score,
                    "routing_source": route.routing_source,
                }
            )
    except SQLAlchemyError as error:
        raise RoutingRecommendationError("Unable to query routing data") from error

    if not candidates:
        return {"recommendations": [], "message": NO_STATION_MESSAGE}
    candidates.sort(key=lambda item: (item["score"], item["distance_km"], item["station_id"]))
    _apply_labels(candidates)
    recommendations = [_round_metrics(item) for item in candidates[: request.limit]]
    return {"recommendations": recommendations, "message": None}


def _lookup_station_traffic(
    db: Session, road_names: list[str], station_road_name: str | None
) -> dict[str, Any]:
    for road_name in road_names:
        traffic = lookup_traffic_factor(road_name, db=db)
        if traffic.get("td_ma") is not None:
            return traffic
    if station_road_name:
        # TX_TRUCDUONG is contextual metadata, not an assertion that this is
        # the full driven route.
        return lookup_traffic_factor(station_road_name, db=db)
    return {"he_so": 1.0, "muc_do": "THONG_THOANG"}


def calculate_behind_penalty(heading_difference: float | None) -> float:
    return BEHIND_PENALTY if heading_difference is not None and heading_difference > 90.0 else 0.0


def calculate_uturn_penalty(
    uturn_count: int | None,
    is_fallback: bool,
    has_median: bool,
    heading_difference: float | None,
) -> tuple[float, bool]:
    if uturn_count is not None:
        return UTURN_BASE_PENALTY * max(0, uturn_count), False
    if (
        is_fallback
        and has_median
        and heading_difference is not None
        and heading_difference > 90.0
    ):
        # This is an explicit heuristic; it does not invent a U-turn count.
        return UTURN_BASE_PENALTY, True
    return 0.0, False


def _apply_labels(candidates: list[dict[str, Any]]) -> None:
    nearest = min(item["distance_km"] for item in candidates)
    fastest = min(item["duration_minutes"] for item in candidates)
    lowest_traffic = min(item["traffic_factor"] for item in candidates)
    for item in candidates:
        labels: list[str] = []
        if item["uturn_penalty"] > 0.0:
            labels.append("OPPOSITE_DIRECTION")
        if item["behind_penalty"] > 0.0:
            labels.append("BEHIND_DIRECTION")
        if math.isclose(item["duration_minutes"], fastest):
            labels.append("FASTEST")
        if math.isclose(item["distance_km"], nearest):
            labels.append("NEAREST")
        if math.isclose(item["traffic_factor"], lowest_traffic):
            labels.append("LOW_TRAFFIC")
        item["labels"] = labels
        item["reason"] = _build_reason(labels, item["uturn_inferred"])


def _build_reason(labels: list[str], uturn_inferred: bool) -> str:
    reasons = {
        "OPPOSITE_DIRECTION": (
            "Trạm có khả năng cần quay đầu do hướng tiếp cận/dải phân cách."
            if uturn_inferred
            else "Lộ trình có thao tác quay đầu được provider xác nhận."
        ),
        "BEHIND_DIRECTION": "Trạm nằm phía sau hướng di chuyển hiện tại.",
        "FASTEST": "Thời gian dự kiến thấp.",
        "NEAREST": "Quãng đường định tuyến ước tính ngắn.",
        "LOW_TRAFFIC": "Tuyến đường có hệ số giao thông thấp.",
    }
    return " ".join(reasons[label] for label in labels)


def _round_metrics(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    for field in (
        "straight_line_distance_km", "distance_km", "duration_minutes", "bearing",
        "heading_difference", "traffic_factor", "traffic_penalty", "uturn_penalty",
        "behind_penalty", "score",
    ):
        if result[field] is not None:
            result[field] = round(float(result[field]), 4)
    return result
