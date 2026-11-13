"""Shared, parameterized public discovery constraints; EXISTS avoids duplicate rows."""
from typing import Literal
from fastapi import HTTPException
from sqlalchemy import exists, select, or_, func
from app.models import DichVu, TxDv, TramXang, Gia, NhienLieu

# Compatibility for existing clients sending the five original seed labels.
# Assignment/filter identity stays dv_ma; public display remains database dv_ten.
LEGACY_SERVICE_IDS = {
    'Thanh toan QR': 'DV000001', 'Nha ve sinh': 'DV000002',
    'Cua hang tien loi': 'DV000003', 'Bom lop / kiem tra lop': 'DV000004',
    'Xuat hoa don dien tu': 'DV000005',
}


def filter_station_query(db, query, *, amenity_ids=(), amenity_match: Literal['all', 'any'] = 'all',
                         fuel_type=None, search=None, service_name=None):
    ids = sorted(set(amenity_ids))
    if amenity_match not in ('all', 'any'):
        raise HTTPException(422, 'Cách lọc tiện ích phải là all hoặc any')
    if len(ids) > 50 or any(not isinstance(i, str) or not 1 <= len(i) <= 8 for i in ids):
        raise HTTPException(422, 'Mã tiện ích không hợp lệ')
    if ids:
        known = set(db.scalars(select(DichVu.dv_ma).where(DichVu.dv_ma.in_(ids))))
        if set(ids) - known:
            raise HTTPException(422, 'Mã tiện ích không tồn tại: ' + ', '.join(sorted(set(ids) - known)))
        if amenity_match == 'all':
            for service_id in ids:
                query = query.where(exists(select(TxDv.tx_ma).where(
                    TxDv.tx_ma == TramXang.tx_ma, TxDv.dv_ma == service_id)))
        else:
            query = query.where(exists(select(TxDv.tx_ma).where(
                TxDv.tx_ma == TramXang.tx_ma, TxDv.dv_ma.in_(ids))))
    if service_name:
        # Preserve case-insensitive legacy seed substring searches after adding
        # accents, while still including custom services matching their DB name.
        legacy_ids = [code for label,code in LEGACY_SERVICE_IDS.items()
                      if service_name.casefold() in label.casefold()]
        name_match = DichVu.dv_ten.icontains(service_name, autoescape=True)
        if legacy_ids: name_match = or_(name_match, DichVu.dv_ma.in_(legacy_ids))
        query = query.where(exists(select(TxDv.tx_ma).join(DichVu).where(
            TxDv.tx_ma == TramXang.tx_ma, name_match)))
    if fuel_type:
        alias = {'RON95': 'NL000001', 'E5': 'NL000002', 'DIESEL': 'NL000003'}
        fuel = alias.get(fuel_type.upper(), fuel_type)
        query = query.where(exists(select(Gia.tx_ma).join(NhienLieu).where(
            Gia.tx_ma == TramXang.tx_ma, or_(Gia.nl_ma == fuel,
            func.replace(func.lower(NhienLieu.nl_ten), ' ', '').contains(fuel.lower().replace(' ', ''), autoescape=True)))))
    if search:
        needle = search.strip()
        query = query.where(or_(TramXang.tx_ten.icontains(needle, autoescape=True),
                               TramXang.tx_diachi.icontains(needle, autoescape=True)))
    return query
