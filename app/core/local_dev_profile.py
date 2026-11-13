"""Restricted self-service profile, never an alias for owner/production approval."""
import ipaddress,json,os
from pathlib import Path
from app.core.development_deployment import fail

PROFILE='local-dev-self-service-v1'
DATASET=Path('proposals/phase58/LOCAL_DEV_DATA_PROFILE.json')
ROOT=Path(__file__).resolve().parents[2]

def loopback(value):
    if value=='localhost':return True
    try:
        address=ipaddress.ip_address(str(value))
        return address.is_loopback or bool(getattr(address,'ipv4_mapped',None) and address.ipv4_mapped.is_loopback)
    except ValueError:return False

def offline_environment(root=ROOT,setup=False):
    from dotenv import dotenv_values
    local={k:v for k,v in dotenv_values(root/'.env').items() if v is not None}
    for values in (local,os.environ):
        if any(values.get(key) for key in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGHOST','PGPORT','PGDATABASE','PGOPTIONS')):
            fail('PostgreSQL routing/session environment overrides present; use only the explicit local DATABASE_URL')
        for key in ('PETRO_ENVIRONMENT','APP_ENV','ENVIRONMENT','DEPLOYMENT_ENV'):
            value=values.get(key)
            if value and value.lower() not in ('local-development','development','dev','local','test','testing'):
                fail('init-dev rejects production/shared staging environment marker '+key)
        for key,value in values.items():
            if value and (key.startswith(('CASSO_','VIETQR_')) or key in ('BANK_WEBHOOK_SECRET','PAYMENT_WEBHOOK_SECRET')):
                fail('real bank/Casso configuration present: '+key+'; remove it from this test environment, not from production')
        if values.get('ENABLE_PAYMENT_SIMULATION','false').lower()!='false':fail('payment simulation endpoint must remain disabled')
    for key,expected in [('PETRO_ENVIRONMENT','local-development'),('PETRO_REAL_PAYMENTS_ENABLED','false')]:
        supplied=[values[key] for values in (local,os.environ) if key in values]
        if not supplied or any(value!=expected for value in supplied):fail('init-dev requires '+key+'='+expected+' in local configuration')
    if local.get('PETRO_LIFECYCLE_WORKER_ENABLED','false').lower()=='true' or (setup and os.environ.get('PETRO_LIFECYCLE_WORKER_ENABLED','false').lower()=='true'):
        fail('worker enable override present during local setup; no worker is started by init-dev')

def validate_url(url):
    if url.get_backend_name()!='postgresql' or not loopback(url.host) or url.database!='DB_TRAMXANG' or not isinstance(url.port,int) or not 1024<=url.port<=65535:
        fail('init-dev requires an explicit loopback PostgreSQL DB_TRAMXANG port (1024..65535)')
    if set(url.query)&{'host','hostaddr','port','dbname','service','servicefile'}:
        fail('init-dev rejects connection-routing overrides in DATABASE_URL query parameters')

def database_isolation(db):
    from sqlalchemy import text
    row=db.execute(text("SELECT host(inet_server_addr()),current_setting('listen_addresses'),pg_is_in_recovery(),current_user")).one()
    if not loopback(row[0]) or row[2]:fail('database is not a local primary development instance')
    if not row[1] or any(not loopback(item.strip()) for item in row[1].split(',')):
        fail('PostgreSQL listen_addresses is not loopback-only; configure a dedicated local test cluster, no server setting was changed')
    if db.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND left(nspname,3)<>'pg_'")):
        fail('unreviewed extra user schemas found; database purpose/provenance is not isolated')
    objects=list(db.execute(text("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('m','f','p','S')")))
    if any(kind!='S' for _,kind in objects) or {name for name,_ in objects}!=set(dataset()['sequences']):
        fail('unreviewed materialized/foreign/partitioned/sequence data found in public')
    addresses=list(db.execute(text("SELECT DISTINCT host(client_addr) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND client_addr IS NOT NULL")).scalars())
    if any(not loopback(address) for address in addresses):fail('remote/shared clients detected on the proposed local test database')
    return str(row[3])

def dataset(root=ROOT):
    from app.core.local_onboarding import release
    release(root)  # Includes the group-reviewed data profile, not a local trust file.
    value=json.loads((root/DATASET).read_text(encoding='utf-8'))
    if value.get('format_version')!=1 or value.get('kind')!='synthetic_catalog_only':fail('unapproved local development dataset profile')
    return value

def verify_test_data(db,observed,root=ROOT):
    from sqlalchemy import text
    from app.core.local_onboarding import value_sha
    active=db.scalar(text("SELECT count(*) FROM yeu_cau_do_xang WHERE ttxn_ma IN ('TTXN0001','TTXN0002','TTXN0003')"))
    processing=db.scalar(text("SELECT count(*) FROM giao_dich WHERE tt_ma='TT000003'"))
    holds=db.scalar(text("SELECT count(*) FROM giu_cho_nhien_lieu WHERE gc_trangthai='GIU_CHO'"))
    if active or processing or holds:fail('active requests/payments/holds found; init-dev cannot approve or expire them; use manual review')
    profile=dataset(root);tables=observed['row_counts']
    if len(tables)!=35 or set(profile['rows'])-set(tables):fail('unapproved local development dataset tables')
    expected={}
    for table,count in tables.items():
        rows=profile['rows'].get(table,[])
        if count!=len(rows):fail('unverified test-data provenance in '+table+'; use the released clean starter or prepare/approve, never delete operational data to pass')
        expected[table]=sorted(value_sha(row) for row in rows)
        actual=[json.loads(row) for row in db.execute(text('SELECT row_to_json(t)::text FROM public.'+db.bind.dialect.identifier_preparer.quote(table)+' t')).scalars()]
        if sorted(value_sha(row) for row in actual)!=expected[table]:fail('data differs from group-reviewed starter in '+table)
    for name,seed in profile['sequences'].items():
        value=db.execute(text('SELECT last_value,is_called FROM public.'+db.bind.dialect.identifier_preparer.quote(name))).one()
        if value[0]!=seed['start_value'] or value[1]!=seed['is_called']:fail('sequence history is not the reviewed clean starter; no sequence was reset')
    return {'dataset_id':profile['dataset_id'],'initial_data_sha256':value_sha({'tables':expected,'sequences':profile['sequences']})}

def validate_binding_profile(deployment,policy,root=ROOT):
    from app.core.local_onboarding import release,RELEASE_SHA,source_digest
    if policy.get('profile')!=PROFILE or deployment.get('approval_origin',{}).get('kind')!='local-development-init':fail('local development authorization kind mismatch')
    origin=deployment['approval_origin'];meta=policy.get('local_development',{})
    if origin.get('developer_confirmed') is not True or meta.get('developer_confirmed') is not True:fail('explicit local developer confirmation missing')
    if 'owner' in origin or 'owner_consent' in origin:fail('init-dev must not impersonate project-owner consent')
    if meta.get('release_sha256')!=RELEASE_SHA:fail('local development source release changed; preserve configuration and review the new release')
    spec=release(root)
    profile=dataset(root)
    from app.core.local_onboarding import value_sha,TOOLS
    schema=json.loads((root/'app/core/station_self_service_schema.json').read_text(encoding='utf-8'))['35']['schema']
    expected=value_sha({'tables':{table:sorted(value_sha(row) for row in profile['rows'].get(table,[])) for table in schema},'sequences':profile['sequences']})
    if meta.get('dataset_id')!=profile['dataset_id'] or meta.get('initial_data_sha256')!=expected:fail('local development seed provenance binding missing or unapproved')
    if set(meta.get('source_sha256',{}))!=set(spec['source_sha256'])|set(TOOLS):fail('local development source binding incomplete')
    for file,sha in meta.get('source_sha256',{}).items():
        if not (root/file).is_file() or source_digest(root/file)!=sha:fail('local development source changed: '+file)
    target=policy['target']
    if not target.get('hosts') or any(not loopback(host) for host in target['hosts']) or not isinstance(target.get('port'),int) or not 1024<=target['port']<=65535:
        fail('unapproved self-service local development target')
    offline_environment(root)

def runtime_guard(policy,db,root=ROOT):
    from app.core.local_onboarding import release,RELEASE_SHA,source_digest
    offline_environment(root);meta=policy.get('local_development',{})
    if meta.get('release_sha256')!=RELEASE_SHA:fail('local development release binding mismatch')
    spec=release(root)
    from app.core.local_onboarding import TOOLS
    if set(meta.get('source_sha256',{}))!=set(spec['source_sha256'])|set(TOOLS):fail('local development source binding incomplete')
    for file,sha in meta['source_sha256'].items():
        if source_digest(root/file)!=sha:fail('local development source changed: '+file)
    role=database_isolation(db)
    if role!=meta.get('database_role'):fail('local development database role changed')
