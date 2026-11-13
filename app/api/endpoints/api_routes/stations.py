from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Literal
from pydantic import StringConstraints
from typing_extensions import Annotated

from app.database.session import get_db
from app.services.map_station_service import (
    MapStationError, get_map_station, list_map_stations,
)

router = APIRouter(prefix="/api/map", tags=["Map station display"])


@router.get("/stations")
def map_stations(
    lat: float | None = Query(default=None, ge=-90.0, le=90.0),
    lng: float | None = Query(default=None, ge=-180.0, le=180.0),
    search: str | None = None,
    fuel_type: str | None = None,
    service: str | None = None,
    radius_km: float | None = Query(default=None, gt=0.0, le=50.0),
    amenity_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=8)]] = Query(default=[], max_length=50),
    amenity_match: Literal['all', 'any'] = 'all',
    db: Session = Depends(get_db),
):
    try:
        stations = list_map_stations(
            db, latitude=lat, longitude=lng, search=search,
            fuel_type=fuel_type, service_name=service, radius_km=radius_km,
            amenity_ids=amenity_ids, amenity_match=amenity_match,
        )
    except MapStationError as error:
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu trạm xăng.") from error
    return {"status": "success", "total": len(stations), "stations": stations}


@router.get("/stations/{tx_ma}")
def map_station_detail(
    tx_ma: str,
    lat: float | None = Query(default=None, ge=-90.0, le=90.0),
    lng: float | None = Query(default=None, ge=-180.0, le=180.0),
    db: Session = Depends(get_db),
):
    try:
        station = get_map_station(db, tx_ma, latitude=lat, longitude=lng)
    except MapStationError as error:
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu trạm xăng.") from error
    if station is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm xăng")
    return {"status": "success", "station": station}
