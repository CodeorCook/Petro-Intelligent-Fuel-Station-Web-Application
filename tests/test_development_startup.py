"""Isolated configuration tests: synthetic files only, no database/network."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.core import development_startup as startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'proposals/phase58').mkdir(parents=True)
        (self.root / '.runtime/development').mkdir(parents=True)
        self.policy = self.root / '.runtime/policy.json'
        (self.root / 'scripts').mkdir()
        self.worker = self.root / 'scripts/expire_fuel_requests.py'
        self.worker.write_text('# synthetic worker, never executed')
        self.data = dict(schema_version=1, activation_authorized=True, legacy_import_rows=0,
                         lifecycle_enabled=True, target=dict(port=5432, database='DB_TRAMXANG',
                         system_identifier='1111111111111111111', hosts=['127.0.0.1'], data_directory=str(self.root/'pgdata')))
        self.config = dict(mode='development', source_root=str(self.root), work=str(self.root/'.runtime/work'), policy=str(self.policy),
                           worker_sha256=hashlib.sha256(self.worker.read_bytes()).hexdigest())
        self.env = dict(DATABASE_URL='postgresql+psycopg://synthetic@127.0.0.1:5432/DB_TRAMXANG',
                        SESSION_SECRET='isolated-test-marker', PETRO_OPERATIONAL_STORAGE='postgresql',
                        PETRO_LIFECYCLE_WORKER_ENABLED='true')
        self.sync()
        for context in (patch.object(startup, 'ROOT', self.root), patch.dict(os.environ, {}, clear=True),
                        patch('proposals.phase58.worker_supervisor.load', side_effect=lambda _: (self.config, self.root/'.runtime', self.root, self.worker)),
                        patch('proposals.phase58.worker_supervisor.environment', side_effect=lambda *_: self.env.copy())):
            context.start(); self.addCleanup(context.stop)

    def sync(self):
        self.policy.write_text(json.dumps(self.data))
        self.config['policy_sha256'] = hashlib.sha256(self.policy.read_bytes()).hexdigest()
        configfile = self.root/'.runtime/supervisor.json'
        configfile.write_text(json.dumps(self.config), encoding='utf-8')
        self.pointer = self.root/'proposals/phase58/DEVELOPMENT_DEPLOYMENT.json'
        self.pointer.write_text(json.dumps(dict(migration_verified=True, promotion_verified=True)), encoding='utf-8')
        self.local = self.root/'.runtime/development/deployment.local.json'
        self.local.write_text(json.dumps(dict(format_version=1, migration_verified=True, promotion_verified=True,
            supervisor_config='.runtime/supervisor.json', supervisor_sha256=hashlib.sha256(configfile.read_bytes()).hexdigest(),
            policy_sha256=self.config['policy_sha256'], approved_target=self.data['target'])), encoding='utf-8')

    def test_valid_and_repeat(self):
        startup.configure_development(); startup.configure_development()
        self.assertEqual(os.environ['PETRO_OPERATIONAL_STORAGE'], 'postgresql')
        self.assertNotIn('PETRO_LIFECYCLE_WORKER_ENABLED', os.environ)

    def test_missing_release(self):
        self.pointer.unlink()
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_missing_policy(self):
        self.policy.unlink()
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_policy_tamper(self):
        self.policy.write_text('{}')
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_lifecycle_disabled(self):
        self.data['lifecycle_enabled'] = False; self.sync()
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_wrong_system(self):
        self.data['target']['system_identifier'] = '2222222222222222222'
        self.policy.write_text(json.dumps(self.data))
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_worker_tamper(self):
        self.worker.write_text('# changed')
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_inherited_wrong_target_not_overridden(self):
        os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
        with self.assertRaisesRegex(RuntimeError, 'DATABASE_URL'): startup.configure_development()

    def test_json_mode_rejected(self):
        os.environ['PETRO_OPERATIONAL_STORAGE'] = 'json'
        with self.assertRaisesRegex(RuntimeError, 'PETRO_OPERATIONAL_STORAGE'): startup.configure_development()

    def test_missing_url(self):
        self.env.pop('DATABASE_URL')
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_missing_session_secret(self):
        self.env.pop('SESSION_SECRET')
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_wrong_url(self):
        self.env['DATABASE_URL'] = 'postgresql://synthetic@127.0.0.1:55457/DB_TRAMXANG'
        with self.assertRaises(RuntimeError): startup.configure_development()

    def test_distinct_preapproved_machine_target_supported(self):
        self.data['target']['system_identifier'] = '2222222222222222222'
        self.sync()
        startup.configure_development()

    def test_target_mismatch_even_if_policy_checksum_updated(self):
        local = json.loads(self.local.read_text())
        local['approved_target']['system_identifier'] = '9999999999999999999'
        self.local.write_text(json.dumps(local))
        with self.assertRaisesRegex(RuntimeError, 'target differs'): startup.configure_development()

    def test_supervisor_checksum_rejected(self):
        path = self.root/'.runtime/supervisor.json'
        path.write_text(path.read_text() + ' ')
        with self.assertRaisesRegex(RuntimeError, 'supervisor configuration SHA256'): startup.configure_development()

    def test_local_approval_cannot_override_unapproved_shared_release(self):
        self.pointer.write_text(json.dumps(dict(migration_verified=False, promotion_verified=True)))
        with self.assertRaisesRegex(RuntimeError, 'shared development release not approved'): startup.configure_development()

    def test_private_supervisor_policy_checksum_rejected(self):
        self.config['policy_sha256'] = '0'*64
        configfile = self.root/'.runtime/supervisor.json'
        configfile.write_text(json.dumps(self.config))
        local = json.loads(self.local.read_text())
        local['supervisor_sha256'] = hashlib.sha256(configfile.read_bytes()).hexdigest()
        self.local.write_text(json.dumps(local))
        with self.assertRaisesRegex(RuntimeError, 'private policy SHA256'): startup.configure_development()

    def test_missing_local_approval(self):
        self.local.unlink()
        with self.assertRaisesRegex(RuntimeError, 'local deployment approval missing'): startup.configure_development()

    def test_new_binding_pins_supervisor_source_without_changing_legacy_bindings(self):
        source = self.root/'proposals/phase58/worker_supervisor.py'
        source.write_text('# unit fixture, never executed')
        local = json.loads(self.local.read_text())
        local['supervisor_source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.local.write_text(json.dumps(local))
        startup.configure_development()
        source.write_text('# altered unit supervisor')
        with self.assertRaisesRegex(RuntimeError, 'supervisor source SHA256'): startup.configure_development()

    def test_unapproved_path(self):
        local = json.loads(self.local.read_text())
        local['supervisor_config'] = '../outside.json'
        self.local.write_text(json.dumps(local))
        with self.assertRaisesRegex(RuntimeError, 'inside .runtime'): startup.configure_development()

    def test_legacy_approved_release_compatibility(self):
        self.local.unlink()
        self.pointer.write_text(json.dumps(dict(migration_verified=True, promotion_verified=True,
            supervisor_config='.runtime/supervisor.json', policy_sha256=self.config['policy_sha256'])))
        startup.configure_development()

    def test_bad_legacy_checksum_does_not_auto_approve(self):
        self.local.unlink()
        self.pointer.write_text(json.dumps(dict(migration_verified=True, promotion_verified=True,
            supervisor_config='.runtime/supervisor.json', policy_sha256='0'*64)))
        with self.assertRaisesRegex(RuntimeError, 'private policy SHA256'): startup.configure_development()


if __name__ == '__main__': unittest.main()
