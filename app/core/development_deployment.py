"""Machine-local approval binding. No discovery, DB writes or policy generation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = Path('.runtime/development/deployment.local.json')


def fail(gate):
    raise RuntimeError('PETRO configuration gate failed: ' + gate)


def read(path, label):
    if not path.is_file():
        fail(label + ' missing')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        fail(label + ' unreadable or invalid JSON')


def private_path(value, label, root=ROOT):
    path = (root / value).resolve()
    if not path.is_relative_to((root / '.runtime').resolve()):
        fail(label + ' must stay inside .runtime')
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_binding(deployment, root=ROOT):
    """A previously approved hash binds policy and target; never accept a queried ID."""
    if deployment.get('migration_verified') is not True or deployment.get('promotion_verified') is not True:
        fail('development release not approved')
    path = private_path(deployment['supervisor_config'], 'supervisor configuration', root)
    config = read(path, 'supervisor configuration')
    if deployment.get('supervisor_sha256') and digest(path) != deployment['supervisor_sha256']:
        fail('supervisor configuration SHA256 mismatch')
    if config.get('mode') != 'development' or Path(config['source_root']).resolve() != root.resolve():
        fail('supervisor mode/source root mismatch')
    private_path(config['work'], 'supervisor work directory', root)
    policy = private_path(config['policy'], 'private policy', root)
    data = read(policy, 'private policy')
    if digest(policy) != deployment.get('policy_sha256') or digest(policy) != config.get('policy_sha256'):
        fail('private policy SHA256 mismatch')
    worker = root / 'scripts/expire_fuel_requests.py'
    if not worker.is_file() or digest(worker) != config.get('worker_sha256'):
        fail('worker SHA256 mismatch')
    if deployment.get('supervisor_source_sha256') and digest(root / 'proposals/phase58/worker_supervisor.py') != deployment['supervisor_source_sha256']:
        fail('supervisor source SHA256 mismatch; owner release review required')
    if (data.get('schema_version') != 1 or data.get('activation_authorized') is not True
            or data.get('legacy_import_rows') != 0 or data.get('lifecycle_enabled') is not True):
        fail('private policy activation/lifecycle approval')
    target = data['target']
    from app.core.local_dev_profile import PROFILE,validate_binding_profile
    local_dev=data.get('profile')==PROFILE
    if deployment.get('approval_origin',{}).get('kind')=='local-development-init' or local_dev:
        validate_binding_profile(deployment,data,root)
    if (target.get('database') != 'DB_TRAMXANG' or (target.get('port') != 5432 and not local_dev)
            or not str(target.get('system_identifier', '')).isdigit()
            or not target.get('hosts') or not target.get('data_directory')):
        fail('approved PostgreSQL target invalid')
    if 'approved_target' in deployment and target != deployment['approved_target']:
        fail('target differs from local approval')
    return path, config, data


def load_deployment(root=ROOT):
    shared = read(root / 'proposals/phase58/DEVELOPMENT_DEPLOYMENT.json', 'shared deployment release')
    if shared.get('migration_verified') is not True or shared.get('promotion_verified') is not True:
        fail('shared development release not approved')
    local_path = private_path(LOCAL, 'local deployment approval', root)
    if local_path.exists():
        local = read(local_path, 'local deployment approval')
        if local.get('format_version') != 1 or not local.get('approved_target') or not local.get('supervisor_sha256'):
            fail('local deployment approval format')
        deployment = {**shared, **local}
    elif shared.get('supervisor_config') and shared.get('policy_sha256'):
        # Backward compatibility ONLY for an unchanged, hash-approved legacy release.
        deployment = shared
    else:
        fail('local deployment approval missing; new machines: scripts/onboard_petro_local.py prepare then owner approval; existing approvals: scripts/configure_petro_local.py')
    validate_binding(deployment, root)
    return deployment
