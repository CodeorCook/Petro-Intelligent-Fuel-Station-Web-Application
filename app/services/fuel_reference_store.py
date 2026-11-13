"""Source-separated reference history. Never writes GIA or creates schema.

Installation is explicit and gated. Writes require the target/policy guard and
the pinned 35-table published-price schema contract; no startup DDL is allowed.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from app.services.operational_service import guard

FUELS = ('NL000001', 'NL000002', 'NL000003')
TABLE = 'gia_tham_chieu'
LOCK_KEY = 706381043
REGIONS = {'petrolimex': '2', 'pvoil': 'national'}


class ReferenceStorageError(Exception):
    pass


def ready(db):
    ins = inspect(db.connection())
    if not ins.has_table(TABLE, schema='public'):
        return False
    cols = {c['name'] for c in ins.get_columns(TABLE, schema='public')}
    return cols == {'id', 'source', 'region', 'fuel_id', 'price', 'effective_date',
                    'effective_time', 'source_url', 'synced_at'} and any(
        c['name'] == 'uq_reference_period_fuel' and c['column_names'] ==
        ['source', 'region', 'effective_date', 'effective_time', 'fuel_id']
        for c in ins.get_unique_constraints(TABLE, schema='public'))


def persist(db, result):
    """All three fuels or none; exact replay succeeds, conflicting replay fails."""
    if not ready(db):
        raise ReferenceStorageError('Reference storage migration is not installed')
    try:
        guard(db)  # Never bypass target, policy, schema, lifecycle or worker guards.
    except HTTPException as error:
        raise ReferenceStorageError('Current operational policy does not permit the reference schema') from error
    if db.new or db.dirty or db.deleted:
        raise ReferenceStorageError('Refusing to commit unrelated pending changes')
    source = result.provider_name
    prices = result.prices
    host = urlparse(result.source_url or '')
    valid_hosts = {'petrolimex': {'www.petrolimex.com.vn', 'w.petrolimex.com.vn'},
                   'pvoil': {'www.pvoil.com.vn', 'pvoil.com.vn'}}
    if source not in REGIONS or host.scheme != 'https' or host.netloc not in valid_hosts[source]:
        raise ReferenceStorageError('Verified official source URL is required')
    if len(prices) != 3 or {p.fuel_id for p in prices} != set(FUELS):
        raise ReferenceStorageError('Exactly three canonical fuels are required')
    periods = {(p.effective_date, p.effective_time) for p in prices}
    if len(periods) != 1:
        raise ReferenceStorageError('Mixed effective periods')
    day, clock = next(iter(periods))
    if not isinstance(day, date) or day > datetime.now(timezone(timedelta(hours=7))).date():
        raise ReferenceStorageError('Invalid effective date')
    try:
        clock = time.fromisoformat(clock) if clock else None
    except ValueError as error:
        raise ReferenceStorageError('Invalid effective time') from error
    if clock and clock.tzinfo:
        raise ReferenceStorageError('Expected official local time')
    if clock and datetime.combine(day, clock, tzinfo=timezone(timedelta(hours=7))) > datetime.now(timezone.utc):
        raise ReferenceStorageError('Future effective period')
    if not result.fetched_at or result.fetched_at.tzinfo is None:
        raise ReferenceStorageError('Verified synchronization timestamp is required')
    params = dict(source=source, region=REGIONS[source], day=day, clock=clock)
    try:
        with db.begin_nested():
            db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_KEY})
            existing = {r.fuel_id: r for r in db.execute(text(
                'SELECT fuel_id,price FROM public.gia_tham_chieu WHERE source=:source AND region=:region '
                'AND effective_date=:day AND effective_time IS NOT DISTINCT FROM CAST(:clock AS time)'), params)}
            if existing and set(existing) != set(FUELS):
                raise ReferenceStorageError('Incomplete stored period; manual reconciliation required')
            for item in prices:
                value = Decimal(item.price)
                if not value.is_finite() or value <= 0 or value >= 1000000000 or value != value.to_integral_value():
                    raise ReferenceStorageError('Invalid whole-VND reference price')
                if item.fuel_id in existing and existing[item.fuel_id].price != value:
                    raise ReferenceStorageError('Conflicting verified period; historical values preserved')
            if not existing:
                for item in prices:
                    db.execute(text('INSERT INTO public.gia_tham_chieu '
                        '(source,region,fuel_id,price,effective_date,effective_time,source_url,synced_at) '
                        'VALUES (:source,:region,:fuel,:price,:day,:clock,:url,:synced)'),
                        {**params, 'fuel': item.fuel_id, 'price': item.price,
                         'url': result.source_url, 'synced': result.fetched_at})
        db.commit()
        return 'unchanged' if existing else 'persisted'
    except (SQLAlchemyError, ReferenceStorageError) as error:
        db.rollback()
        if isinstance(error, ReferenceStorageError):
            raise
        raise ReferenceStorageError('Reference transaction failed; rolled back') from error


def rows(db, source, *, start=None, end=None):
    if source not in REGIONS:
        raise ReferenceStorageError('Unknown reference source')
    if not ready(db):
        import logging
        logging.getLogger(__name__).warning('Published price history unavailable: reference schema not installed or invalid')
        return []
    filters = ['source=:source', 'region=:region']
    params = dict(source=source, region=REGIONS[source])
    if start:
        filters.append('effective_date>=:start'); params['start'] = start
    if end:
        filters.append('effective_date<=:end'); params['end'] = end
    return list(db.execute(text('SELECT source,region,fuel_id,price,effective_date,effective_time,source_url,synced_at '
        'FROM public.gia_tham_chieu WHERE ' + ' AND '.join(filters) +
        ' ORDER BY effective_date,effective_time NULLS FIRST,fuel_id'), params).mappings())


def latest(db, source):
    values = rows(db, source)
    if not values:
        return None
    last = values[-1]
    period = (last['effective_date'], last['effective_time'])
    current = [r for r in values if (r['effective_date'], r['effective_time']) == period]
    if len(current) != 3 or {r['fuel_id'] for r in current} != set(FUELS):
        raise ReferenceStorageError('Incomplete stored reference period')
    return current, values
