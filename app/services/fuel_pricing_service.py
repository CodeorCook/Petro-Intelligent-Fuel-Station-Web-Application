"""Business logic for official reference prices and station-specific GIA rows.

Petrolimex Region 2 is the primary reference. THOI_DIEM stores DATE only, so
adjustment time is not persisted. GIA is station-specific while the provider
publishes reference prices; replication to demo stations is a demo assumption,
not proof of each station's actual selling price.
"""

import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Gia, NhienLieu, ThoiDiem, TramXang
from app.services import fuel_crawler, fuel_reference_store as reference_store
from app.services.fuel_crawler import (
    CrawledFuelPrice, FuelCrawlerError, FuelCrawlerNetworkError,
    FuelCrawlerParseError,
)

logger = logging.getLogger(__name__)
SUPPORTED_FUEL_IDS = ("NL000001", "NL000002", "NL000003")
LEGACY_REFERENCE_STATION_IDS = tuple(f"TX{i:06d}" for i in range(1, 7))
REFRESH_LOCK_KEY = 706381042
_last_sync_attempt_at: datetime | None = None
_last_sync_success_at: datetime | None = None
CANONICAL_FUEL_NAMES = {
    "NL000001": "Xăng E10 RON 95-III",
    "NL000002": "Xăng E5 RON 92-II",
    "NL000003": "Dầu DO 0,05S-II",
}


class FuelPriceDatabaseError(Exception):
    """A fuel-price database operation failed without exposing internals."""


class FuelPriceRefreshBusy(Exception):
    """Another approved refresh owns the shared PostgreSQL advisory lock."""


def _legacy_station_filter():
    return (TramXang.tx_du_lieu_cu.is_(True), TramXang.tx_ma.in_(LEGACY_REFERENCE_STATION_IDS))


def plan_price_inserts(db: Session, prices: list[CrawledFuelPrice]) -> dict:
    """Read-only dry run. Never replace any existing station-specific PK."""
    stations = list(db.scalars(select(TramXang.tx_ma).where(*_legacy_station_filter()).order_by(TramXang.tx_ma)))
    missing, conflicts, skipped = [], [], 0
    for station in stations:
        for price in prices:
            existing = db.get(Gia, (price.effective_date, station, price.fuel_id), populate_existing=True)
            record = dict(date=price.effective_date.isoformat(), station_id=station,
                          fuel_id=price.fuel_id, price=str(price.price))
            if existing is None:
                missing.append(record)
            elif existing.dongia != price.price:
                conflicts.append({**record, "existing_price": str(existing.dongia)})
            else:
                skipped += 1
    return {"legacy_demo_stations": stations, "inserts": missing, "conflicts": conflicts, "skipped": skipped}


def persist_crawled_prices(db: Session, prices: list[CrawledFuelPrice]) -> int:
    unique_prices = {
        (item.effective_date, item.fuel_id): item
        for item in prices
        if item.fuel_id in SUPPORTED_FUEL_IDS
    }
    try:
        if db.bind.dialect.name == "postgresql" and not db.scalar(text(f"SELECT pg_try_advisory_xact_lock({REFRESH_LOCK_KEY})")):
            db.rollback()
            raise FuelPriceRefreshBusy()
        plan = plan_price_inserts(db, list(unique_prices.values()))
        if plan["conflicts"]:
            logger.warning("Reference refresh blocked by %d historical conflicts; no rows overwritten or partially inserted", len(plan["conflicts"]))
            db.rollback()
            return 0
        for effective_date in sorted({key[0] for key in unique_prices}):
            if db.get(ThoiDiem, effective_date) is None:
                db.add(ThoiDiem(ngaygio=effective_date))
        # Flush establishes THOI_DIEM before GIA without adding another commit.
        db.flush()

        # Only explicitly marked legacy demo stations receive reference replicas.
        # Approval of a new station does not verify its actual retail prices.
        station_ids = [value.strip() for value in db.scalars(
            select(TramXang.tx_ma).where(*_legacy_station_filter())
        ).all()]
        available_fuels = {
            value.strip()
            for value in db.scalars(
                select(NhienLieu.nl_ma).where(NhienLieu.nl_ma.in_(SUPPORTED_FUEL_IDS))
            ).all()
        }
        inserted = 0
        # Official reference price replicated to demo stations because current schema
        # does not have a separate market/reference-price table.
        for station_id in station_ids:
            for (effective_date, fuel_id), item in unique_prices.items():
                if fuel_id not in available_fuels:
                    logger.warning("Mapped fuel %s is absent from database; price ignored", fuel_id)
                    continue
                existing = db.get(Gia, (effective_date, station_id, fuel_id))
                if existing is not None:
                    if existing.dongia != item.price:
                        logger.warning("Reference price conflict date=%s station=%s fuel=%s existing=%s official=%s; preserved",
                                       effective_date, station_id, fuel_id, existing.dongia, item.price)
                    continue
                db.add(
                    Gia(
                        ngaygio=effective_date,
                        tx_ma=station_id,
                        nl_ma=fuel_id,
                        dongia=item.price,
                    )
                )
                inserted += 1
        db.commit()
        logger.info("Persisted %d official reference-price rows", inserted)
        return inserted
    except SQLAlchemyError as error:
        db.rollback()
        raise FuelPriceDatabaseError("Unable to persist fuel prices") from error


async def get_latest_fuel_prices(
    db: Session, *, force_refresh: bool = False
) -> dict[str, Any]:
    global _last_sync_attempt_at, _last_sync_success_at
    metadata = {"persistence_status": "database"}
    def finish(response):
        return {**response, **metadata, "last_attempt_at": _last_sync_attempt_at,
                "last_success_at": _last_sync_success_at}
    # Request-time checks are reference-only. The existing task-mode setting
    # must never be bypassed to replicate reference prices into station GIA rows.
    metadata["station_price_writes_enabled"] = False
    metadata["refresh_on_request_config"] = os.getenv("FUEL_PRICE_REFRESH_ON_REQUEST", "true")
    _last_sync_attempt_at = datetime.now(timezone.utc)
    try:
        provider_result = await fuel_crawler.crawl_reference_prices(
            force_refresh=force_refresh
        )
        source = provider_result.provider_name
        crawled = provider_result.prices
        if not crawled or source != "petrolimex":
            raise FuelCrawlerParseError("Invalid reference provider result")
        metadata.update(source_url=provider_result.source_url, fetched_at=provider_result.fetched_at,
                        is_cached=provider_result.is_cached)
        metadata["sources_attempted"] = list(provider_result.attempts)
        try:
            metadata["persistence_status"] = reference_store.persist(db, provider_result)
        except reference_store.ReferenceStorageError as error:
            logger.warning("Reference history not saved: %s", error)
            metadata.update(persistence_status="blocked", sync_status="error",
                            sync_error="Chưa thể lưu kỳ giá mới; đang giữ giá Petrolimex đã lưu.",
                            history_message="Chưa thể lưu lịch sử giá tham chiếu.")
            saved = reference_store.latest(db, 'petrolimex')
            if saved:
                return finish(_response_from_saved(db, 'petrolimex', saved[0]))
            return finish(dict(source='database_fallback', source_message='Chưa có giá Petrolimex đã lưu',
                               effective_date=None, effective_time=None, items=[]))
        metadata["sync_status"] = "verified"
        _last_sync_success_at = provider_result.fetched_at
        saved = reference_store.latest(db, source)
        live_period = (crawled[0].effective_date, crawled[0].effective_time or '')
        if saved:
            last = saved[0][0]
            saved_period = (last['effective_date'], last['effective_time'].isoformat() if last['effective_time'] else '')
            if saved_period > live_period:
                return finish(_response_from_saved(db, source, saved[0]))
        response = build_latest_from_live(db, crawled, source)
        _validate_published_changes(response["items"], crawled)
        return finish(response)
    except FuelCrawlerError as error:
        logger.warning("Reference synchronization failed: %s", error)
        metadata.update(sync_status="error", sync_error=str(error),
                        sources_attempted=list(getattr(error, "attempts", ())))

    saved = [(source, reference_store.latest(db, source)) for source in ('petrolimex',)]
    saved = [(source, batch) for source, batch in saved if batch]
    if saved:
        source, batch = max(saved, key=lambda pair: (pair[1][0][0]['effective_date'],
            pair[1][0][0]['effective_time'].isoformat() if pair[1][0][0]['effective_time'] else '', pair[0]=='petrolimex'))
        metadata.update(persistence_status="stored", source_url=batch[0][0]['source_url'],
                        fetched_at=batch[0][0]['synced_at'])
        return finish(_response_from_saved(db, source, batch[0]))
    return finish(dict(source="database_fallback", source_message="Chưa có giá tham chiếu đã lưu",
                       effective_date=None, effective_time=None, items=[], **_stale_metadata(None)))


def _response_from_saved(db, source, batch):
    from app.services.fuel_crawler import CrawledFuelPrice
    return build_latest_from_live(db, [CrawledFuelPrice(r['fuel_id'], '', r['price'], None,
        r['effective_date'], r['effective_time'].strftime('%H:%M:%S') if r['effective_time'] else None) for r in batch], source)


def build_latest_from_live(db: Session, prices: list[CrawledFuelPrice], source: str) -> dict:
    """Compare only verified history from this same source and region."""
    day, clock = prices[0].effective_date, prices[0].effective_time
    current_key = (day, clock or '')
    history = reference_store.rows(db, source)
    items = []
    for live in sorted(prices, key=lambda item: SUPPORTED_FUEL_IDS.index(item.fuel_id)):
        earlier = [r for r in history if r['fuel_id']==live.fuel_id and
            (r['effective_date'], r['effective_time'].isoformat() if r['effective_time'] else '') < current_key]
        previous = earlier[-1] if earlier else None
        change = live.price - previous['price'] if previous else None
        items.append(dict(fuel_id=live.fuel_id, name=CANONICAL_FUEL_NAMES[live.fuel_id],
            current_price=_money_to_int(live.price), previous_price=_money_to_int(previous['price']) if previous else None,
            previous_effective_date=previous['effective_date'] if previous else None,
            change_vnd=_money_to_int(change) if change is not None else None,
            change_percent=round(float(change / previous['price'] * 100), 2) if previous else None,
            has_station_variation=False))
    return dict(source=source, source_message='Petrolimex Vùng 2' if source=='petrolimex' else 'PVOIL',
                effective_date=day, effective_time=clock, items=items, **_stale_metadata(day))


def _stale_metadata(day: date | None) -> dict:
    stale = day is None or (datetime.now(timezone(timedelta(hours=7))).date() - day).days > 10
    return dict(is_stale=stale, stale_message="Dữ liệu giá đã quá 10 ngày; vui lòng kiểm tra kỳ điều chỉnh mới nhất." if stale else None)


def build_latest_from_database(
    db: Session,
    *,
    source: str,
    effective_date_hint: date | None = None,
    effective_time: str | None = None,
    source_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    points = _load_aggregated_points(db)
    try:
        fuel_names = {
            fuel_id.strip(): name
            for fuel_id, name in db.execute(
                select(NhienLieu.nl_ma, NhienLieu.nl_ten).where(
                    NhienLieu.nl_ma.in_(SUPPORTED_FUEL_IDS)
                )
            ).all()
        }
    except SQLAlchemyError as error:
        raise FuelPriceDatabaseError("Unable to load fuel names") from error
    items: list[dict[str, Any]] = []
    latest_dates: list[date] = []
    for fuel_id in SUPPORTED_FUEL_IDS:
        history = points.get(fuel_id, [])
        if not history:
            continue
        current = history[-1]
        previous = history[-2] if len(history) > 1 else None
        current_price = current[1]
        previous_price = previous[1] if previous else None
        change = current_price - previous_price if previous_price is not None else None
        change_percent = None
        if previous_price is not None and previous_price > 0:
            change_percent = round(float(change / previous_price * Decimal("100")), 2)
        items.append(
            {
                "fuel_id": fuel_id,
                "name": CANONICAL_FUEL_NAMES.get(fuel_id)
                or (source_names or {}).get(fuel_id)
                or fuel_names.get(fuel_id, fuel_id),
                "current_price": _money_to_int(current_price),
                "previous_price": _money_to_int(previous_price) if previous_price is not None else None,
                "previous_effective_date": previous[0] if previous else None,
                "change_vnd": _money_to_int(change) if change is not None else None,
                "change_percent": change_percent,
                "has_station_variation": current[2],
            }
        )
        latest_dates.append(current[0])
    reported_date = max(latest_dates) if latest_dates else effective_date_hint
    reported_time = (
        effective_time
        if source in {"petrolimex", "pvoil"} and reported_date == effective_date_hint
        else None
    )
    source_messages = {
        "petrolimex": "Giá tham chiếu Petrolimex - Vùng 2",
        "pvoil": (
            "Petrolimex tạm thời không khả dụng; đang sử dụng giá tham chiếu "
            "từ PVOIL."
        ),
        "database_fallback": (
            "Nguồn giá trực tuyến tạm thời không khả dụng; đang sử dụng dữ liệu "
            "lưu gần nhất."
        ),
    }
    return {
        "source": source,
        "source_message": source_messages.get(
            source, source_messages["database_fallback"]
        ),
        "effective_date": reported_date,
        "effective_time": reported_time,
        **_stale_metadata(reported_date),
        "items": items,
    }


def get_fuel_price_history(
    db: Session, days: int, *, today: date | None = None, source: str = "petrolimex"
) -> dict[str, Any]:
    if not 1 <= days <= 365 or source not in reference_store.REGIONS:
        raise ValueError("Invalid reference history filter")
    end_date = today or datetime.now(timezone(timedelta(hours=7))).date()
    start_date = end_date - timedelta(days=days - 1)
    try:
        saved = reference_store.rows(db, source, start=start_date, end=end_date)
        return dict(days=days, source=source, storage_ready=reference_store.ready(db),
            sources=[name for name in reference_store.REGIONS if reference_store.rows(db,name)],
            series={fuel: [dict(date=r['effective_date'], effective_time=r['effective_time'].isoformat() if r['effective_time'] else None,
                price=_money_to_int(r['price']), source_url=r['source_url'], synced_at=r['synced_at'],
                has_station_variation=False) for r in saved if r['fuel_id']==fuel] for fuel in SUPPORTED_FUEL_IDS})
    except SQLAlchemyError as error:
        raise FuelPriceDatabaseError("Unable to read reference history") from error


def _load_aggregated_points(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[tuple[date, Decimal, bool]]]:
    statement = select(Gia.nl_ma, Gia.ngaygio, Gia.dongia).join(TramXang, Gia.tx_ma == TramXang.tx_ma).where(
        Gia.nl_ma.in_(SUPPORTED_FUEL_IDS), *_legacy_station_filter()
    )
    if start_date is not None:
        statement = statement.where(Gia.ngaygio >= start_date)
    if end_date is not None:
        statement = statement.where(Gia.ngaygio <= end_date)
    statement = statement.order_by(Gia.ngaygio.asc(), Gia.nl_ma.asc())
    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError as error:
        raise FuelPriceDatabaseError("Unable to read fuel-price history") from error
    grouped: dict[tuple[str, date], list[Decimal]] = defaultdict(list)
    for fuel_id, point_date, value in rows:
        grouped[(fuel_id.strip(), point_date)].append(Decimal(value))
    result: dict[str, list[tuple[date, Decimal, bool]]] = defaultdict(list)
    for (fuel_id, point_date), values in grouped.items():
        representative, variation = _representative_price(fuel_id, point_date, values)
        result[fuel_id].append((point_date, representative, variation))
    for fuel_points in result.values():
        fuel_points.sort(key=lambda point: point[0])
    return dict(result)


def _representative_price(
    fuel_id: str, point_date: date, values: list[Decimal]
) -> tuple[Decimal, bool]:
    counts = Counter(values)
    variation = len(counts) > 1
    # A mode-frequency tie deterministically selects the higher price; callers
    # still receive has_station_variation=True instead of a silent choice.
    selected = max(counts, key=lambda value: (counts[value], value))
    if variation:
        logger.warning(
            "Station price variation for %s on %s; mode selected from %s",
            fuel_id, point_date, sorted(counts.items()),
        )
    return selected, variation


def _money_to_int(value: Decimal) -> int:
    if value != value.to_integral_value():
        logger.warning("Fractional VND value rounded for API output: %s", value)
    return int(value.quantize(Decimal("1")))


def _validate_published_changes(
    items: list[dict[str, Any]], crawled: list[CrawledFuelPrice]
) -> None:
    published = {item.fuel_id: item.change_amount for item in crawled}
    for item in items:
        calculated = item["change_vnd"]
        expected = published.get(item["fuel_id"])
        if calculated is not None and expected is not None and Decimal(calculated) != expected:
            logger.warning(
                "Published change differs from DB historical comparison for %s",
                item["fuel_id"],
            )
