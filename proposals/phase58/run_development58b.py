"""Explicit approved development launcher. Never migrates or starts an expiry worker."""
from pathlib import Path
import os,sys,json,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from app.core.development_deployment import load_deployment
deployment = load_deployment(ROOT)
assert deployment.get('migration_verified') and deployment.get('promotion_verified'),'Cutover not ready'
from proposals.phase58.worker_supervisor import load,environment
config,work,source,worker=load(ROOT/deployment['supervisor_config'])
assert config['mode']=='development' and source==ROOT
os.environ.update(environment(config,source))
os.environ.pop('PETRO_LIFECYCLE_WORKER_ENABLED',None)
from sqlalchemy.orm import configure_mappers
from app.main import app
configure_mappers();app.openapi()
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False)
