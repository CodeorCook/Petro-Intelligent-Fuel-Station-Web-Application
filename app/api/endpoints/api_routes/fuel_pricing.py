from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from typing import Literal

from app.database.session import get_db
from app.schemas.fuel_pricing import FuelPriceHistoryResponse, FuelPriceLatestResponse
from app.services.fuel_pricing_service import (
    FuelPriceDatabaseError, get_fuel_price_history, get_latest_fuel_prices,
)

router = APIRouter(prefix="/api/fuel-prices", tags=["Fuel reference prices"])


@router.get("/latest", response_model=FuelPriceLatestResponse)
async def latest_fuel_prices(response: Response, refresh: bool = Query(default=False), db: Session = Depends(get_db)) -> FuelPriceLatestResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await get_latest_fuel_prices(db, force_refresh=refresh)
    except FuelPriceDatabaseError as error:
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu giá nhiên liệu.") from error
    return FuelPriceLatestResponse.model_validate(result)


@router.get("/history", response_model=FuelPriceHistoryResponse)
def fuel_price_history(
    days: int = Query(default=30, ge=1, le=365),
    source: Literal['petrolimex', 'pvoil'] = Query(default='petrolimex'),
    db: Session = Depends(get_db),
) -> FuelPriceHistoryResponse:
    try:
        result = get_fuel_price_history(db, days, source=source)
    except FuelPriceDatabaseError as error:
        raise HTTPException(status_code=500, detail="Không thể tải lịch sử giá nhiên liệu.") from error
    return FuelPriceHistoryResponse.model_validate(result)
