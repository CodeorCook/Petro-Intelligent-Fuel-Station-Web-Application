"""Offline payment contracts; no app.main, private policy or external bank calls."""
import os
import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app.services import casso_integration as casso
from tests.test_casso_merge_pure import BANK_ENV


def receipt(**changes):
    return dict(tid='MOCK-TID-1', description='PETRO GD123456', amount='49868',
                accountNumber=BANK_ENV['CASSO_BANK_ACCOUNT'], **changes)


class ReceiptContracts(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, BANK_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_or_invalid_tid_is_diagnosed_without_audit_claim(self):
        for tid in ('', None, True, {}, [], 'x' * 65, 'bad\nTID'):
            item=receipt(); item['tid']=tid
            events, rejected=casso.parse_casso_events({'data':[item]})
            self.assertEqual(events, [])
            self.assertEqual(rejected[0]['reason'], 'missing_or_invalid_bank_tid')
            self.assertFalse(rejected[0]['audit_persisted'])

    def test_unverified_receipts_are_not_events(self):
        cases=[('accountNumber',''), ('accountNumber','999999999'),
               ('bank_sub_acc_id','999999999'), ('type','DEBIT'),
               ('amount','NaN'), ('amount','Infinity'), ('amount',-1),
               ('description','PETRO GD123456 GD654321'),
               ('description','XXGD123456X'), ('description','no invoice')]
        for key,value in cases:
            item=receipt();item[key]=value
            with self.subTest(key=key,value=value):
                events,rejected=casso.parse_casso_events({'data':[item]})
                self.assertFalse(events)
                self.assertEqual(len(rejected),1)
                self.assertNotIn('description',rejected[0])
                self.assertNotIn('account_number',rejected[0])

    def test_batch_conflict_detected_before_any_settlement(self):
        for changes in ({'amount':'49867'}, {'description':'PETRO GD654321'},
                        {'description':'no invoice'}):
            second=receipt();second.update(changes)
            with self.assertRaises(casso.CassoPayloadConflict):
                casso.parse_casso_events({'data':[receipt(),second]})

    def test_identical_retry_and_provider_numeric_id(self):
        events,rejected=casso.parse_casso_events({'data':[receipt(),receipt()]})
        self.assertEqual(len(events),2)
        self.assertFalse(rejected)
        item=receipt();item.pop('tid');item['id']=123
        self.assertEqual(casso.validated_casso_events({'data':item})[0]['tid'],'123')

    def test_qr_and_settlement_share_round_half_up(self):
        for value,expected in [('49867.49',49867),('49867.5',49868),('49868',49868)]:
            result=casso.qr_fields('GD123456',Decimal(value))
            self.assertEqual(result['qr_payment_amount'],expected)
            self.assertEqual(casso.payment_amount(value),Decimal(expected))
        for value in ['NaN','Infinity','bad','0.1','0','-1','1e10000']:
            self.assertFalse(casso.qr_fields('GD123456',value)['qr_configured'])

    def test_self_service_profile_forces_all_payment_keys_off(self):
        with patch('app.core.operational_mode.configured_target',return_value={'profile':'local-dev-self-service-v1'}):
            for key in casso.PAYMENT_KEYS:
                self.assertEqual(casso.payment_setting(key),'')
            self.assertFalse(casso.qr_fields('GD123456',50000)['qr_configured'])
            self.assertFalse(casso.validated_casso_events({'data':receipt()}))

    def test_bank_settings_required_but_secret_not_needed_to_show_qr(self):
        with patch.dict(os.environ,{'CASSO_WEBHOOK_SECRET':''}):
            self.assertTrue(casso.qr_fields('GD123456',50000)['qr_configured'])
        for key in BANK_ENV.keys()-{'CASSO_WEBHOOK_SECRET'}:
            with patch.dict(os.environ,{key:''}):
                self.assertFalse(casso.qr_fields('GD123456',50000)['qr_configured'])


class WebhookContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import API router in its own test process, bound to in-memory SQLite.
        # It is never connected: webhook UoW is mocked in these HTTP contracts.
        os.environ['DATABASE_URL']='sqlite:///:memory:'
        # Model registration must not depend on a developer's .env/approval.
        # No SQL connection or UoW runs in these rejection-only HTTP tests.
        os.environ['PETRO_OPERATIONAL_STORAGE']='postgresql'
        from app.api.endpoints.api_routes import payment_workflow as api
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        cls.api=api
        app=FastAPI();app.include_router(api.router)
        app.dependency_overrides[api.get_db]=lambda:MagicMock()
        cls.client=TestClient(app)

    def setUp(self):
        self.env=patch.dict(os.environ,BANK_ENV);self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_wrong_and_non_ascii_token_rejected(self):
        for headers in ({},{'secure-token':'wrong'},{b'secure-token':b'\xff'}):
            self.assertEqual(self.client.post('/api/payment/casso-webhook',json={'data':[]},headers=headers).status_code,401)

    def test_no_secret_or_beneficiary_is_503(self):
        for key in ('CASSO_WEBHOOK_SECRET','CASSO_BANK_ACCOUNT'):
            with patch.dict(os.environ,{key:''}):
                self.assertEqual(self.client.post('/api/payment/casso-webhook',json={'data':[]}).status_code,503)

    def test_profile_payment_off_overrides_accidental_bank_settings(self):
        with patch('app.core.operational_mode.configured_target',return_value={'profile':'local-dev-self-service-v1'}):
            self.assertEqual(self.client.post('/api/payment/casso-webhook',json={'data':receipt()},headers={'secure-token':BANK_ENV['CASSO_WEBHOOK_SECRET']}).status_code,503)

    def test_conflicting_batch_rejected_before_uow(self):
        second=receipt();second['amount']='1000'
        response=self.client.post('/api/payment/casso-webhook',json={'data':[receipt(),second]},headers={'secure-token':BANK_ENV['CASSO_WEBHOOK_SECRET']})
        self.assertEqual(response.status_code,409)

    def test_rejections_never_claim_payment_or_persisted_audit(self):
        item=receipt();item['tid']=''
        response=self.client.post('/api/payment/casso-webhook',json={'data':item},headers={'secure-token':BANK_ENV['CASSO_WEBHOOK_SECRET']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['settled_count'],0)
        self.assertEqual(response.json()['rejected_count'],1)
        self.assertFalse(response.json()['audit_persisted'])

    def test_invalid_json_rejected_and_legacy_settlement_disabled(self):
        headers={'secure-token':BANK_ENV['CASSO_WEBHOOK_SECRET']}
        self.assertEqual(self.client.post('/api/payment/casso-webhook',content='not json',headers=headers).status_code,400)
        with patch.object(self.api,'POSTGRESQL_OPERATIONS',False):
            self.assertEqual(self.client.post('/api/payment/casso-webhook',json={'data':receipt()},headers=headers).status_code,503)


if __name__=='__main__':
    unittest.main()
