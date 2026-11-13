"""Approved local configuration before database/auth imports. No workers or writes."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def configure_development():
    try:
        from proposals.phase58.worker_supervisor import load, environment
        from app.core.development_deployment import load_deployment
        deployment = load_deployment(ROOT)
        config, _, source, worker = load(ROOT / deployment['supervisor_config'])
        policy = Path(config['policy']).resolve()
        data = json.loads(policy.read_bytes())
        target = data['target']
        env = environment(config, source)
        # Dotenv must never conceal contradictory caller configuration.
        for key in ('DATABASE_URL', 'SESSION_SECRET', 'PETRO_OPERATIONAL_STORAGE',
                    'PETRO_PROJECT_ROOT', 'PETRO_OPERATIONAL_CONFIG',
                    'PETRO_OPERATIONAL_CONFIG_SHA256', 'ENABLE_PAYMENT_SIMULATION',
                    'FUEL_PRICE_REFRESH_ON_REQUEST'):
            if key in os.environ and os.environ[key] != env.get(key):
                raise RuntimeError('PETRO startup: conflicting environment variable ' + key)
        if not env.get('DATABASE_URL') or not env.get('SESSION_SECRET'):
            raise RuntimeError('PETRO configuration gate failed: DATABASE_URL or SESSION_SECRET missing')
        from sqlalchemy.engine import make_url
        url = make_url(env['DATABASE_URL'])
        if (url.get_backend_name() != 'postgresql' or url.host not in target['hosts']
                or url.port != target['port'] or url.database != target['database']):
            raise RuntimeError('PETRO configuration gate failed: DATABASE_URL target differs from approved policy')
        env.pop('PETRO_LIFECYCLE_WORKER_ENABLED', None)
        os.environ.update(env)
        os.environ.pop('PETRO_LIFECYCLE_WORKER_ENABLED', None)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError('PETRO configuration gate failed: invalid startup configuration; inspect local approval/runbook') from None
