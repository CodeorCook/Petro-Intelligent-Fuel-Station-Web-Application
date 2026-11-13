from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models import Gia, NhienLieu, TramXang, TxDv
from app.services.routing_service import haversine_distance
from app.services.station_visibility import public_station_query
from app.services.station_discovery import filter_station_query


class MapStationError(Exception):
    pass


def list_map_stations(
    db: Session,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    search: str | None = None,
    fuel_type: str | None = None,
    service_name: str | None = None,
    radius_km: float | None = None,
    amenity_ids: list[str] | None = None,
    amenity_match: str = 'all',
) -> list[dict[str, Any]]:
    try:
        query = filter_station_query(db, _station_query(), amenity_ids=amenity_ids or [],
            amenity_match=amenity_match, fuel_type=fuel_type, search=search, service_name=service_name)
        stations = db.scalars(query.order_by(TramXang.tx_ma)).unique().all()
    except SQLAlchemyError as error:
        raise MapStationError("Unable to load station display data") from error
    results = []
    for station in stations:
        item = _format_station(station, latitude, longitude)
        if radius_km is not None:
            distance = item["straight_line_distance_km"]
            if distance is None or distance > radius_km:
                continue
        results.append(item)
    return results


def get_map_station(
    db: Session,
    station_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any] | None:
    try:
        station = db.scalars(
            _station_query().where(TramXang.tx_ma == station_id)
        ).unique().first()
    except SQLAlchemyError as error:
        raise MapStationError("Unable to load station display data") from error
    return _format_station(station, latitude, longitude) if station else None


def _station_query():
    return public_station_query().options(
        selectinload(TramXang.bang_gia)
        .selectinload(Gia.nhien_lieu)
        .selectinload(NhienLieu.don_vi_tinh),
        selectinload(TramXang.tx_dv).selectinload(TxDv.dich_vu),
        selectinload(TramXang.danh_gia),
    )


def _format_station(
    station: TramXang,
    latitude: float | None,
    longitude: float | None,
) -> dict[str, Any]:
    station_lat = float(station.tx_vido)
    station_lon = float(station.tx_kinhdo)
    straight_distance = None
    if latitude is not None and longitude is not None:
        straight_distance = haversine_distance(latitude, longitude, station_lat, station_lon)
    prices_by_fuel: dict[str, Gia] = {}
    for price in station.bang_gia:
        current = prices_by_fuel.get(price.nl_ma)
        if current is None or price.ngaygio > current.ngaygio:
            prices_by_fuel[price.nl_ma] = price
    fuels = [
        {
            "name": price.nhien_lieu.nl_ten if price.nhien_lieu else None,
            "code": (price.nhien_lieu.nl_ma if price.nhien_lieu else price.nl_ma).strip(),
            "price": float(price.dongia),
            "unit": (
                price.nhien_lieu.don_vi_tinh.dvt_ten
                if price.nhien_lieu and price.nhien_lieu.don_vi_tinh
                else None
            ),
            "price_date": price.ngaygio.isoformat(),
        }
        for price in prices_by_fuel.values()
    ]
    from app.core.fuel_order import ordered_fuels
    fuels = ordered_fuels(fuels, lambda f: f['code'])
    services = sorted(
        link.dich_vu.dv_ten for link in station.tx_dv if link.dich_vu is not None
    )
    ratings = [review.dg_mucdo for review in station.danh_gia]
    brand = _infer_brand(station.tx_ten)
    return {
        "tx_ma": station.tx_ma.strip(),
        "tx_ten": station.tx_ten,
        "tx_diachi": station.tx_diachi,
        "lat": station_lat,
        "lng": station_lon,
        "straight_line_distance_km": straight_distance,
        "rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "review_count": len(ratings),
        "brand": brand["name"],
        "brand_color": brand["color"],
        "brand_inferred": brand["name"] is not None,
        "fuels": fuels,
        "services": services,
        "open_hours": None,
        "is_open": None,
        "car_friendly": None,
        "demo_data": False,
    }


def _infer_brand(name: str) -> dict[str, str | None]:
    normalized = name.lower()
    known = (
        ("petrolimex", "Petrolimex", "#0055a5"),
        ("pvoil", "PVOIL", "#df1c24"),
        ("mipec", "MIPEC", "#1b5e20"),
        ("quân đội", "MIPEC", "#1b5e20"),
    )
    for token, brand, color in known:
        if token in normalized:
            return {"name": brand, "color": color}
    return {"name": None, "color": None}


def _matches_search(item: dict[str, Any], query: str) -> bool:
    needle = query.strip().lower()
    return any(
        needle in str(value or "").lower()
        for value in (item["tx_ten"], item["tx_diachi"], item["brand"])
    )


def _matches_fuel(item: dict[str, Any], fuel_type: str) -> bool:
    needle = fuel_type.strip().lower()
    return any(
        needle in str(fuel.get("name") or "").lower()
        or needle in str(fuel.get("code") or "").lower()
        for fuel in item["fuels"]
    )


def _matches_service(item: dict[str, Any], service_name: str) -> bool:
    needle = service_name.strip().lower()
    return any(needle in service.lower() for service in item["services"])
