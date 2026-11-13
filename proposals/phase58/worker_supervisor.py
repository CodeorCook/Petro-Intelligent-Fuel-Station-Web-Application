"""Windows-compatible expiry supervisor. Explicit private configuration only.

No credentials in argv. Child cooperative stop uses a private IPC file and Python
signal dispatch, not a console-wide Ctrl+C or forcibly killed DB transaction.
"""
from pathlib import Path
import argparse,hashlib,json,os,sys,time,subprocess,secrets,signal,threading,runpy,_thread
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read_json(path,default=None):
    """Share DELETE on Windows so an atomic heartbeat replace is never blocked.

    Brief sharing/AV errors are unavailable samples, NOT process failures. The
    caller still enforces the age of the last valid heartbeat (60 seconds).
    """
    for attempt in range(3):
        try:
            if os.name!='nt':return json.loads(path.read_text(encoding='utf-8'))
            import ctypes,msvcrt
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            create=kernel.CreateFileW
            create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
            create.restype=wintypes.HANDLE
            handle=create(str(path),0x80000000,1|2|4,None,3,0x80,None)
            if handle==ctypes.c_void_p(-1).value:
                code=ctypes.get_last_error()
                if code in (2,3):return default
                if code in (5,32):raise PermissionError(code,'Heartbeat temporarily unavailable')
                raise ctypes.WinError(code)
            fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
            with os.fdopen(fd,'rb') as stream:return json.loads(stream.read().decode('utf-8'))
        except (FileNotFoundError,json.JSONDecodeError):return default
        except PermissionError:
            if attempt==2:return default
            time.sleep(.02)
def write(path,data):
    temp=path.with_suffix('.tmp')
    for attempt in range(10):
        try:
            temp.write_text(json.dumps(data),encoding='utf-8');os.replace(temp,path);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.05)
def load(path):
    path=path.resolve();assert path.is_relative_to(ROOT/'.runtime'),'Private configuration required'
    config=json.loads(path.read_text(encoding='utf-8'))
    work=Path(config['work']).resolve();assert work.is_relative_to(ROOT/'.runtime')
    source=Path(config['source_root']).resolve()
    worker=source/'scripts/expire_fuel_requests.py'
    assert sha(worker)==config['worker_sha256'],'Worker release hash mismatch'
    policy=Path(config['policy']).resolve();assert policy.is_relative_to(ROOT/'.runtime')
    assert sha(policy)==config['policy_sha256'],'Policy hash mismatch'
    policy_data=json.loads(policy.read_text(encoding='utf-8'));assert policy_data['lifecycle_enabled'] is True
    if config['mode']=='isolated':assert policy_data['target']['port']==55457
    else:
        sys.path.insert(0,str(ROOT))
        from app.core.local_dev_profile import PROFILE
        assert config['mode']=='development' and (policy_data['target']['port']==5432 or policy_data.get('profile')==PROFILE)
        # Direct supervisor and API startup use the same machine-local approval.
        from app.core.development_deployment import load_deployment,private_path
        deployment=load_deployment(ROOT)
        assert path==private_path(deployment['supervisor_config'],'supervisor configuration',ROOT),'Unapproved supervisor configuration'
    return config,work,source,worker
def environment(config,source):
    from dotenv import dotenv_values
    env=os.environ.copy()
    if config['mode']=='development':
        env.update({k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None})
        if not env.get('SESSION_SECRET'):
            secret=Path(config['session_secret']).resolve();assert secret.is_relative_to(ROOT/'.runtime')
            env['SESSION_SECRET']=secret.read_text(encoding='utf-8').strip()
    else:env['DATABASE_URL']='postgresql+psycopg://phase57_test@127.0.0.1:55457/DB_TRAMXANG'
    env.update(PETRO_OPERATIONAL_STORAGE='postgresql',PETRO_LIFECYCLE_WORKER_ENABLED='true',
       PETRO_PROJECT_ROOT=str(ROOT),PETRO_OPERATIONAL_CONFIG=config['policy'],
       PETRO_OPERATIONAL_CONFIG_SHA256=config['policy_sha256'],ENABLE_PAYMENT_SIMULATION='false',
       FUEL_PRICE_REFRESH_ON_REQUEST='false',PYTHONUNBUFFERED='1')
    return env
def child(config,work,source,worker):
    os.environ.update(environment(config,source));sys.path.insert(0,str(source));os.chdir(source)
    # Fresh private run token prevents a stale stop request targeting a new child.
    token=os.environ['PETRO_SUPERVISOR_CHILD_TOKEN'];stopfile=work/'child_stop.json'
    write(work/'child_identity.json',dict(token=token,pid=os.getpid()))
    def watch():
        while True:
            data=read_json(stopfile,{})
            if data.get('token')==token:
                _thread.interrupt_main(signal.SIGTERM);return
            time.sleep(.2)
    threading.Thread(target=watch,daemon=True).start()
    sys.argv=[str(worker),'--interval','2'];runpy.run_path(str(worker),run_name='__main__')
def run(config,work,source,worker,path):
    import msvcrt
    work.mkdir(parents=True,exist_ok=True)
    lock=(work/'supervisor.lock').open('a+b');lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:raise SystemExit('Supervisor already running')
    stopping=False
    def request_stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,request_stop);signal.signal(signal.SIGTERM,request_stop)
    instance=secrets.token_hex(16);restarts=0;proc=None;token=None;reason='starting';last_start=0;last_health={}
    def state(running,**extra):
        child_info=read_json(work/'child_identity.json',{})
        write(work/'supervisor_health.json',dict(running=running,instance=instance,pid=os.getpid(),
          worker_pid=child_info.get('pid') if child_info.get('token')==token else None,
          worker_launcher_pid=proc.pid if proc else None,restarts=restarts,reason=reason,
          updated_at=datetime.now(timezone.utc).isoformat(),**extra))
    def stop_child():
        if proc is None or proc.poll() is not None:return
        write(work/'child_stop.json',dict(token=token))
        try:proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            # Do not kill a potentially active transaction or launch a second writer.
            raise RuntimeError('Worker did not stop cooperatively; operator review required')
    state(True)
    try:
        while not stopping:
            command=read_json(work/'supervisor_stop.json',{})
            if command.get('instance')==instance:break
            if proc is None or proc.poll() is not None:
                if proc is not None:
                    restarts+=1;reason='child_failed';state(True,last_exit_code=proc.returncode)
                    if restarts>5:raise RuntimeError('Restart budget exceeded; operator review required')
                    time.sleep(min(2**restarts,15))
                token=secrets.token_hex(16);env=environment(config,source);env['PETRO_SUPERVISOR_CHILD_TOKEN']=token
                with (work/'worker.private.log').open('ab') as log:
                    proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'child','--config',str(path)],
                       env=env,cwd=source,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                last_start=time.monotonic();reason='running';state(True)
            heartbeat=ROOT/'.runtime/phase58b_expiry_health.json'
            sample=read_json(heartbeat)
            if sample is not None:last_health=sample
            health=last_health
            child_info=read_json(work/'child_identity.json',{})
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(health['last_success_at'])).total_seconds() if health.get('last_success_at') else None
            healthy=health.get('running') is True and child_info.get('token')==token and health.get('pid')==child_info.get('pid') and age is not None and age<60
            if time.monotonic()-last_start>65 and not healthy:
                reason='stale_heartbeat';state(True,healthy=False);stop_child()
            else:state(True,healthy=healthy,heartbeat_age_seconds=age)
            time.sleep(.5)
        reason='operator_stop';stop_child();state(False,healthy=False)
    except BaseException:
        reason='supervisor_failed';state(False,healthy=False)
        stop_child();raise
    finally:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','child','stop','status'])
    parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config,work,source,worker=load(args.config)
    if args.action=='child':child(config,work,source,worker)
    elif args.action=='run':run(config,work,source,worker,args.config.resolve())
    else:
        health=read_json(work/'supervisor_health.json')
        if health is None:raise SystemExit('Supervisor status unavailable; retry or inspect private logs')
        if args.action=='stop':write(work/'supervisor_stop.json',dict(instance=health['instance']))
        print(json.dumps(health))
