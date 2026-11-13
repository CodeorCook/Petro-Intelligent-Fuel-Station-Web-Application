from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.services.station_visibility import get_public_station

from app.database.session import get_db
from app.schemas.routing import (
    RouteGeometryResponse, RoutingRecommendationRequest, RoutingRecommendationResponse,
)
from app.services.routing_service import get_route_geometry
from app.services.station_recommendation_service import (
    RoutingRecommendationError, recommend_stations,
)

router = APIRouter(prefix="/api/routing", tags=["Smart routing"])


@router.get("/route", response_model=RouteGeometryResponse)
def route_geometry(
    start_lat: float = Query(ge=-90.0, le=90.0),
    start_lng: float = Query(ge=-180.0, le=180.0),
    end_lat: float = Query(ge=-90.0, le=90.0),
    end_lng: float = Query(ge=-180.0, le=180.0),
    station_id: str | None = Query(default=None, min_length=1, max_length=8),
    db: Session = Depends(get_db),
) -> RouteGeometryResponse:
    # Generic coordinate routing remains supported. Station-targeted requests
    # revalidate publication and always use approved canonical coordinates.
    if station_id is not None:
        try:
            station = get_public_station(db, station_id)
        except SQLAlchemyError as error:
            raise HTTPException(503, "Thông tin trạm tạm thời không khả dụng") from error
        if station is None:
            raise HTTPException(404, "Trạm không còn công khai hoặc không tồn tại")
        end_lat, end_lng = float(station.tx_vido), float(station.tx_kinhdo)
    route = get_route_geometry(start_lat, start_lng, end_lat, end_lng)
    return RouteGeometryResponse.model_validate(route, from_attributes=True)
@router.post("/recommendations", response_model=RoutingRecommendationResponse)
def routing_recommendations(
    payload: RoutingRecommendationRequest,
    db: Session = Depends(get_db),
) -> RoutingRecommendationResponse:
    try:
        result = recommend_stations(db, payload)
    except RoutingRecommendationError as error:
        raise HTTPException(status_code=500, detail="Không thể tính gợi ý định tuyến lúc này.") from error
    return RoutingRecommendationResponse.model_validate(result)
