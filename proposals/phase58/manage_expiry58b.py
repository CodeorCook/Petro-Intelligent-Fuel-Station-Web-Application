"""Explicit development worker supervision: run | status | stop."""
from pathlib import Path
import sys,json,runpy
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from app.core.development_deployment import load_deployment
deployment = load_deployment(ROOT)
assert deployment.get('migration_verified') and deployment.get('promotion_verified')
assert len(sys.argv)==2 and sys.argv[1] in ('run','status','stop')
script=ROOT/'proposals/phase58/worker_supervisor.py'
sys.argv=[str(script),sys.argv[1],'--config',str(ROOT/deployment['supervisor_config'])]
runpy.run_path(str(script),run_name='__main__')
