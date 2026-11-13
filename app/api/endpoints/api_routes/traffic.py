from datetime import time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas import (
    HeSoGiaoThongCreate, HeSoGiaoThongResponse, HeSoGiaoThongUpdate,
    TuyenDuongCreate, TuyenDuongResponse, TuyenDuongUpdate,
)
from app.services import traffic_service

router = APIRouter(
    prefix="/api",
    responses={400: {"description": "Bad request"}, 404: {"description": "Not found"}, 409: {"description": "Conflict"}},
)


def _run(operation):
    try:
        return operation()
    except traffic_service.TrafficError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/roads", response_model=list[TuyenDuongResponse], tags=["Roads"])
def list_roads(db: Session = Depends(get_db)):
    return traffic_service.list_roads(db)


@router.post("/roads", response_model=TuyenDuongResponse, status_code=status.HTTP_201_CREATED, tags=["Roads"])
def create_road(payload: TuyenDuongCreate, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.create_road(db, payload.model_dump()))


@router.get("/roads/{td_ma}", response_model=TuyenDuongResponse, tags=["Roads"])
def get_road(td_ma: str, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.get_road(db, td_ma))


@router.patch("/roads/{td_ma}", response_model=TuyenDuongResponse, tags=["Roads"])
def update_road(td_ma: str, payload: TuyenDuongUpdate, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.update_road(db, td_ma, payload.model_dump(exclude_unset=True)))


@router.delete("/roads/{td_ma}", status_code=status.HTTP_204_NO_CONTENT, tags=["Roads"])
def delete_road(td_ma: str, db: Session = Depends(get_db)) -> Response:
    _run(lambda: traffic_service.delete_road(db, td_ma))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/traffic-factors/lookup", tags=["Traffic factors"])
def lookup_traffic_factor(road: str, check_time: time | None = None, db: Session = Depends(get_db)):
    return traffic_service.lookup_traffic_factor(road, check_time, db=db)


@router.get("/traffic-factors", response_model=list[HeSoGiaoThongResponse], tags=["Traffic factors"])
def list_traffic_factors(road_id: str | None = None, db: Session = Depends(get_db)):
    return traffic_service.list_traffic_factors(db, road_id)


@router.post("/traffic-factors", response_model=HeSoGiaoThongResponse, status_code=status.HTTP_201_CREATED, tags=["Traffic factors"])
def create_traffic_factor(payload: HeSoGiaoThongCreate, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.create_traffic_factor(db, payload.model_dump()))


@router.get("/traffic-factors/{hsgt_ma}", response_model=HeSoGiaoThongResponse, tags=["Traffic factors"])
def get_traffic_factor(hsgt_ma: str, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.get_traffic_factor(db, hsgt_ma))


@router.patch("/traffic-factors/{hsgt_ma}", response_model=HeSoGiaoThongResponse, tags=["Traffic factors"])
def update_traffic_factor(hsgt_ma: str, payload: HeSoGiaoThongUpdate, db: Session = Depends(get_db)):
    return _run(lambda: traffic_service.update_traffic_factor(db, hsgt_ma, payload.model_dump(exclude_unset=True)))


@router.delete("/traffic-factors/{hsgt_ma}", status_code=status.HTTP_204_NO_CONTENT, tags=["Traffic factors"])
def delete_traffic_factor(hsgt_ma: str, db: Session = Depends(get_db)) -> Response:
    _run(lambda: traffic_service.delete_traffic_factor(db, hsgt_ma))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
