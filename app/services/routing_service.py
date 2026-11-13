import json
import logging
import math
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.routing_config import (
    FALLBACK_ROAD_FACTOR, FALLBACK_SPEED_KMH, OSRM_BASE_URL,
    OSRM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RouteMetrics:
    distance_km: float
    duration_minutes: float
    uturn_count: int | None = None
    road_names: list[str] = field(default_factory=list)
    routing_source: str = "unknown"
    is_fallback: bool = False
    duration_includes_traffic: bool = False


@dataclass(slots=True)
class RouteGeometry:
    geometry: dict[str, Any]
    distance_km: float
    duration_minutes: float
    routing_source: str
    is_fallback: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
class RoutingProvider(ABC):
    """Provider-neutral contract for future road-routing integrations."""

    @abstractmethod
    def get_route_metrics(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
    ) -> RouteMetrics:
        raise NotImplementedError


class FallbackRoutingProvider(RoutingProvider):
    def get_route_metrics(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
    ) -> RouteMetrics:
        straight_distance = haversine_distance(user_lat, user_lon, station_lat, station_lon)
        # 1.2 is a fallback heuristic, not measured road distance.
        estimated_road_distance = straight_distance * FALLBACK_ROAD_FACTOR
        base_duration = estimated_road_distance / FALLBACK_SPEED_KMH * 60.0
        return RouteMetrics(
            distance_km=estimated_road_distance,
            duration_minutes=base_duration,
            uturn_count=None,
            road_names=[],
            routing_source="haversine_fallback",
            is_fallback=True,
            duration_includes_traffic=False,
        )

    def get_route_geometry(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
    ) -> RouteGeometry:
        metrics = self.get_route_metrics(user_lat, user_lon, station_lat, station_lon)
        return RouteGeometry(
            geometry={
                "type": "LineString",
                "coordinates": [[user_lon, user_lat], [station_lon, station_lat]],
            },
            distance_km=metrics.distance_km,
            duration_minutes=metrics.duration_minutes,
            routing_source=metrics.routing_source,
            is_fallback=True,
        )


class OSRMRoutingProvider(RoutingProvider):
    """OSRM adapter. Public OSRM durations do not include live traffic."""

    def __init__(
        self,
        base_url: str = OSRM_BASE_URL,
        timeout_seconds: float = OSRM_TIMEOUT_SECONDS,
        opener: Callable[..., Any] = urllib.request.urlopen,
        fallback_provider: FallbackRoutingProvider | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self.fallback_provider = fallback_provider or FallbackRoutingProvider()

    def get_route_metrics(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
    ) -> RouteMetrics:
        try:
            route = self._fetch_route(
                user_lat, user_lon, station_lat, station_lon,
                overview="false", steps=True,
            )
            road_names, uturn_count = self._parse_steps(route)
            return RouteMetrics(
                distance_km=float(route["distance"]) / 1000.0,
                duration_minutes=float(route["duration"]) / 60.0,
                uturn_count=uturn_count,
                road_names=road_names,
                routing_source="osrm",
                is_fallback=False,
                duration_includes_traffic=False,
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            logger.warning("OSRM metrics unavailable; using controlled fallback: %s", error)
            return self.fallback_provider.get_route_metrics(
                user_lat, user_lon, station_lat, station_lon
            )

    def get_route_geometry(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
    ) -> RouteGeometry:
        try:
            route = self._fetch_route(
                user_lat, user_lon, station_lat, station_lon,
                overview="full", steps=True,
            )
            geometry = route.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
                raise ValueError("OSRM response did not contain a GeoJSON LineString")
            return RouteGeometry(
                geometry=geometry,
                distance_km=float(route["distance"]) / 1000.0,
                duration_minutes=float(route["duration"]) / 60.0,
                routing_source="osrm",
                is_fallback=False,
                steps=self._navigation_steps(route),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            logger.warning("OSRM geometry unavailable; using controlled fallback: %s", error)
            return self.fallback_provider.get_route_geometry(
                user_lat, user_lon, station_lat, station_lon
            )

    def _fetch_route(
        self,
        user_lat: float,
        user_lon: float,
        station_lat: float,
        station_lon: float,
        *,
        overview: str,
        steps: bool,
    ) -> dict[str, Any]:
        coordinates = f"{user_lon},{user_lat};{station_lon},{station_lat}"
        query = urllib.parse.urlencode(
            {"overview": overview, "geometries": "geojson", "steps": str(steps).lower()}
        )
        request = urllib.request.Request(
            f"{self.base_url}/route/v1/driving/{coordinates}?{query}",
            headers={"User-Agent": "PetroApp/1.0"},
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise ValueError("OSRM returned no usable route")
        return payload["routes"][0]

    @staticmethod
    def _navigation_steps(route: dict[str, Any]) -> list[dict[str, Any]]:
        """Expose only verified OSRM metadata; missing steps means preview-only."""
        result = []
        for leg in route.get('legs') or []:
            for step in leg.get('steps') or []:
                maneuver = step.get('maneuver') or {}
                geometry = step.get('geometry') or {}
                location = maneuver.get('location')
                coordinates = geometry.get('coordinates')
                if (not isinstance(maneuver.get('type'), str) or not isinstance(location, list)
                    or len(location) != 2 or geometry.get('type') != 'LineString'
                    or not isinstance(coordinates, list) or not coordinates):
                    return []
                def valid_coordinate(point):
                    return (isinstance(point, list) and len(point) == 2
                        and all(isinstance(value, (float, int)) and math.isfinite(value) for value in point)
                        and abs(point[0]) <= 180 and abs(point[1]) <= 90)
                if not valid_coordinate(location) or not all(valid_coordinate(point) for point in coordinates):
                    return []
                distance, duration = step.get('distance'), step.get('duration')
                if any(not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 for value in (distance, duration)):
                    return []
                result.append({'distance_m': float(distance),
                    'duration_seconds': float(duration),
                    'road_name': step.get('name') or '', 'maneuver': maneuver,
                    'geometry': geometry})
        return result

    @staticmethod
    def _parse_steps(route: dict[str, Any]) -> tuple[list[str], int | None]:
        names: list[str] = []
        explicit_uturns = 0
        for leg in route.get("legs") or []:
            for step in leg.get("steps") or []:
                name = step.get("name")
                if isinstance(name, str) and name.strip() and name not in names:
                    names.append(name.strip())
                maneuver = step.get("maneuver") or {}
                maneuver_type = str(maneuver.get("type", "")).lower().replace("-", "")
                modifier = str(maneuver.get("modifier", "")).lower().replace("-", "")
                if maneuver_type == "uturn" or modifier == "uturn":
                    explicit_uturns += 1
        # Be conservative: absence of an explicit maneuver is not proof of zero U-turns.
        return names, explicit_uturns if explicit_uturns > 0 else None


def get_route_geometry(
    user_lat: float,
    user_lon: float,
    station_lat: float,
    station_lon: float,
    provider: OSRMRoutingProvider | FallbackRoutingProvider | None = None,
) -> RouteGeometry:
    selected_provider = provider or OSRMRoutingProvider()
    return selected_provider.get_route_geometry(
        user_lat, user_lon, station_lat, station_lon
    )

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine is straight-line distance and is not actual driving distance."""
    earth_radius_km = 6371.0088
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    return earth_radius_km * 2.0 * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))


def calculate_bearing(
    user_lat: float, user_lon: float, station_lat: float, station_lon: float
) -> float:
    lat1, lat2 = math.radians(user_lat), math.radians(station_lat)
    delta_lon = math.radians(station_lon - user_lon)
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def calculate_heading_difference(bearing: float, heading: float) -> float:
    return abs((bearing - heading + 180.0) % 360.0 - 180.0)
