import os
import json
import hashlib
from pathlib import Path
from functools import lru_cache

# Off unless explicitly selected by the isolated test launcher. Never auto-fallback.
POSTGRESQL_OPERATIONS = os.getenv('PETRO_OPERATIONAL_STORAGE') == 'postgresql'
if os.getenv('PETRO_OPERATIONAL_STORAGE') not in (None,'json','postgresql'):
    raise RuntimeError('Invalid operational storage mode; refusing silent JSON fallback')

@lru_cache(maxsize=1)
def configured_target():
    """Immutable cutover policy, never an inventory-data source or fallback."""
    filename=os.getenv('PETRO_OPERATIONAL_CONFIG')
    if not filename:return None  # Existing pinned disposable test mode only.
    path=Path(filename).resolve()
    root=Path(os.environ['PETRO_PROJECT_ROOT']).resolve()
    if not path.is_relative_to(root/'.runtime'):
        raise RuntimeError('Operational configuration must be private')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=os.environ.get('PETRO_OPERATIONAL_CONFIG_SHA256'):
        raise RuntimeError('Operational configuration fingerprint mismatch')
    config=json.loads(raw)
    if config.get('schema_version')!=1 or config.get('legacy_import_rows')!=0 or config.get('activation_authorized') is not True:
        raise RuntimeError('Cutover policy is not approved')
    return config

def preserved_request(request_id):
    config=configured_target()
    return bool(config and request_id.strip() in config['preserved_request_ids'])
