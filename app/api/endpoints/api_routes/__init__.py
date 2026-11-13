from app.api.endpoints.api_routes.catalog import router as catalog_router
from app.api.endpoints.api_routes.workflows import router as workflow_router
from app.api.endpoints.api_routes.traffic import router as traffic_router
from app.api.endpoints.api_routes.routing import router as routing_router
from app.api.endpoints.api_routes.stations import router as map_stations_router
from app.api.endpoints.api_routes.fuel_pricing import router as fuel_pricing_router

__all__ = [
    "catalog_router", "workflow_router", "traffic_router", "routing_router",
    "map_stations_router", "fuel_pricing_router",
]
