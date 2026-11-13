"""VietQR beneficiary and Casso event parsing. No database mutations here.

The private .env is read for *payment keys only*. Do not override the Phase 5.8
approved PostgreSQL/session/worker environment or trust a hardcoded bank account.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import os
import re
from urllib.parse import urlencode

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PAYMENT_KEYS = frozenset({
    "CASSO_WEBHOOK_SECRET", "CASSO_BANK_ACCOUNT", "VIETQR_BANK_BIN",
    "VIETQR_ACCOUNT_NAME", "VIETQR_BANK_NAME",
})


def payment_setting(key: str) -> str:
    """Explicit process env wins. Never loads database or startup keys from .env."""
    if key not in PAYMENT_KEYS:
        raise ValueError("Unapproved payment setting")
    # Fail closed even if banking keys are accidentally supplied to a local
    # self-service profile. No profile approval or startup guard is changed.
    from app.core.operational_mode import configured_target
    policy = configured_target()
    if policy and policy.get("profile") == "local-dev-self-service-v1":
        return ""
    if key in os.environ:
        return os.environ[key].strip()
    values = dotenv_values(ROOT / ".env")
    return str(values.get(key) or "").strip()


@dataclass(frozen=True)
class Beneficiary:
    bin: str
    account_number: str
    account_name: str
    bank_name: str


def beneficiary() -> Beneficiary | None:
    bank_bin = payment_setting("VIETQR_BANK_BIN")
    account = payment_setting("CASSO_BANK_ACCOUNT")
    name = payment_setting("VIETQR_ACCOUNT_NAME")
    bank_name = payment_setting("VIETQR_BANK_NAME")
    if not bank_bin or not account or not name or not bank_name:
        return None
    if not re.fullmatch(r"[0-9]{6}", bank_bin) or not re.fullmatch(r"[0-9]{6,25}", account):
        return None
    if len(name) > 100 or len(bank_name) > 100:
        return None
    return Beneficiary(bank_bin, account, name, bank_name)


def qr_fields(gd_ma: str, amount: Decimal | int | float) -> dict:
    """QR is display-only; never evidence that an invoice was paid."""
    bank = beneficiary()
    if bank is None:
        return dict(vietqr_url=None, bank_account=None, bank_name=None,
                    account_name=None, transfer_content=None,
                    qr_payment_amount=None, qr_configured=False)
    try:
        rounded = payment_amount(amount)
    except ValueError:
        return dict(vietqr_url=None, bank_account=None, bank_name=None,
                    account_name=None, transfer_content=None,
                    qr_payment_amount=None, qr_configured=False)
    # The bank transfer is an integer amount in VND. Never truncate a 0.5 VND
    # remainder; display the rounded bank amount separately from the invoice.
    content = f"PETRO {gd_ma.strip()}"
    query = urlencode({"amount": int(rounded), "addInfo": content, "accountName": bank.account_name})
    return dict(
        vietqr_url=f"https://img.vietqr.io/image/{bank.bin}-{bank.account_number}-compact2.png?{query}",
        bank_account=bank.account_number, bank_name=bank.bank_name,
        account_name=bank.account_name, transfer_content=content,
        qr_payment_amount=int(rounded), qr_configured=True,
    )


_ORDER_ID = re.compile(r"(?<![A-Z0-9])GD[A-Z0-9]{6}(?![A-Z0-9])")
_DEBIT_MARKERS = {"DEBIT", "OUT", "DR", "DBIT", "MINUS", "OUTGOING", "TIEN_RA"}


def payment_amount(amount) -> Decimal:
    """One VND rounding contract for both QR display and bank reconciliation."""
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value <= 0 or value >= Decimal('100000000'):
            raise ValueError('Invalid payment amount')
        rounded = value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        if rounded <= 0:
            raise ValueError('Invalid payment amount')
        return rounded
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid payment amount') from None


def bank_transaction_id(value) -> str | None:
    # Never manufacture an ID, coerce an object/bool or truncate a bank TID.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    tid = str(value).strip()
    if not tid or len(tid) > 64 or any(ord(c) < 32 or ord(c) == 127 for c in tid):
        return None
    return tid


class CassoPayloadConflict(ValueError):
    """One authenticated batch assigns different financial data to one TID."""


def parse_casso_events(payload) -> tuple[list[dict], list[dict]]:
    """Fail closed on unverifiable entries; only bank receipt is allowed to settle.

    Provider-specific shape must be verified with a real Casso sandbox payload.
    """
    bank = beneficiary()
    if bank is None:
        return [], [dict(status='rejected', reason='beneficiary_unavailable')]
    if not isinstance(payload, dict) or payload.get("error") not in (None, 0):
        return [], [dict(status='rejected', reason='invalid_envelope')]
    raw = payload.get("data", [])
    entries = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    if not isinstance(raw, (dict, list)) or len(entries) > 500:
        return [], [dict(status='rejected', reason='invalid_batch')]
    result, rejected, seen = [], [], {}
    for index, item in enumerate(entries):
        def reject(reason):
            # Return diagnostics only to the authenticated sender. Do not echo
            # descriptions, bank accounts or tokens into responses/logs.
            rejected.append(dict(index=index, status='rejected', reason=reason,
                                 is_settled=False, audit_persisted=False))
        if not isinstance(item, dict):
            reject('invalid_entry')
            continue
        accounts = [str(item[k]).strip() for k in ('accountNumber', 'bank_sub_acc_id', 'subAccId')
                    if item.get(k) is not None and str(item[k]).strip()]
        actual_account = accounts[0] if accounts else ''
        # Do not auto-mark PAID unless the incoming destination account is verifiable.
        if not actual_account or set(accounts) != {bank.account_number}:
            reject('unverified_destination')
            continue
        indicators = (item.get(k) for k in ("type", "direction", "flow", "creditDebitIndicator", "transactionType"))
        if any(str(x).strip().upper() in _DEBIT_MARKERS for x in indicators if x is not None):
            reject('debit_not_receipt')
            continue
        try:
            amount = Decimal(str(item.get("amount", "")))
        except (InvalidOperation, ValueError):
            reject('invalid_amount')
            continue
        if not amount.is_finite() or amount <= 0 or amount >= Decimal('1000000000000'):
            reject('invalid_amount')
            continue
        description = str(item.get("description") or "").upper()
        codes = set(_ORDER_ID.findall(description))
        # A provider may supply a numeric id as well as a bank reference. Keep
        # the established V1 precedence; don't assert those aliases are equal.
        raw_tid = next((item[k] for k in ('tid', 'reference', 'id')
                        if item.get(k) is not None and item[k] != ''), None)
        tid = bank_transaction_id(raw_tid)
        signature = (tuple(sorted(codes)), amount)
        if tid:
            if tid in seen and seen[tid] != signature:
                raise CassoPayloadConflict('Conflicting bank transaction data')
            seen[tid] = signature
        if len(codes) != 1:
            reject('ambiguous_reference' if codes else 'invalid_reference')
            continue
        if not tid:
            reject('missing_or_invalid_bank_tid')
            continue
        result.append(dict(gd_ma=next(iter(codes)), amount=amount, tid=tid,
                           description=description, account_number=actual_account))
    return result, rejected


def validated_casso_events(payload) -> list[dict]:
    """Compatibility adapter; callers needing diagnostics use parse_casso_events."""
    return parse_casso_events(payload)[0]
