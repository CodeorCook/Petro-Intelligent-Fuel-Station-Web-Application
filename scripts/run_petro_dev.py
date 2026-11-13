"""One-command local development. API reload and expiry supervision stay separate."""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def petro_processes():
    # Enumerate command identity rather than trusting stale/reused heartbeat PIDs.
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'worker_supervisor\\.py|manage_expiry58b\\.py|expire_fuel_requests\\.py' } | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    rows=json.loads(result.stdout or '[]');rows=rows if isinstance(rows,list) else ([rows] if rows else [])
    return any(str(ROOT).casefold() in (row.get('CommandLine') or '').casefold() for row in rows)


def descendant(pid, parent):
    # Popen's venv launcher may be the parent of the actual Python process.
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress'],
        capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    parents = {r['ProcessId']:r['ParentProcessId'] for r in json.loads(result.stdout)}
    for _ in range(8):
        if pid == parent:
            return True
        pid = parents.get(pid)
        if not pid:
            return False
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('This launcher uses the approved Windows development supervisor.')
    os.chdir(ROOT)
    from app.core.development_startup import configure_development
    configure_development()
    from app.database.session import engine
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.services.operational_service import guard
    from proposals.phase58.worker_supervisor import load, read_json, write
    from proposals.phase58.provision58c import health
    from app.core.development_deployment import load_deployment
    deployment = load_deployment(ROOT)
    _, work, _, _ = load(ROOT/deployment['supervisor_config'])
    def check():
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            guard(db)
            value = health(work, db)
            db.rollback()
            return value

    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', args.port))
        except OSError:
            raise SystemExit(f'API port {args.port} already in use; nothing started.') from None

    import msvcrt
    logs = ROOT/'.runtime/start-all'
    logs.mkdir(parents=True, exist_ok=True)
    lock = (logs/f'launcher-{args.port}.lock').open('a+b')
    lock.write(b'1');lock.flush();lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise SystemExit('Start All is already running for this API port.') from None
    supervisor = None
    owned_instance = None
    stop_monitor = threading.Event()
    monitor = None
    try:
        sample = check()
        if sample['healthy']:
            print('Expiry worker healthy; reusing independent supervisor (will keep it on exit).', flush=True)
        else:
            state = read_json(work/'supervisor_health.json', {})
            if sample['singleton_lease_count'] or petro_processes():
                raise RuntimeError('Worker is unhealthy but a process/lease exists. Review runbook; no duplicate started.')
            log = logs/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.supervisor.private.log')
            with log.open('ab') as output:
                supervisor = subprocess.Popen([sys.executable, str(ROOT/'proposals/phase58/manage_expiry58b.py'), 'run'],
                    cwd=ROOT, stdout=output, stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                if supervisor.poll() is not None:
                    raise RuntimeError('Supervisor exited; inspect .runtime/start-all private log. API not started.')
                state = read_json(work/'supervisor_health.json', {})
                if state.get('running') and descendant(state.get('pid'), supervisor.pid):
                    owned_instance = state['instance']
                sample = check()
                if sample['healthy'] and owned_instance:
                    break
            else:
                raise RuntimeError('Worker heartbeat/lease not healthy within startup deadline. API not started.')
            print('Expiry worker started and healthy; this launcher owns its supervisor.', flush=True)

        def watch():
            while not stop_monitor.wait(15):
                try:
                    if not check()['healthy']:
                        print('ERROR: expiry worker unhealthy. Website is not fully ready; inspect supervisor logs.', flush=True)
                except Exception as error:
                    print(f'ERROR: expiry health check failed ({type(error).__name__}); website readiness degraded.', flush=True)
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        print(f'PETRO ready: http://127.0.0.1:{args.port} ; Ctrl+C stops API and only launcher-owned supervisor.', flush=True)
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.port, reload=True, reload_dirs=[str(ROOT/'app')])
    finally:
        # A second Ctrl+C must not abandon cooperative supervisor cleanup.
        previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
        stop_monitor.set()
        if monitor:
            monitor.join(timeout=5)
        if supervisor is not None:
            state = read_json(work/'supervisor_health.json', {})
            if not owned_instance and supervisor.poll() is None and state.get('running') and descendant(state.get('pid'), supervisor.pid):
                owned_instance = state['instance']
            if owned_instance and state.get('instance') == owned_instance:
                write(work/'supervisor_stop.json', {'instance':owned_instance})
            # Wait only for our child; never terminate an unknown process or DB session.
            try:
                supervisor.wait(timeout=50)
            except subprocess.TimeoutExpired:
                raise RuntimeError('Owned supervisor did not stop cooperatively; inspect runbook. No transaction forcibly killed.') from None
            print('Launcher-owned supervisor stopped cooperatively.', flush=True)
        engine.dispose()
        lock.seek(0);msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1);lock.close()
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f'PETRO startup/shutdown failed: {error}', file=sys.stderr)
        raise SystemExit(1) from None
