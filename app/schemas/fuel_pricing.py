from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class FuelPriceItemResponse(BaseModel):
    fuel_id: str
    name: str
    current_price: int
    previous_price: int | None = None
    previous_effective_date: date | None = None
    change_vnd: int | None = None
    change_percent: float | None = None
    has_station_variation: bool = False


class FuelPriceLatestResponse(BaseModel):
    source: Literal["petrolimex", "pvoil", "database_fallback"]
    source_message: str
    effective_date: date | None = None
    effective_time: str | None = None
    is_stale: bool = False
    stale_message: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
    is_cached: bool = False
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    persistence_status: str = "database"
    history_message: str | None = None
    sync_status: str = "database"
    sync_error: str | None = None
    sources_attempted: list[dict] = Field(default_factory=list)
    refresh_on_request_config: str | None = None
    station_price_writes_enabled: bool = False
    items: list[FuelPriceItemResponse] = Field(default_factory=list)


class FuelPriceHistoryPoint(BaseModel):
    date: date
    price: int
    has_station_variation: bool = False
    effective_time: str | None = None
    source_url: str | None = None
    synced_at: datetime | None = None


class FuelPriceHistoryResponse(BaseModel):
    days: int
    source: Literal['petrolimex', 'pvoil'] = 'petrolimex'
    sources: list[str] = Field(default_factory=list)
    storage_ready: bool = False
    series: dict[str, list[FuelPriceHistoryPoint]] = Field(default_factory=dict)
