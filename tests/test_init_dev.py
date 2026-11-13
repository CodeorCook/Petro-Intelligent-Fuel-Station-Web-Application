"""Restricted developer-profile boundaries; no DB or bank calls in unit tests."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from sqlalchemy.engine import make_url
from app.core import local_dev_profile as dev,local_onboarding as on

class InitDevTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.values={'PETRO_ENVIRONMENT':'local-development','PETRO_REAL_PAYMENTS_ENABLED':'false','ENABLE_PAYMENT_SIMULATION':'false'}
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
        self.sync()
    def sync(self):
        (self.root/'.env').write_text('\n'.join(k+'='+v for k,v in self.values.items()),encoding='utf-8')
    def test_offline_markers_and_no_bank_config(self):dev.offline_environment(self.root,setup=True)
    def test_no_attestation_is_inferred_from_localhost(self):
        self.values.pop('PETRO_ENVIRONMENT');self.sync()
        with self.assertRaisesRegex(RuntimeError,'requires PETRO_ENVIRONMENT'):dev.offline_environment(self.root)
    def test_production_marker_rejected(self):
        self.values['APP_ENV']='production';self.sync()
        with self.assertRaisesRegex(RuntimeError,'production/shared staging'):dev.offline_environment(self.root)
    def test_shared_staging_marker_rejected(self):
        os.environ['DEPLOYMENT_ENV']='staging'
        with self.assertRaisesRegex(RuntimeError,'production/shared staging'):dev.offline_environment(self.root)
    def test_webhook_secret_in_dotenv_cannot_be_masked_by_env(self):
        self.values['CASSO_WEBHOOK_SECRET']='UNIT_TEST_REJECT_ONLY';self.sync();os.environ['CASSO_WEBHOOK_SECRET']=''
        with self.assertRaisesRegex(RuntimeError,'CASSO_WEBHOOK_SECRET'):dev.offline_environment(self.root)
    def test_vietqr_beneficiary_rejected(self):
        os.environ['VIETQR_BANK_BIN']='UNIT_TEST_NO_BANK'
        with self.assertRaisesRegex(RuntimeError,'VIETQR_BANK_BIN'):dev.offline_environment(self.root)
    def test_real_payments_cannot_be_enabled(self):
        self.values['PETRO_REAL_PAYMENTS_ENABLED']='true';self.sync()
        with self.assertRaisesRegex(RuntimeError,'REAL_PAYMENTS_ENABLED=false'):dev.offline_environment(self.root)
    def test_worker_override_rejected_during_setup(self):
        os.environ['PETRO_LIFECYCLE_WORKER_ENABLED']='true'
        with self.assertRaisesRegex(RuntimeError,'worker enable override'):dev.offline_environment(self.root,setup=True)
        dev.offline_environment(self.root,setup=False)  # explicitly launched test worker, not setup
    def test_dotenv_worker_override_rejected_at_runtime(self):
        self.values['PETRO_LIFECYCLE_WORKER_ENABLED']='true';self.sync()
        with self.assertRaisesRegex(RuntimeError,'worker enable override'):dev.offline_environment(self.root)
    def test_remote_database(self):
        with self.assertRaisesRegex(RuntimeError,'loopback PostgreSQL'):dev.validate_url(make_url('postgresql+psycopg://unit@203.0.113.9:5432/DB_TRAMXANG'))
    def test_private_loopback_port_pinned_without_fake_5432(self):
        dev.validate_url(make_url('postgresql+psycopg://unit@127.0.0.1:55463/DB_TRAMXANG'))
    def test_connection_routing_query_override(self):
        with self.assertRaisesRegex(RuntimeError,'routing overrides'):dev.validate_url(make_url('postgresql+psycopg://unit@localhost:5432/DB_TRAMXANG?host=203.0.113.9'))
    def test_pg_environment_cannot_route_to_another_host(self):
        os.environ['PGHOSTADDR']='203.0.113.9'
        with self.assertRaisesRegex(RuntimeError,'routing/session environment'):dev.offline_environment(self.root)
    def test_database_listening_on_lan_rejected(self):
        db=Mock();db.execute.return_value.one.return_value=('127.0.0.1','*',False,'unit')
        with self.assertRaisesRegex(RuntimeError,'not loopback-only'):dev.database_isolation(db)
    def test_active_transaction_data_rejected_before_any_profile_trust(self):
        db=Mock();db.scalar.side_effect=[1,0,0]
        with self.assertRaisesRegex(RuntimeError,'active requests/payments/holds'):dev.verify_test_data(db,{},self.root)
    def test_source_reference_and_clean_profile(self):
        value=dev.dataset();self.assertEqual(value['kind'],'synthetic_catalog_only')
        self.assertEqual(sum(map(len,value['rows'].values())),16)
        self.assertFalse({'nguoi_dung','tram_xang','giao_dich','yeu_cau_do_xang'}&set(value['rows']))
    def test_existing_configuration_is_never_overwritten_or_reconfirmed(self):
        file=self.root/on.LOCAL;file.parent.mkdir(parents=True);file.write_text('existing')
        confirm=Mock()
        with patch.object(on,'reuse_existing',return_value={'status':'EXISTING_UNCHANGED'}) as reuse:
            result=on.init_dev(confirm,self.root)
        self.assertEqual(result['status'],'EXISTING_UNCHANGED');reuse.assert_called_once_with(self.root)
        confirm.assert_not_called();self.assertEqual(file.read_text(),'existing')
    def test_no_bank_setting_returned_for_restricted_profile(self):
        from app.services import casso_integration as casso
        with patch('app.core.operational_mode.configured_target',return_value={'profile':dev.PROFILE}):
            for key in casso.PAYMENT_KEYS:self.assertEqual(casso.payment_setting(key),'')

if __name__=='__main__':unittest.main()
