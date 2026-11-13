"""Standalone supervised worker; explicitly enabled only after lifecycle cutover GO."""
from pathlib import Path
import sys,os,time,json,signal,argparse
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--interval',type=float,default=2)
args=parser.parse_args()
if not 0.5<=args.interval<=30:raise SystemExit('Invalid interval')
if os.getenv('PETRO_LIFECYCLE_WORKER_ENABLED')!='true':raise SystemExit('Worker not explicitly enabled')
if os.getenv('PETRO_OPERATIONAL_STORAGE')!='postgresql':raise SystemExit('PostgreSQL operational mode required')
from app.core.operational_mode import configured_target
config=configured_target()
if not config or config.get('lifecycle_enabled') is not True:raise SystemExit('Lifecycle policy not activated')
from app.database.session import engine,SessionLocal
from app.services import operational_service as ops
from app.services.request_expiry import tick
from sqlalchemy import text
stop=False
def shutdown(*_):
    global stop
    stop=True
signal.signal(signal.SIGINT,shutdown);signal.signal(signal.SIGTERM,shutdown)
heartbeat=Path(os.environ['PETRO_PROJECT_ROOT'])/'.runtime/phase58b_expiry_health.json'
with engine.connect() as lease:
    with SessionLocal() as db:ops.guard(db);db.rollback()
    locked=lease.scalar(text("SELECT pg_try_advisory_lock(hashtextextended('petro-request-expiry-worker',0))"));lease.commit()
    if not locked:raise SystemExit('Expiry worker already running')
    try:
        while not stop:
            lease.execute(text('SELECT 1'));lease.commit() # Loss of leader lease is fatal, never keep writing.
            count=tick(SessionLocal)
            payload=dict(running=True,last_success_at=datetime.now(timezone.utc).isoformat(),processed=count,pid=os.getpid())
            temporary=heartbeat.with_suffix('.tmp');temporary.write_text(json.dumps(payload),encoding='utf-8');os.replace(temporary,heartbeat)
            if args.once:break
            until=time.monotonic()+args.interval
            while not stop and time.monotonic()<until:time.sleep(min(.2,max(0,until-time.monotonic())))
    finally:
        heartbeat.write_text(json.dumps(dict(running=False,stopped_at=datetime.now(timezone.utc).isoformat())),encoding='utf-8')
        lease.execute(text("SELECT pg_advisory_unlock(hashtextextended('petro-request-expiry-worker',0))"));lease.commit()
