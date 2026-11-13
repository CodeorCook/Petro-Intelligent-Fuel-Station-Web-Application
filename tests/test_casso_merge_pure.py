"""Offline pure-contract checks. Does not import app.main or touch PostgreSQL."""
import os
import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from decimal import Decimal
from app.services.casso_integration import qr_fields, validated_casso_events, beneficiary

BANK_ENV = {
    'VIETQR_BANK_BIN':'970422',
    'CASSO_BANK_ACCOUNT':'0123456789',
    'VIETQR_ACCOUNT_NAME':'DEMO RECEIVER',
    'VIETQR_BANK_NAME':'Demo Bank',
    'CASSO_WEBHOOK_SECRET':'test-only',
}

class CassoContractTests(unittest.TestCase):
    def test_status_response_carries_exact_qr_amount(self):
        # Run the actual response handler with isolated query/auth fixtures.
        # This verifies serialization only, not authentication or settlement.
        tree=ast.parse(Path('app/api/endpoints/api_routes/payment_workflow.py').read_text(encoding='utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_fuel_request_status')
        handler.decorator_list=[]
        handler.args.defaults=[]
        for arg in handler.args.args: arg.annotation=None
        handler.returns=None
        scope={name:MagicMock() for name in ['select','selectinload','YeuCauDoXang','ChiTietYeuCau','Gia','_require_request_access']}
        scope.update(POSTGRESQL_OPERATIONS=False,qr_fields=qr_fields,workflow_view=lambda *a:{},
                     REQUEST_WAITING='WAITING',REQUEST_ACCEPTED='ACCEPTED',REQUEST_PUMPING='PUMPING',PAYMENT_SUCCEEDED='PAID')
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'<isolated status response>','exec'),scope)
        req=SimpleNamespace(yc_ma='YC123456',tx_ma='TX000001',ttxn_ma='COMPLETED',pt_bienso='',hinh_thuc_do_xang='SO_LIT',
            chitiet_yeucau=[],giao_dich=[SimpleNamespace(gd_ma='GD123456',gd_sotien=Decimal('49867.5'),tt_ma='PENDING')],
            tram_xang=SimpleNamespace(tx_ten='Isolated',tx_diachi=''),trang_thai_xac_nhan=None,thoi_gian_tao=None)
        db=MagicMock();db.scalars.return_value.first.return_value=req
        with patch.dict(os.environ,{**BANK_ENV,'CASSO_WEBHOOK_SECRET':''}):
            result=scope['get_fuel_request_status']('YC123456',db,None)
            self.assertEqual(result['qr_payment_amount'],49868)
            self.assertIn('amount=49868',result['vietqr_url'])
            self.assertEqual(result['thanhtien'],49867.5)
        with patch.dict(os.environ,{**BANK_ENV,'CASSO_BANK_ACCOUNT':''}):
            result=scope['get_fuel_request_status']('YC123456',db,None)
            self.assertIsNone(result['qr_payment_amount'])
            self.assertFalse(result['qr_configured'])

    def test_qr_does_not_require_webhook_secret(self):
        with patch.dict(os.environ, {**BANK_ENV, 'CASSO_WEBHOOK_SECRET':''}):
            self.assertTrue(qr_fields('GD123456', Decimal('49867.5'))['qr_configured'])

    def test_each_bank_setting_required(self):
        for key in ('VIETQR_BANK_BIN','CASSO_BANK_ACCOUNT','VIETQR_ACCOUNT_NAME','VIETQR_BANK_NAME'):
            with self.subTest(key=key), patch.dict(os.environ, {**BANK_ENV,key:''}):
                result=qr_fields('GD123456',Decimal('1000'))
                self.assertFalse(result['qr_configured'])
                self.assertIsNone(result['vietqr_url'])
                self.assertIsNone(result['qr_payment_amount'])

    def test_unconfigured_disables_qr(self):
        with patch.dict(os.environ, {k:'' for k in BANK_ENV}):
            self.assertFalse(qr_fields('GD123456', Decimal('1000'))['qr_configured'])
            self.assertEqual(validated_casso_events({'data':[{}]}), [])

    def test_qr_uses_config_and_rounds_no_truncation(self):
        with patch.dict(os.environ, BANK_ENV):
            result = qr_fields('GD123456', Decimal('49867.5'))
            self.assertEqual(result['qr_payment_amount'], 49868)
            self.assertIn('amount=49868', result['vietqr_url'])
            self.assertIn('addInfo=PETRO+GD123456', result['vietqr_url'])
            self.assertEqual(result['bank_account'], '0123456789')

    def test_casso_event_is_bank_bound(self):
        receipt={'tid':'T-123','description':'PETRO GD123456','amount':49868,'subAccId':'0123456789'}
        with patch.dict(os.environ, BANK_ENV):
            self.assertEqual(len(validated_casso_events({'error':0,'data':[receipt]})),1)
            for modified in [dict(receipt, subAccId='9999999999'),
                             dict(receipt, subAccId=''),
                             dict(receipt, amount=-20),
                             dict(receipt, type='DEBIT'),
                             dict(receipt, tid=''),
                             dict(receipt, description='PETRO GD123456 GD999999'),
                             dict(receipt, description='ABCDEFGD123456X')]:
                self.assertEqual(validated_casso_events({'error':0,'data':[modified]}), [])

    def test_batch_and_object_forms(self):
        receipt={'reference':'BNK001','description':'PETRO GD123456','amount':'1000','accountNumber':'0123456789'}
        with patch.dict(os.environ,BANK_ENV):
            for value in (receipt,[receipt]):
                result=validated_casso_events({'error':0,'data':value})
                self.assertEqual(len(result),1)
                self.assertEqual(result[0]['tid'],'BNK001')

if __name__ == '__main__':unittest.main()
