"""Explicit new-machine approval, reusing the existing policy/binding/guards.

Inspection is SELECT-only. A pending request cannot activate operations. Owner
approval and restricted developer self-service are separate authorization paths.
"""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib,ipaddress,json,os,secrets,sys
from app.core.development_deployment import LOCAL,digest,fail,read,private_path,validate_binding

ROOT=Path(__file__).resolve().parents[2]
RELEASE=Path('proposals/phase58/LOCAL_ONBOARDING_RELEASE.json')
RELEASE_SHA='2278b5ecd50605365f9529ad733c54038a3677b1e69df489d5a4d2ab553bf995'
TOOLS=('app/core/local_onboarding.py','scripts/onboard_petro_local.py','app/core/local_dev_profile.py')

def value_sha(value):return hashlib.sha256(json.dumps(value,default=str,sort_keys=True).encode()).hexdigest()
def source_digest(path):return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
def save(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,default=str);stream.write('\n')

def release(root=ROOT):
    if digest(root/RELEASE)!=RELEASE_SHA:fail('onboarding release reference SHA256 mismatch')
    result=read(root/RELEASE,'onboarding release reference')
    if result.get('format_version')!=1:fail('onboarding release reference format')
    for filename,expected in result['source_sha256'].items():
        if source_digest(root/filename)!=expected:fail('reviewed source changed: '+filename)
        if filename.endswith('.py'):compile((root/filename).read_text(encoding='utf-8'),filename,'exec')
    return result

def settings(root=ROOT):
    from dotenv import dotenv_values
    values={k:v for k,v in dotenv_values(root/'.env').items() if v is not None}
    for key in ('DATABASE_URL','SESSION_SECRET'):
        if key in os.environ and key in values and os.environ[key]!=values[key]:fail('conflicting environment variable '+key)
    for key in ('PETRO_OPERATIONAL_CONFIG','PETRO_OPERATIONAL_CONFIG_SHA256','PETRO_PROJECT_ROOT'):
        if os.environ.get(key) or values.get(key):fail('old operational override '+key+'; use a clean terminal/.env')
    if os.environ.get('PETRO_OPERATIONAL_STORAGE',values.get('PETRO_OPERATIONAL_STORAGE','postgresql'))!='postgresql':fail('PostgreSQL-only configuration required')
    if os.environ.get('PETRO_LIFECYCLE_WORKER_ENABLED',values.get('PETRO_LIFECYCLE_WORKER_ENABLED','false')).lower()=='true':fail('onboarding must not enable a worker')
    if os.environ.get('ENABLE_PAYMENT_SIMULATION',values.get('ENABLE_PAYMENT_SIMULATION','false')).lower()!='false':fail('payment simulation must be disabled')
    url=os.environ.get('DATABASE_URL') or values.get('DATABASE_URL')
    if not url:fail('DATABASE_URL missing; configure local .env, never pass credentials in argv')
    from sqlalchemy.engine import make_url
    parsed=make_url(url)
    try:local=parsed.host=='localhost' or ipaddress.ip_address(parsed.host).is_loopback
    except ValueError:local=False
    if parsed.get_backend_name()!='postgresql' or not local or parsed.database!='DB_TRAMXANG' or not parsed.port:
        fail('explicit local PostgreSQL DB_TRAMXANG host/port required')
    # Importing the inspected services must not activate a JSON fallback or load
    # a different dotenv database. No operational command is executed here.
    os.environ.update(DATABASE_URL=url,PETRO_OPERATIONAL_STORAGE='postgresql')
    return parsed,os.environ.get('SESSION_SECRET') or values.get('SESSION_SECRET'),{
        'dotenv_sha256':digest(root/'.env') if (root/'.env').exists() else None,
        'connection_sha256':value_sha([parsed.drivername,parsed.host,parsed.port,parsed.database,parsed.username]),
        'session_source_sha256':hashlib.sha256((os.environ.get('SESSION_SECRET') or values.get('SESSION_SECRET') or '').encode()).hexdigest()}

def catalog(connection):
    from sqlalchemy import text
    functions=[dict(r) for r in connection.execute(text("SELECT p.oid::regprocedure::text AS identity,pg_get_functiondef(p.oid) AS definition FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p','w') ORDER BY 1")).mappings()]
    triggers=[dict(r) for r in connection.execute(text("SELECT c.relname AS table_name,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,false) AS definition FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2")).mappings()]
    views=[dict(r) for r in connection.execute(text("SELECT viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname")).mappings()]
    return {'functions':functions,'triggers':triggers,'views':views}

def catalog_hashes(value):
    return {kind:{(row.get('identity') or row.get('viewname') or row['table_name']+'.'+row['tgname']):value_sha(row) for row in rows} for kind,rows in value.items()}

def probe(db,spec):
    """Also usable by isolated PG tests. Does not approve any host or port."""
    from sqlalchemy import text,select
    from app.core.published_price_schema import validate,canonical,CONTRACT
    from app.services.request_lifecycle import guard_schema
    from app.core.workflow_status import validate_catalog
    from app.services.operational_service import operation_schema_signature,invariant
    from app.models import BonChua
    from proposals.phase57e1.prepare import snapshot
    identity=dict(db.execute(text("SELECT current_database() AS database,inet_server_port() AS port,current_setting('data_directory') AS data_directory,system_identifier::text,current_user AS database_role,current_setting('server_version_num')::int AS server_version FROM pg_control_system()")).mappings().one())
    if identity['server_version']//10000!=spec['postgresql_major']:fail('PostgreSQL major version not reviewed')
    guard_schema(db);validate_catalog(db)
    if validate(db)!=35:fail('current 35-table schema required; migrations are separate owner-approved work')
    state=snapshot(db.connection())
    current=json.loads(CONTRACT.with_name('station_self_service_schema.json').read_text(encoding='utf-8'))
    if canonical(state['schema'],current)!=current['35']['schema']:fail('current self-service/review/reference-price migrations missing; no migration was run')
    ddl=catalog(db.connection())
    if catalog_hashes(ddl)!=spec['catalog_sha256']:fail('public function/trigger/view catalog differs from reviewed release')
    for tank in db.scalars(select(BonChua)):invariant(db,tank)
    privileges={'select_all_public':bool(db.scalar(text("SELECT bool_and(has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'SELECT')) FROM pg_tables WHERE schemaname='public'")))}
    for table,required in {'yeu_cau_do_xang':['INSERT','UPDATE'],'chitiet_yeucau':['INSERT','UPDATE'],
        'bon_chua':['INSERT','UPDATE'],'tru_bom':['INSERT','UPDATE'],'tru_bom_nhien_lieu':['INSERT'],
        'giu_cho_nhien_lieu':['INSERT','UPDATE'],'bien_dong_kho':['INSERT'],'giao_dich':['INSERT','UPDATE'],
        'chi_tiet_giao_dich':['INSERT'],'thoi_diem':['INSERT'],'gia_tham_chieu':['INSERT']}.items():
        for privilege in required:
            privileges[table+'.'+privilege]=bool(db.scalar(text('SELECT has_table_privilege(current_user,:table,:privilege)'),{'table':'public.'+table,'privilege':privilege}))
    if not all(privileges.values()):fail('runtime role privileges insufficient; no GRANT is performed')
    lease=int(db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted AND objsubid=1 AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND classid=((hashtextextended('petro-request-expiry-worker',0)>>32)&4294967295)::oid AND objid=(hashtextextended('petro-request-expiry-worker',0)&4294967295)::oid")))
    transactions=int(db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend' AND xact_start IS NOT NULL")))
    if lease:fail('expiry lease already held; stop/reconcile the existing supervised instance before onboarding')
    if transactions:fail('other open transactions; establish a quiet window, never terminate sessions automatically')
    preserved=list(db.execute(text('SELECT yc_ma FROM yeu_cau_do_xang ORDER BY yc_ma')).scalars())
    active=[dict(r) for r in db.execute(text("SELECT yc_ma,ttxn_ma,yc_het_han_luc FROM yeu_cau_do_xang WHERE ttxn_ma IN ('TTXN0001','TTXN0002','TTXN0003') ORDER BY yc_ma")).mappings()]
    return {'identity':identity,'schema_sha256':state['schema_digest'],'data_fingerprints':state['table_fingerprints'],
        'row_counts':state['row_counts'],'table_count':35,'catalog_sha256':catalog_hashes(ddl),
        'operation_schema_sha256':operation_schema_signature(db),'privileges':privileges,
        'singleton_leases':lease,'other_open_transactions':transactions,'preserved_request_ids':preserved,
        'imported_active_requests':active,'runtime_health':'NOT_STARTED_NOT_VERIFIED'},ddl

def inspect_machine(root=ROOT,local_dev=False):
    spec=release(root);url,session,environment=settings(root)
    if local_dev:
        from app.core.local_dev_profile import validate_url
        validate_url(url)
    if url.port!=5432 and not (local_dev and isinstance(url.port,int) and 1024<=url.port<=65535):fail('development onboarding requires port 5432; isolated probes cannot receive local approval')
    if os.name!='nt':fail('new-machine development approval requires the reviewed Windows supervisor')
    if sys.version_info<(3,10):fail('Python 3.10+ required by the reviewed application/worker')
    import subprocess
    command="@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"
    processes=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    rows=json.loads(processes.stdout or '[]');rows=rows if isinstance(rows,list) else ([rows] if rows else [])
    scoped=[r['ProcessId'] for r in rows if r['ProcessId']!=os.getpid() and str(root.resolve()).casefold() in (r.get('CommandLine') or '').casefold() and any(s in (r.get('CommandLine') or '') for s in ('worker_supervisor','manage_expiry58b','expire_fuel_requests'))]
    if scoped:fail('PETRO supervisor/worker process exists for this project; reconcile it before onboarding')
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import Session
    engine=create_engine(url,hide_parameters=True,connect_args={'connect_timeout':10})
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'));db.execute(text("SET LOCAL statement_timeout='30s'"))
            try:result,ddl=probe(db,spec)
            except RuntimeError as error:
                if str(error).startswith('PETRO configuration gate failed:'):raise
                fail('schema/catalog validation failed: '+str(error)+'; use a compatible reviewed schema, no migration was run')
            except Exception as error:
                from fastapi import HTTPException
                if isinstance(error,HTTPException):fail('lifecycle/catalog/inventory validation failed: '+str(error.detail)+'; manual inspection required')
                raise
            db.rollback()
    finally:engine.dispose()
    if result['identity']['database']!=url.database or result['identity']['port']!=url.port:fail('connected target differs from DATABASE_URL')
    result.update(host=url.host,environment=environment,
        source_sha256={name:source_digest(root/name) for name in (*spec['source_sha256'],*TOOLS)},release_sha256=RELEASE_SHA,
        supervisor_processes=[],platform='Windows')
    return result,ddl,session

def prepare(destination,root=ROOT):
    destination=private_path(destination,'pending onboarding request',root)
    if destination.exists():fail('pending request exists; choose a new filename, no overwrite')
    observed,ddl,_=inspect_machine(root)
    from proposals.phase57e1.prepare import restrict
    destination.parent.mkdir(parents=True,exist_ok=True);restrict(destination.parent)
    request={'format_version':1,'status':'AWAITING_OWNER_REVIEW','project_root':str(root.resolve()),
             'checked_at':datetime.now(timezone.utc).isoformat(),'observed':observed,
             'database_writes':False,'migration_executed':False,'worker_started':False}
    save(destination,request)
    save(destination.with_suffix('.catalog.private.json'),ddl)
    return digest(destination)

def policy_for_approved_target(target,observed,ddl):
    """Serialize the existing policy format; callers must authorize their target.
    This pure function does not install a policy or a local approval.
    """
    if catalog_hashes(ddl)!=observed['catalog_sha256']:fail('review catalog sidecar drift')
    return {'schema_version':1,'activation_authorized':True,'legacy_import_rows':0,'lifecycle_enabled':True,
        'target':target,'preserved_request_ids':observed['preserved_request_ids'],
        'operation_schema_sha256':observed['operation_schema_sha256'],
        'trigger_sha256':{r['tgname']:hashlib.sha256(r['definition'].encode()).hexdigest() for r in ddl['triggers'] if r['tgname'] in ('trg_tb_scope','trg_gc_scope','trg_bd_scope','trg_bd_immutable','trg_tb_immutable','trg_bc_immutable','trg_gc_immutable')},
        'function_sha256':{r['identity'].split('(')[0].split('.')[-1]:hashlib.sha256(r['definition'].encode()).hexdigest() for r in ddl['functions'] if r['identity'].split('(')[0].split('.')[-1] in ('phase57_scope_guard','phase57_immutable_guard')}}

def approve(request_path,reviewed_sha,expected_identifier,expected_directory,owner,reference,confirmed,root=ROOT):
    if not confirmed or not owner.strip() or not reference.strip():fail('explicit project-owner approval and reference required')
    request_path=private_path(request_path,'reviewed onboarding request',root)
    if digest(request_path)!=reviewed_sha:fail('reviewed onboarding request SHA256 mismatch')
    request=read(request_path,'reviewed onboarding request')
    if request.get('format_version')!=1 or request.get('status')!='AWAITING_OWNER_REVIEW' or request.get('project_root')!=str(root.resolve()):fail('onboarding request scope/status mismatch')
    if datetime.now(timezone.utc)-datetime.fromisoformat(request['checked_at'])>timedelta(hours=24):fail('onboarding review older than 24h; prepare a fresh request')
    observed=request['observed'];identity=observed['identity']
    if not Path(expected_directory).is_absolute():fail('owner expected data directory must be absolute')
    if identity['system_identifier']!=expected_identifier or Path(identity['data_directory']).resolve()!=Path(expected_directory).resolve():fail('owner expected identity/data directory differs from reviewed request')
    destination=root/LOCAL
    if destination.exists():fail('existing local approval preserved; no overwrite permitted')
    current,_,session=inspect_machine(root)
    if value_sha(current)!=value_sha(observed):fail('database/configuration/release drift since owner review; prepare again')
    ddl=read(request_path.with_suffix('.catalog.private.json'),'reviewed public catalog')
    origin={'kind':'new-machine-owner-approval','owner':owner,'reference':reference,
        'reviewed_request_sha256':reviewed_sha,'approved_at':datetime.now(timezone.utc).isoformat(),
        'migration_executed':False,'schema_verified':35,'worker_health':'NOT_STARTED_NOT_VERIFIED'}
    return install_bundle(observed,ddl,session,reviewed_sha,origin,root)

def install_bundle(observed,ddl,session,bundle_id,origin,root=ROOT,local_dev=None):
    """Shared private artifact/UoW verification, after a distinct consent gate."""
    destination=root/LOCAL
    if destination.exists():fail('existing local approval preserved; no overwrite permitted')
    shared=read(root/'proposals/phase58/DEVELOPMENT_DEPLOYMENT.json','shared release evidence')
    if shared.get('migration_verified') is not True or shared.get('promotion_verified') is not True:fail('shared release evidence not approved')
    folder=private_path('.runtime/development/onboarding/'+bundle_id,'new private approval bundle',root)
    if folder.exists():fail('approval bundle exists; preserve it for review, no overwrite')
    from proposals.phase57e1.prepare import restrict
    folder.mkdir(parents=True);restrict(folder)
    # Activation is issued only after the caller's distinct consent gate and
    # fresh checks; self-service never manufactures project-owner consent.
    target={'hosts':[observed['host']],'database':'DB_TRAMXANG','port':observed['identity']['port'] if local_dev else 5432,
        'system_identifier':observed['identity']['system_identifier'],'data_directory':str(Path(observed['identity']['data_directory']).resolve())}
    # Bind the displayed catalog to the inspected trusted release, not to an
    # arbitrary edited sidecar or the newly connected target.
    policy=policy_for_approved_target(target,observed,ddl)
    if local_dev:
        from app.core.local_dev_profile import PROFILE
        policy.update(profile=PROFILE,local_development=local_dev)
    save(folder/'policy.private.json',policy)
    with (folder/'session_secret.private').open('x',encoding='utf-8') as stream:stream.write(session or secrets.token_hex(32))
    work=folder/'supervisor';work.mkdir()
    config={'mode':'development','source_root':str(root.resolve()),'work':str(work),'policy':str(folder/'policy.private.json'),
        'policy_sha256':digest(folder/'policy.private.json'),'worker_sha256':digest(root/'scripts/expire_fuel_requests.py'),
        'session_secret':str(folder/'session_secret.private')}
    save(folder/'supervisor.private.json',config)
    local={'format_version':1,'supervisor_config':str((folder/'supervisor.private.json').relative_to(root)),
        'supervisor_sha256':digest(folder/'supervisor.private.json'),'policy_sha256':config['policy_sha256'],
        'supervisor_source_sha256':digest(root/'proposals/phase58/worker_supervisor.py'),'approved_target':target,
        'approval_origin':origin}
    validate_binding({**shared,**local},root)
    # Verify the actual existing UoW/target/trigger/schema guard before installing
    # the pointer. This configuration is never used for a business command.
    os.environ.update(PETRO_PROJECT_ROOT=str(root),PETRO_OPERATIONAL_CONFIG=config['policy'],PETRO_OPERATIONAL_CONFIG_SHA256=config['policy_sha256'])
    from app.core.operational_mode import configured_target
    configured_target.cache_clear()
    from app.services.operational_service import guard
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import Session
    engine=create_engine(os.environ['DATABASE_URL'],hide_parameters=True)
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'));guard(db)
            if local_dev:
                from app.core.local_dev_profile import verify_test_data
                if verify_test_data(db,observed,root)['initial_data_sha256']!=local_dev['initial_data_sha256']:fail('starter data drift before binding installation')
            db.rollback()
    finally:engine.dispose()
    destination.parent.mkdir(parents=True,exist_ok=True);restrict(destination.parent)
    save(destination,local)  # exclusive create; pointer is always the last write
    installed_sha=digest(destination)
    try:
        from app.core.development_deployment import load_deployment
        loaded=load_deployment(root)
        if root.resolve()==ROOT.resolve():
            from proposals.phase58.worker_supervisor import load
            load(root/loaded['supervisor_config'])  # validation only; never run/child
    except Exception:
        if destination.is_file() and digest(destination)==installed_sha:destination.unlink()
        raise
    return local

def reuse_existing(root=ROOT):
    """No conversion, overwrite, secret regeneration, or worker launch."""
    from app.core.development_deployment import load_deployment
    loaded=load_deployment(root)
    # Real CLI always uses the source-derived root, including a test source copy.
    if root.resolve()!=ROOT.resolve():fail('existing configuration must be checked by its own project CLI')
    from app.core.development_startup import configure_development
    configure_development()
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import Session
    from app.services.operational_service import guard
    from app.core.operational_mode import configured_target
    configured_target.cache_clear()
    engine=create_engine(os.environ['DATABASE_URL'],hide_parameters=True)
    try:
        with Session(engine) as db:db.execute(text('SET TRANSACTION READ ONLY'));guard(db);db.rollback()
    finally:engine.dispose()
    return {'status':'EXISTING_UNCHANGED','kind':loaded.get('approval_origin',{}).get('kind','owner-approved-legacy')}

def init_dev(confirm,root=ROOT):
    """Self-service development authorization, not project-owner consent."""
    if (root/LOCAL).exists():return reuse_existing(root)
    from app.core.local_dev_profile import offline_environment,validate_url,database_isolation,verify_test_data
    offline_environment(root,setup=True)
    observed,ddl,session=inspect_machine(root,local_dev=True)
    url,_,_=settings(root);validate_url(url)
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import Session
    engine=create_engine(url,hide_parameters=True,connect_args={'connect_timeout':10})
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            role=database_isolation(db);provenance=verify_test_data(db,observed,root);db.rollback()
    finally:engine.dispose()
    if not confirm(observed):fail('local development confirmation declined; nothing was installed')
    current,current_ddl,current_session=inspect_machine(root,local_dev=True)
    if value_sha(current)!=value_sha(observed):fail('database/config/source drift during local confirmation; nothing was installed')
    meta={**provenance,'developer_confirmed':True,'database_role':role,'release_sha256':RELEASE_SHA,'source_sha256':observed['source_sha256']}
    origin={'kind':'local-development-init','developer_confirmed':True,'confirmed_at':datetime.now(timezone.utc).isoformat(),
        'dataset_id':provenance['dataset_id'],'release_sha256':RELEASE_SHA,'migration_executed':False,
        'schema_verified':35,'worker_health':'NOT_STARTED_NOT_VERIFIED'}
    install_bundle(current,current_ddl,current_session,'init-dev-'+value_sha(origin),origin,root,meta)
    return {'status':'INITIALIZED_LOCAL_DEVELOPMENT','kind':origin['kind']}
