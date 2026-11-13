"""Pinned additive schema contract; legacy 34 and approved 35 only."""
import hashlib
import json
from pathlib import Path
from sqlalchemy import inspect, text

CONTRACT = Path(__file__).with_name('published_price_schema.json')
CONTRACT_SHA = '0747a0a98051c1e8495182674969fcd5ad4311c58eeb47e4c49666aa62b61d9e'
VERSION = 'PETRO_SCHEMA_35_REFERENCE_V1'


def contract():
    raw = CONTRACT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTRACT_SHA:
        raise RuntimeError('Published-price schema contract integrity failure')
    return json.loads(raw)


def canonical(schema, spec):
    value = json.loads(json.dumps(schema, default=str))
    # SQLAlchemy omits the current public schema when reflecting without an
    # explicit schema argument. Live validation always reflects public explicitly.
    for table in value.values():
        for fk in table.get('fk', []):
            if fk['referred_schema'] is None:
                fk['referred_schema']='public'
        for idx in table.get('indexes', []):
            if 'include_columns' not in idx:
                idx['include_columns'] = []
    for pair in spec['cast_pairs']:
        for check in value.get(pair['table'], {}).get('checks', []):
            if check['name']==pair['name'] and check['sqltext']==pair['restored']:
                check['sqltext']=pair['source']
    return value


def validate_shape(schema, flags, marker, spec=None):
    if spec is None:
        original = contract()
        extra = CONTRACT.with_name('station_self_service_schema.json').read_bytes()
        if hashlib.sha256(extra).hexdigest() != '912701eb82711d822d727165a989ba8e10059afd55c29d168e40c413ad5949e1':
            raise RuntimeError('Self-service schema contract integrity failure')
        candidate = json.loads(extra)
        count = len(schema)
        use_original = count in (34,35) and canonical(schema,original)==original[str(count)]['schema'] and flags==original[str(count)]['flags']
        spec = original if use_original else candidate
    count = len(schema)
    if count not in (34,35):
        raise RuntimeError('Unapproved public table count')
    expected = spec[str(count)]
    if canonical(schema,spec)!=expected['schema'] or flags!=expected['flags']:
        raise RuntimeError('Unapproved table/column/constraint/index schema')
    if count==35 and marker!=VERSION:
        raise RuntimeError('Unapproved published-price schema version')
    return count


def validate(db):
    if db.scalar(text("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND (NOT i.indisvalid OR NOT i.indisready)")):
        raise RuntimeError('Invalid or incomplete public index')
    ins=inspect(db.connection())
    schema={name:dict(columns=ins.get_columns(name,schema='public'),pk=ins.get_pk_constraint(name,schema='public'),
        fk=ins.get_foreign_keys(name,schema='public'),indexes=ins.get_indexes(name,schema='public'),
        checks=ins.get_check_constraints(name,schema='public'),unique=ins.get_unique_constraints(name,schema='public'))
        for name in sorted(ins.get_table_names(schema='public'))}
    flags=[dict(r) for r in db.execute(text("SELECT c.relname AS table_name,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,k.connoinherit,k.confmatchtype,k.confupdtype,k.confdeltype FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND k.contype != 'n' ORDER BY 1,2")).mappings()]
    marker=ins.get_table_comment('gia_tham_chieu',schema='public')['text'] if 'gia_tham_chieu' in schema else None
    return validate_shape(schema,flags,marker)
