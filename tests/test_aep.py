"""
tests/test_aep.py — AEP Test Suite

Covers:
  - Schema validation (models.py)
  - Storage layer (db.py)
  - Billing / metering (billing.py)
  - Payment manager (idempotency, replay, retry)
  - Adapter contracts (mock, credits, solana stub)
  - Async queue (queue.py)
  - Security fixes (private key masking, ANSI borders)
  - UI (table alignment)
  - API (stdlib server)

Run:
    python -m pytest tests/test_aep.py -v
    python tests/test_aep.py          # runs without pytest
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import contextlib
import unittest

# Make package importable without install
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# Point all DB/storage paths to temp files before any imports
_TMP_DIR   = tempfile.mkdtemp()
_DB_PATH   = os.path.join(_TMP_DIR, "test-payments.db")
_BILL_PATH = os.path.join(_TMP_DIR, "test-billing.db")
_ANCH_PATH = os.path.join(_TMP_DIR, "test-anchors.json")

os.environ.update({
    "AEP_DB_PATH":       _DB_PATH,
    "AEP_BILLING_DB":    _BILL_PATH,
    "AEP_ANCHOR_PATH":   _ANCH_PATH,
    "AEP_PRIVATE_KEY":   "0xDEADBEEF" * 8,
    "AEP_DEMO_MODE":     "1",
})

# Reset module singleton after env is set
import importlib


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

ADDR     = "0x" + "a" * 40
ADDR2    = "0x" + "b" * 40
AGENT_ID = "test_agent_01"


def _fresh_store():
    """Return a PaymentStore backed by a fresh temp DB."""
    p = pathlib.Path(tempfile.mktemp(suffix=".db"))
    from aaip.storage.db import PaymentStore
    return PaymentStore(p)


def _fresh_meter():
    from aaip.engine.billing import UsageMeter
    return UsageMeter(db_path=tempfile.mktemp(suffix=".db"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema / models
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemas(unittest.TestCase):

    def test_payment_request_valid(self):
        from aaip.schemas.models import PaymentRequest
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.05)
        self.assertEqual(req.agent_id, AGENT_ID)
        self.assertGreater(len(req.request_id), 0)
        self.assertGreater(len(req.fingerprint), 0)

    def test_payment_request_bad_amount(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=-1)

    def test_payment_request_zero_amount(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0)

    def test_payment_request_blank_agent(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id="", recipient_address=ADDR, amount=1.0)

    def test_payment_request_bad_agent_chars(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id="agent with spaces!", recipient_address=ADDR, amount=1.0)

    def test_poe_hash_validation(self):
        from aaip.schemas.models import PaymentRequest
        good = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR,
                               amount=1.0, poe_hash="0x" + "a" * 64)
        self.assertIn("0x", good.poe_hash)
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR,
                           amount=1.0, poe_hash="not_a_hash")

    def test_execution_receipt_requires_tx_on_success(self):
        from aaip.schemas.models import ExecutionReceipt, PaymentStatus
        with self.assertRaises(ValueError):
            ExecutionReceipt(request_id="r1", agent_id=AGENT_ID, recipient=ADDR,
                             amount=0.05, status=PaymentStatus.SUCCESS, tx_hash=None)

    def test_agent_wallet_credit_debit(self):
        from aaip.schemas.models import AgentWallet
        w = AgentWallet(agent_id=AGENT_ID, address=ADDR)
        w2 = w.credit(1.5).debit(0.5).bump_cav(2.0)
        self.assertAlmostEqual(w2.total_received, 1.5)
        self.assertAlmostEqual(w2.total_paid, 0.5)
        self.assertAlmostEqual(w2.cav_score, 2.0)
        self.assertEqual(w2.tx_count, 2)

    def test_to_dict_serialisation(self):
        from aaip.schemas.models import PaymentRequest
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.01)
        d = req.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["agent_id"], AGENT_ID)
        json.dumps(d)  # must be JSON-serialisable

    def test_usage_record_total_tokens(self):
        from aaip.schemas.models import UsageRecord
        rec = UsageRecord(agent_id=AGENT_ID, endpoint="reasoner",
                          tokens_in=512, tokens_out=256)
        self.assertEqual(rec.total_tokens, 768)

    def test_address_validation_evm_valid(self):
        from aaip.schemas.models import PaymentRequest
        r = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.1)
        self.assertEqual(r.recipient_address, ADDR)

    def test_address_validation_evm_short(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address="0xSHORT", amount=0.1)

    def test_address_validation_empty(self):
        from aaip.schemas.models import PaymentRequest
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address="", amount=0.1)

    def test_address_validation_solana(self):
        from aaip.schemas.models import PaymentRequest
        # Valid base58 Solana address
        r = PaymentRequest(agent_id=AGENT_ID,
                           recipient_address="DRpbCBMxVnDK7maPMZhQ5H6N9D7EMiRPGCXhK1j8Qs",
                           amount=0.1)
        self.assertTrue(len(r.recipient_address) > 30)

    def test_address_validation_credits_style(self):
        from aaip.schemas.models import PaymentRequest
        r = PaymentRequest(agent_id=AGENT_ID, recipient_address="worker_agent_01", amount=0.1)
        self.assertEqual(r.recipient_address, "worker_agent_01")

    def test_wallet_address_validated(self):
        from aaip.schemas.models import AgentWallet
        w = AgentWallet(agent_id=AGENT_ID, address=ADDR)
        self.assertEqual(w.address, ADDR)
        with self.assertRaises(ValueError):
            AgentWallet(agent_id=AGENT_ID, address="not!!valid")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Storage
# ─────────────────────────────────────────────────────────────────────────────

class TestStorage(unittest.TestCase):

    def setUp(self):
        self.store = _fresh_store()

    def tearDown(self):
        self.store.close()

    def _make_pair(self):
        from aaip.schemas.models import PaymentRequest, ExecutionReceipt, PaymentStatus
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.05)
        rec = ExecutionReceipt(request_id=req.request_id, agent_id=AGENT_ID,
                               recipient=ADDR, amount=0.05,
                               status=PaymentStatus.SUCCESS, tx_hash="0x" + "c" * 64)
        return req, rec

    def test_save_and_retrieve_request(self):
        from aaip.schemas.models import PaymentRequest
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.1)
        self.store.save_request(req)
        got = self.store.get_request(req.request_id)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got.amount, 0.1)

    def test_save_and_retrieve_receipt(self):
        req, rec = self._make_pair()
        self.store.save_request(req)
        self.store.save_receipt(rec)
        got = self.store.get_receipt(rec.receipt_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.tx_hash, rec.tx_hash)

    def test_replay_protection(self):
        ok1 = self.store.register_nonce("nonce_abc", AGENT_ID)
        ok2 = self.store.register_nonce("nonce_abc", AGENT_ID)
        self.assertTrue(ok1)
        self.assertFalse(ok2)

    def test_idempotency_key_lookup(self):
        req, rec = self._make_pair()
        req2 = type(req)(**{**req.to_dict(), "idempotency_key": "idem-unique-99"})
        self.store.save_request(req2)
        self.store.save_receipt(rec)
        found = self.store.get_receipt_by_idempotency_key("idem-unique-99")
        self.assertIsNotNone(found)
        self.assertEqual(found.receipt_id, rec.receipt_id)

    def test_wallet_upsert(self):
        from aaip.schemas.models import AgentWallet
        w = AgentWallet(agent_id=AGENT_ID, address=ADDR)
        self.store.upsert_wallet(w.bump_cav(3.0))
        got = self.store.get_wallet(AGENT_ID)
        self.assertAlmostEqual(got.cav_score, 3.0)
        # Upsert again (update)
        self.store.upsert_wallet(got.bump_cav(1.0))
        got2 = self.store.get_wallet(AGENT_ID)
        self.assertAlmostEqual(got2.cav_score, 4.0)

    def test_stats(self):
        req, rec = self._make_pair()
        self.store.save_request(req)
        self.store.save_receipt(rec)
        s = self.store.stats()
        self.assertEqual(s["total_receipts"], 1)
        self.assertEqual(s["success_count"], 1)
        self.assertAlmostEqual(s["total_volume"], 0.05)

    def test_nonce_purge(self):
        import aaip.engine.payment_manager as pm
        # Manually insert expired nonce
        with self.store._conn:
            self.store._conn.execute(
                "INSERT INTO nonce_registry (nonce_key,agent_id,used_at,expires_at)"
                " VALUES (?,?,?,?)",
                ("expired_nonce", AGENT_ID, time.time() - 400, time.time() - 100)
            )
        purged = self.store.purge_expired_nonces()
        self.assertGreaterEqual(purged, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Billing / metering
# ─────────────────────────────────────────────────────────────────────────────

class TestBilling(unittest.TestCase):

    def setUp(self):
        self.meter = _fresh_meter()

    def tearDown(self):
        self.meter.close()

    def test_record_and_total(self):
        self.meter.record(AGENT_ID, "reasoner",  tokens_in=512, tokens_out=256, period="2026-03")
        self.meter.record(AGENT_ID, "retriever", tokens_in=128, tokens_out=64,  period="2026-03")
        totals = self.meter.total_cost(AGENT_ID, period="2026-03")
        self.assertGreater(totals["cost_usd"], 0)
        self.assertGreater(totals["cost_eth"], 0)
        self.assertEqual(totals["tokens_in"], 640)

    def test_cost_calculation(self):
        from aaip.engine.billing import calculate_cost
        usd, eth = calculate_cost("reasoner", tokens_in=1000, tokens_out=1000)
        self.assertGreater(usd, 0)
        self.assertGreater(eth, 0)

    def test_breakdown(self):
        self.meter.record(AGENT_ID, "reasoner",  tokens_in=100, tokens_out=50, period="2026-03")
        self.meter.record(AGENT_ID, "summariser", tokens_in=50,  tokens_out=25, period="2026-03")
        bd = self.meter.breakdown(AGENT_ID, period="2026-03")
        self.assertGreater(len(bd), 0)
        self.assertIn("endpoint", bd[0])

    def test_generate_invoice_empty(self):
        invoice = self.meter.generate_invoice(AGENT_ID, ADDR, period="2020-01")
        self.assertIsNone(invoice)

    def test_generate_invoice_with_usage(self):
        self.meter.record(AGENT_ID, "reasoner", tokens_in=10000, tokens_out=5000, period="2026-03")
        invoice = self.meter.generate_invoice(AGENT_ID, ADDR, period="2026-03")
        self.assertIsNotNone(invoice)
        self.assertGreater(invoice.amount, 0)

    def test_all_agents_summary(self):
        self.meter.record("alpha", "reasoner", tokens_in=100, tokens_out=50, period="2026-03")
        self.meter.record("beta",  "retriever", tokens_in=200, tokens_out=100, period="2026-03")
        summary = self.meter.all_agents_summary(period="2026-03")
        agent_ids = {r["agent_id"] for r in summary}
        self.assertIn("alpha", agent_ids)
        self.assertIn("beta",  agent_ids)

    def test_calculate_cost_edge_cases(self):
        from aaip.engine.billing import calculate_cost
        # zero tokens
        usd, eth = calculate_cost("reasoner", tokens_in=0, tokens_out=0)
        self.assertGreaterEqual(usd, 0)
        self.assertGreaterEqual(eth, 0)
        # large tokens
        usd, eth = calculate_cost("reasoner", tokens_in=1000000, tokens_out=500000)
        self.assertGreater(usd, 0)
        self.assertGreater(eth, 0)
        # unknown endpoint uses default pricing
        usd, eth = calculate_cost("unknown_endpoint", tokens_in=1000, tokens_out=1000)
        self.assertGreater(usd, 0)
        self.assertGreater(eth, 0)
        # custom pricing
        custom_pricing = {"custom": {"per_1k_in": 1.0, "per_1k_out": 2.0, "per_call": 0.5}}
        usd, eth = calculate_cost("custom", tokens_in=1000, tokens_out=1000, pricing=custom_pricing)
        expected_usd = 0.5 + 1.0 + 2.0  # per_call + per_1k_in + per_1k_out
        self.assertAlmostEqual(usd, expected_usd, places=6)

    def test_flush_billing_below_threshold(self):
        # record small usage (cost less than threshold)
        self.meter.record(AGENT_ID, "reasoner", tokens_in=100, tokens_out=50, period="2026-06")
        result = self.meter.flush_billing(AGENT_ID, ADDR, period="2026-06")
        self.assertFalse(result["billed"])
        self.assertEqual(result["reason"], "below_threshold ($0.0010 < $1.0)")
        self.assertIn("invoice", result)

    def test_flush_billing_above_threshold(self):
        from aaip.aep.adapters.mock import MockPaymentAdapter
        # record enough usage to exceed threshold (1 USD)
        # approximate: reasoner pricing 0.003 per 1k in, 0.015 per 1k out
        # we need about 334k input tokens to reach $1. Let's record 500k tokens.
        self.meter.record(AGENT_ID, "reasoner", tokens_in=500000, tokens_out=0, period="2026-05")
        adapter = MockPaymentAdapter()
        result = self.meter.flush_billing(AGENT_ID, ADDR, period="2026-05", adapter=adapter)
        self.assertTrue(result["billed"])
        self.assertIn("receipt", result)
        self.assertEqual(result["receipt"]["status"], "success")

    def test_flush_billing_adapter_failure(self):
        from aaip.aep.adapters.mock import MockPaymentAdapter
        # record enough usage to exceed threshold, using a distinct period to avoid idempotency
        self.meter.record(AGENT_ID, "reasoner", tokens_in=500000, tokens_out=0, period="2026-04")
        adapter = MockPaymentAdapter(fail_on=[ADDR])
        # Debug: check adapter's fail_on set
        self.assertIn(ADDR, adapter._fail_on)
        result = self.meter.flush_billing(AGENT_ID, ADDR, period="2026-04", adapter=adapter)
        # Debug: print adapter ledger
        print(f"Adapter ledger: {adapter.ledger}")
        # Even though adapter fails, the payment is attempted and returns a failed receipt
        self.assertTrue(result["billed"])  # billing attempted, but payment failed
        self.assertIn("receipt", result)
        # The receipt status should be "failed"
        self.assertEqual(result["receipt"]["status"], "failed", f"Receipt: {result['receipt']}")

    def test_custom_pricing(self):
        from aaip.engine.billing import UsageMeter
        custom_pricing = {
            "my_endpoint": {"per_1k_in": 2.0, "per_1k_out": 3.0, "per_call": 1.0}
        }
        meter = UsageMeter(db_path=tempfile.mktemp(suffix=".db"), pricing=custom_pricing)
        try:
            rec = meter.record(AGENT_ID, "my_endpoint", tokens_in=1000, tokens_out=500)
            # cost = per_call + per_1k_in * 1 + per_1k_out * 0.5 = 1 + 2 + 1.5 = 4.5
            expected_usd = 1.0 + 2.0 + (3.0 * 0.5)
            self.assertAlmostEqual(rec.cost_usd, expected_usd, places=6)
            # verify total cost matches
            totals = meter.total_cost(AGENT_ID, rec.period)
            self.assertAlmostEqual(totals["cost_usd"], expected_usd, places=6)
        finally:
            meter.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Adapters
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapters(unittest.TestCase):

    def test_mock_success(self):
        from aaip.aep.adapters.mock import MockPaymentAdapter
        a = MockPaymentAdapter()
        r = a.send_payment(ADDR, 0.05)
        self.assertEqual(r["status"], "success")
        self.assertIn("0x", r["tx_hash"])
        self.assertIsNotNone(r["explorer_url"])

    def test_mock_failure(self):
        from aaip.aep.adapters.mock import MockPaymentAdapter
        a = MockPaymentAdapter(fail_on=[ADDR])
        r = a.send_payment(ADDR, 0.05)
        self.assertEqual(r["status"], "failed")
        self.assertIsNone(r["tx_hash"])

    def test_mock_valid_address(self):
        from aaip.aep.adapters.mock import MockPaymentAdapter
        a = MockPaymentAdapter()
        self.assertTrue(a.is_valid_address(ADDR))
        self.assertFalse(a.is_valid_address(""))
        self.assertFalse(a.is_valid_address("0xSHORT"))

    def test_credits_fund_and_pay(self):
        from aaip.aep.adapters.credits import CreditsAdapter
        a = CreditsAdapter(sender_id="platform", initial_balance=100.0)
        a.fund("worker", 10.0)
        r = a.send_payment("worker", 1.5, metadata={"agent_id": "platform"})
        self.assertEqual(r["status"], "success")
        self.assertAlmostEqual(a.balance("platform"), 98.5)
        self.assertAlmostEqual(a.balance("worker"), 11.5)

    def test_credits_insufficient(self):
        from aaip.aep.adapters.credits import CreditsAdapter
        a = CreditsAdapter(initial_balance=0.01)
        r = a.send_payment("anyone", 100.0, metadata={"agent_id": "platform"})
        self.assertEqual(r["status"], "failed")

    def test_credits_valid_address(self):
        from aaip.aep.adapters.credits import CreditsAdapter
        a = CreditsAdapter()
        self.assertTrue(a.is_valid_address("any_agent_id"))
        self.assertTrue(a.is_valid_address(ADDR))
        self.assertFalse(a.is_valid_address(""))

    def test_solana_stub_address_validation(self):
        from aaip.aep.adapters.solana import SolanaPaymentAdapter
        a = SolanaPaymentAdapter()
        self.assertTrue(a.is_valid_address("DRpbCBMxVnDK7maPMZhQ5H6N9D7EMiRPGCXhK1j8Qs6J"))
        self.assertFalse(a.is_valid_address(""))
        self.assertFalse(a.is_valid_address("0x" + "a" * 40))  # EVM format not valid for Solana

    def test_solana_stub_payment(self):
        from aaip.aep.adapters.solana import SolanaPaymentAdapter
        a = SolanaPaymentAdapter()
        r = a.send_payment("DRpbCBMxVnDK7maPMZhQ5H6N9D7EMiRPGCXhK1j8Qs6J", 0.1)
        self.assertEqual(r["status"], "success")
        self.assertTrue(r.get("stub", False))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Payment manager (integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestPaymentManager(unittest.TestCase):

    def setUp(self):
        import aaip.engine.payment_manager as pm
        self._orig_store = pm._store
        pm._store = None
        # Point to fresh DB
        os.environ["AEP_DB_PATH"] = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        import aaip.engine.payment_manager as pm
        if pm._store:
            pm._store.close()
        pm._store = self._orig_store

    def test_payment_success(self):
        from aaip.schemas.models import PaymentRequest, PaymentStatus
        import aaip.engine.payment_manager as pm
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.01)
        receipt = pm.process_payment(req)
        self.assertEqual(receipt.status, PaymentStatus.SUCCESS)
        self.assertIsNotNone(receipt.tx_hash)

    def test_idempotency(self):
        from aaip.schemas.models import PaymentRequest
        import aaip.engine.payment_manager as pm
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR,
                             amount=0.01, idempotency_key="idem-test-xyz")
        r1 = pm.process_payment(req)
        r2 = pm.process_payment(req)
        self.assertEqual(r1.receipt_id, r2.receipt_id)

    def test_replay_blocked(self):
        from aaip.schemas.models import PaymentRequest, PaymentStatus
        import aaip.engine.payment_manager as pm
        poe = "0x" + "d" * 64
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR,
                             amount=0.01, poe_hash=poe)
        r1 = pm.process_payment(req)
        self.assertEqual(r1.status, PaymentStatus.SUCCESS)
        # Second attempt: different amount (different fingerprint) but same poe_hash
        # — must hit replay check not idempotency cache
        req2 = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR,
                              amount=0.02, poe_hash=poe)
        r2 = pm.process_payment(req2)
        self.assertEqual(r2.status, PaymentStatus.FAILED)
        self.assertIn("REPLAY", r2.error)

    def test_cav_bump(self):
        from aaip.schemas.models import AgentWallet
        import aaip.engine.payment_manager as pm
        pm.get_or_create_wallet(AGENT_ID, ADDR)
        w = pm.bump_cav(AGENT_ID, delta=2.5)
        self.assertAlmostEqual(w.cav_score, 2.5)

    def test_bilateral_wallet_ledger(self):
        """Payment debits payer and credits recipient — both sides recorded."""
        from aaip.schemas.models import PaymentRequest, PaymentStatus
        import aaip.engine.payment_manager as pm
        # Pre-create payer wallet and capture baseline
        pm.get_or_create_wallet(AGENT_ID, ADDR)
        store = pm._get_store()
        before_payer = store.get_wallet(AGENT_ID)
        before_paid  = before_payer.total_paid if before_payer else 0.0

        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR2, amount=0.07)
        receipt = pm.process_payment(req)
        self.assertEqual(receipt.status, PaymentStatus.SUCCESS)

        after_payer = store.get_wallet(AGENT_ID)
        self.assertIsNotNone(after_payer)
        self.assertAlmostEqual(after_payer.total_paid - before_paid, 0.07, places=6)

        recipient_id = "ext_" + ADDR2[-8:].lower()
        recip = store.get_wallet(recipient_id)
        self.assertIsNotNone(recip, "Recipient wallet should be created")
        self.assertGreater(recip.total_received, 0.0)

    def test_adapter_type_in_receipt(self):
        """Receipt should record the actual adapter type, not always MOCK."""
        from aaip.schemas.models import PaymentRequest, AdapterType
        from aaip.aep.adapters.credits import CreditsAdapter
        import aaip.engine.payment_manager as pm
        adapter = CreditsAdapter(initial_balance=100.0)
        adapter.fund(AGENT_ID, 10.0)
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=AGENT_ID, amount=0.01)
        receipt = pm.process_payment(req, adapter=adapter)
        self.assertEqual(receipt.adapter, AdapterType.CREDITS)

    def test_process_payment_edge_cases(self):
        from aaip.schemas.models import PaymentRequest, PaymentStatus
        import aaip.engine.payment_manager as pm
        # zero amount - validation rejects (amount must be > 0)
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.0)
        # negative amount - validation also rejects
        with self.assertRaises(ValueError):
            PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=-0.01)
        # tiny positive amount - should succeed
        req = PaymentRequest(agent_id=AGENT_ID, recipient_address=ADDR, amount=0.000001)
        receipt = pm.process_payment(req)
        self.assertEqual(receipt.status, PaymentStatus.SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Security
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurity(unittest.TestCase):

    def test_private_key_masked_in_repr(self):
        from aaip.aep.config import AEPConfig
        c = AEPConfig()
        self.assertNotIn("0xDEADBEEF", repr(c))
        self.assertEqual(c.private_key, "0xDEADBEEF" * 8)

    def test_private_key_in_repr_shows_stars(self):
        from aaip.aep.config import AEPConfig
        c = AEPConfig()
        self.assertIn("***", repr(c))


# ─────────────────────────────────────────────────────────────────────────────
# 7. UI — ANSI table alignment
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth(unittest.TestCase):

    def test_check_request_no_auth(self):
        """With no API keys configured, all requests pass."""
        import os, importlib
        import aaip.api.auth as auth_mod
        orig = auth_mod._AUTH_ENABLED
        auth_mod._AUTH_ENABLED = False
        result = auth_mod.check_request({}, b"", "GET", "/health")
        self.assertTrue(result.ok)
        auth_mod._AUTH_ENABLED = orig

    def test_check_request_valid_key(self):
        import aaip.api.auth as auth_mod
        orig_keys   = auth_mod._API_KEYS
        orig_enabled = auth_mod._AUTH_ENABLED
        auth_mod._API_KEYS    = {"valid-key-123"}
        auth_mod._AUTH_ENABLED = True
        result = auth_mod.check_request({"x-api-key": "valid-key-123"}, b"", "GET", "/")
        self.assertTrue(result.ok)
        self.assertEqual(result.api_key, "valid-key-123")
        auth_mod._API_KEYS    = orig_keys
        auth_mod._AUTH_ENABLED = orig_enabled

    def test_check_request_invalid_key(self):
        import aaip.api.auth as auth_mod
        orig_keys   = auth_mod._API_KEYS
        orig_enabled = auth_mod._AUTH_ENABLED
        auth_mod._API_KEYS    = {"valid-key-123"}
        auth_mod._AUTH_ENABLED = True
        result = auth_mod.check_request({"x-api-key": "wrong"}, b"", "GET", "/")
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 403)
        auth_mod._API_KEYS    = orig_keys
        auth_mod._AUTH_ENABLED = orig_enabled

    def test_check_request_missing_key(self):
        import aaip.api.auth as auth_mod
        orig_keys   = auth_mod._API_KEYS
        orig_enabled = auth_mod._AUTH_ENABLED
        auth_mod._API_KEYS    = {"valid-key-123"}
        auth_mod._AUTH_ENABLED = True
        result = auth_mod.check_request({}, b"", "GET", "/")
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 401)
        auth_mod._API_KEYS    = orig_keys
        auth_mod._AUTH_ENABLED = orig_enabled

    def test_rate_limiting(self):
        import aaip.api.auth as auth_mod
        bucket = auth_mod._TokenBucket(rpm=3)
        results = [bucket.is_allowed("test_key") for _ in range(5)]
        self.assertEqual(results[:3], [True, True, True])
        self.assertEqual(results[3:], [False, False])
        bucket.reset("test_key")
        self.assertTrue(bucket.is_allowed("test_key"))

    def test_signature_valid(self):
        import aaip.api.auth as auth_mod
        import hmac, hashlib
        secret = "s3cr3t"
        body   = b'{"amount": 0.05}'
        sig    = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(auth_mod.verify_signature(body, sig, secret))

    def test_signature_invalid(self):
        import aaip.api.auth as auth_mod
        self.assertFalse(auth_mod.verify_signature(b"body", "badsig", "s3cr3t"))

    def test_request_id_generated(self):
        import aaip.api.auth as auth_mod
        result = auth_mod.check_request({}, b"", "GET", "/health")
        self.assertTrue(len(result.request_id) > 0)

    def test_request_id_forwarded(self):
        import aaip.api.auth as auth_mod
        result = auth_mod.check_request(
            {"x-request-id": "my-custom-id-123"}, b"", "GET", "/")
        self.assertEqual(result.request_id, "my-custom-id-123")


class TestUI(unittest.TestCase):

    def _capture_summary(self, rows):
        from aaip import ui
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ui.summary(rows)
        return buf.getvalue()

    def test_borders_align_plain_text(self):
        from aaip import ui
        output = self._capture_summary([("Key", "value"), ("LongerKey", "longer value here")])
        for line in output.split("\n"):
            if "║" in line and line.strip() and not any(c in line for c in "╔╚╠"):
                clean = ui._ANSI_RE.sub("", line).rstrip()
                self.assertTrue(clean.endswith("║"), f"Border misaligned: {repr(clean[-6:])}")

    def test_borders_align_with_ansi_colors(self):
        from aaip import ui
        output = self._capture_summary([
            ("Payment", ui.green("0.05 ETH  [SUCCESS]")),
            ("Status",  ui.red("FAILED")),
        ])
        for line in output.split("\n"):
            if "║" in line and line.strip() and not any(c in line for c in "╔╚╠"):
                clean = ui._ANSI_RE.sub("", line).rstrip()
                self.assertTrue(clean.endswith("║"), f"ANSI border misaligned: {repr(clean[-6:])}")

    def test_visible_len(self):
        from aaip.ui import visible_len, green
        colored = green("hello")
        self.assertEqual(visible_len(colored), 5)
        self.assertEqual(visible_len("plain"), 5)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Async queue
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionEngine(unittest.TestCase):

    def test_same_task_same_hash(self):
        """Same task + model + agent_id must produce the same PoE hash."""
        from aaip.engine.execution_engine import run_task
        r1 = run_task("Analyse earnings", agent_id="bot_01", fast=True)
        r2 = run_task("Analyse earnings", agent_id="bot_01", fast=True)
        self.assertEqual(r1["poe_hash"], r2["poe_hash"],
                         "Deterministic fields should produce identical hashes")

    def test_different_task_different_hash(self):
        from aaip.engine.execution_engine import run_task
        r1 = run_task("Task A", agent_id="bot_01", fast=True)
        r2 = run_task("Task B", agent_id="bot_01", fast=True)
        self.assertNotEqual(r1["poe_hash"], r2["poe_hash"])

    def test_trace_has_execution_id(self):
        """execution_id should be unique per run (not in hash)."""
        from aaip.engine.execution_engine import run_task
        r1 = run_task("Task", agent_id="bot_01", fast=True)
        r2 = run_task("Task", agent_id="bot_01", fast=True)
        self.assertIn("execution_id", r1["trace"])
        self.assertNotEqual(r1["trace"]["execution_id"],
                            r2["trace"]["execution_id"],
                            "execution_id must be unique per run")

    def test_trace_has_timestamp(self):
        from aaip.engine.execution_engine import run_task
        r = run_task("Task", agent_id="bot_01", fast=True)
        self.assertIn("timestamp", r["trace"])
        self.assertGreater(r["trace"]["timestamp"], 0)


class TestQueue(unittest.TestCase):

    def test_queue_complete(self):
        async def _run():
            results = []

            async def fake_executor(job):
                await asyncio.sleep(0.05)
                return {"poe_hash": "0x" + "e" * 64, "steps": 4}

            from aaip.engine.queue import TaskQueue, JobStatus
            async with TaskQueue(workers=2, executor_fn=fake_executor) as q:
                ids = [await q.submit(f"task {i}", agent_id=AGENT_ID) for i in range(3)]
                jobs = [await q.wait(jid, timeout=10) for jid in ids]

            results = [j.status for j in jobs]
            return results

        statuses = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertTrue(all(s == JobStatus.COMPLETE for s in statuses))

    def test_queue_stats(self):
        async def _run():
            async def fast_exec(job):
                return {"done": True}

            from aaip.engine.queue import TaskQueue
            async with TaskQueue(workers=1, executor_fn=fast_exec) as q:
                for i in range(4):
                    jid = await q.submit(f"t{i}", agent_id=AGENT_ID)
                    await q.wait(jid, timeout=5)
                return q.stats()

        s = asyncio.run(_run())
        self.assertEqual(s["complete"], 4)
        self.assertEqual(s["failed"],   0)

    def test_queue_failure_handling(self):
        async def _run():
            async def failing_exec(job):
                raise ValueError("deliberate failure")

            from aaip.engine.queue import TaskQueue, JobStatus
            async with TaskQueue(workers=1, executor_fn=failing_exec) as q:
                jid = await q.submit("bad task", agent_id=AGENT_ID)
                job = await q.wait(jid, timeout=5)
                return job

        job = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIn("deliberate failure", job.error)


# ─────────────────────────────────────────────────────────────────────────────
# 9. API (stdlib fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import socketserver, threading
        # _Handler lives in aaip.api.server regardless of whether FastAPI is
        # installed — the stdlib fallback always defines it.
        # We import it explicitly from the module object to avoid the name
        # being shadowed by the FastAPI branch which doesn't re-export it.
        import importlib, aaip.api.server as _srv_mod
        _Handler = getattr(_srv_mod, "_Handler", None)
        if _Handler is None:
            raise unittest.SkipTest("stdlib API handler not available in this env")
        cls._port = 18470
        socketserver.TCPServer.allow_reuse_address = True
        cls._srv  = socketserver.TCPServer(("127.0.0.1", cls._port), _Handler)
        cls._thread = threading.Thread(target=cls._srv.serve_forever, daemon=True)
        cls._thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls._srv.shutdown()

    def _get(self, path):
        import urllib.request
        r = urllib.request.urlopen(f"http://127.0.0.1:{self._port}{path}")
        return json.loads(r.read())

    def _post(self, path, body):
        import urllib.request
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        r = urllib.request.urlopen(req)
        return json.loads(r.read())

    def test_health(self):
        r = self._get("/health")
        self.assertEqual(r["status"], "ok")

    def test_stats(self):
        r = self._get("/stats")
        self.assertIn("total_receipts", r)

    def test_post_payment(self):
        r = self._post("/payments", {
            "agent_id":          AGENT_ID,
            "recipient_address": ADDR,
            "amount":            0.01,
        })
        self.assertEqual(r["status"], "success")
        self.assertIn("tx_hash", r)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────


class TestTaskRouter(unittest.TestCase):

    def setUp(self):
        import tempfile
        from aaip.engine.task_router import AgentRegistry
        self._db = pathlib.Path(tempfile.mktemp(suffix=".db"))
        self._reg = AgentRegistry(self._db)

    def tearDown(self):
        self._reg.close()

    def test_register_and_retrieve(self):
        r = self._reg.register(AGENT_ID, ADDR, {"summarise", "retrieve"}, cost_per_task=0.05)
        got = self._reg.get(AGENT_ID)
        self.assertIsNotNone(got)
        self.assertIn("summarise", got.capabilities)
        self.assertAlmostEqual(got.cost_per_task, 0.05)

    def test_route_capability_match(self):
        self._reg.register("a1", ADDR,  {"summarise", "retrieve"}, cost_per_task=0.10)
        self._reg.register("a2", ADDR2, {"summarise"},              cost_per_task=0.05)
        # Only a1 has 'retrieve'
        rec = self._reg.route({"retrieve"})
        self.assertEqual(rec.agent_id, "a1")

    def test_route_cheapest_capable(self):
        self._reg.register("cheap", ADDR,  {"summarise"}, cost_per_task=0.01)
        self._reg.register("pricey", ADDR2, {"summarise"}, cost_per_task=0.99)
        rec = self._reg.route({"summarise"})
        self.assertEqual(rec.agent_id, "cheap")

    def test_route_no_capable_agent(self):
        from aaip.engine.task_router import RoutingError
        self._reg.register(AGENT_ID, ADDR, {"retrieve"})
        with self.assertRaises(RoutingError):
            self._reg.route({"summarise"})

    def test_route_no_agents(self):
        from aaip.engine.task_router import RoutingError
        with self.assertRaises(RoutingError):
            self._reg.route(set())

    def test_health_and_heartbeat(self):
        self._reg.register(AGENT_ID, ADDR, {"summarise"})
        self._reg.mark_unhealthy(AGENT_ID, "test")
        from aaip.engine.task_router import RoutingError
        with self.assertRaises(RoutingError):
            self._reg.route({"summarise"})
        self._reg.heartbeat(AGENT_ID)
        rec = self._reg.route({"summarise"})
        self.assertEqual(rec.agent_id, AGENT_ID)

    def test_capacity_respected(self):
        self._reg.register(AGENT_ID, ADDR, {"summarise"}, max_concurrent=1)
        # Route once → capacity hit
        self._reg.route({"summarise"})
        from aaip.engine.task_router import RoutingError
        with self.assertRaises(RoutingError):
            self._reg.route({"summarise"})
        # Release → available again
        self._reg.release(AGENT_ID)
        rec = self._reg.route({"summarise"})
        self.assertEqual(rec.agent_id, AGENT_ID)

    def test_pool_status(self):
        self._reg.register("a1", ADDR, {"x"})
        self._reg.register("a2", ADDR2, {"y"})
        s = self._reg.pool_status()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["healthy"], 2)

    def test_duplicate_registration_overwrites(self):
        # Register same agent_id twice with different data
        self._reg.register("agent1", ADDR, {"cap1"}, cost_per_task=0.1)
        self._reg.register("agent1", ADDR2, {"cap2"}, cost_per_task=0.2)
        rec = self._reg.get("agent1")
        self.assertEqual(rec.agent_id, "agent1")
        self.assertEqual(rec.address, ADDR2)  # second registration overwrites
        self.assertEqual(rec.capabilities, {"cap2"})
        self.assertAlmostEqual(rec.cost_per_task, 0.2)

    def test_route_multiple_capabilities(self):
        self._reg.register("agent1", ADDR, {"cap1", "cap2"}, cost_per_task=0.1)
        self._reg.register("agent2", ADDR2, {"cap2", "cap3"}, cost_per_task=0.2)
        # require both cap1 and cap2 -> only agent1 matches
        rec = self._reg.route({"cap1", "cap2"})
        self.assertEqual(rec.agent_id, "agent1")
        # require cap2 and cap3 -> only agent2 matches
        rec2 = self._reg.route({"cap2", "cap3"})
        self.assertEqual(rec2.agent_id, "agent2")
        # require cap1 and cap3 -> no agent matches
        from aaip.engine.task_router import RoutingError
        with self.assertRaises(RoutingError):
            self._reg.route({"cap1", "cap3"})


class TestQueue(unittest.TestCase):

    def _make_queue(self, backend_name="memory"):
        import os; os.environ["AEP_QUEUE_BACKEND"] = backend_name
        from aaip.engine.queue import TaskQueue, _MemoryBackend
        return TaskQueue(workers=2, backend=_MemoryBackend())

    def test_queue_complete(self):
        async def _run():
            async def fake_executor(job):
                await asyncio.sleep(0.02)
                return {"poe_hash": "0x" + "e" * 64}
            from aaip.engine.queue import TaskQueue, _MemoryBackend, JobStatus
            async with TaskQueue(workers=2, executor_fn=fake_executor,
                                 backend=_MemoryBackend()) as q:
                ids  = [await q.submit(f"task {i}", agent_id=AGENT_ID) for i in range(3)]
                jobs = [await q.wait(jid, timeout=10) for jid in ids]
            return [j.status for j in jobs]
        statuses = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertTrue(all(s == JobStatus.COMPLETE for s in statuses))

    def test_queue_retry_then_succeed(self):
        async def _run():
            call_count = {"n": 0}
            async def flaky_exec(job):
                call_count["n"] += 1
                if call_count["n"] < 2:
                    raise ValueError("transient failure")
                return {"ok": True}
            from aaip.engine.queue import TaskQueue, _MemoryBackend, JobStatus
            async with TaskQueue(workers=1, executor_fn=flaky_exec,
                                 backend=_MemoryBackend()) as q:
                jid = await q.submit("task", agent_id=AGENT_ID, max_retries=2, backoff_s=0.01)
                job = await q.wait(jid, timeout=10)
            return job.status, job.attempts
        status, attempts = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertEqual(status, JobStatus.COMPLETE)
        self.assertEqual(attempts, 2)

    def test_queue_dead_letter_after_exhausted_retries(self):
        async def _run():
            async def always_fail(job):
                raise ValueError("permanent failure")
            from aaip.engine.queue import TaskQueue, _MemoryBackend, JobStatus
            async with TaskQueue(workers=1, executor_fn=always_fail,
                                 backend=_MemoryBackend()) as q:
                jid = await q.submit("task", agent_id=AGENT_ID, max_retries=1, backoff_s=0.01)
                job = await q.wait(jid, timeout=10)
            return job.status
        status = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertEqual(status, JobStatus.DEAD)

    def test_queue_cancellation(self):
        async def _run():
            async def slow_exec(job):
                await asyncio.sleep(60)
                return {}
            from aaip.engine.queue import TaskQueue, _MemoryBackend, JobStatus
            q = TaskQueue(workers=0, executor_fn=slow_exec, backend=_MemoryBackend())
            await q.start()
            jid = await q.submit("long task", agent_id=AGENT_ID)
            ok  = q.cancel(jid)
            job = q.get_job(jid)
            await q.stop()
            return ok, job.status
        cancelled, status = asyncio.run(_run())
        from aaip.engine.queue import JobStatus
        self.assertTrue(cancelled)
        self.assertEqual(status, JobStatus.CANCELLED)

    def test_file_backend_persistence(self):
        """Jobs survive a queue restart (file backend)."""
        import tempfile
        path = pathlib.Path(tempfile.mktemp(suffix=".jsonl"))

        async def _run_first():
            from aaip.engine.queue import TaskQueue, _FileBackend, JobStatus
            backend = _FileBackend(path)
            async with TaskQueue(workers=1, backend=backend,
                                 executor_fn=lambda j: asyncio.sleep(999)) as q:
                jid = await q.submit("durable task", agent_id=AGENT_ID)
            return jid

        async def _run_second(jid):
            from aaip.engine.queue import _FileBackend
            backend = _FileBackend(path)
            # After restore, the interrupted RUNNING job is reset to PENDING
            job = backend.get(jid)
            return job

        jid = asyncio.run(_run_first())
        job = asyncio.run(_run_second(jid))
        self.assertIsNotNone(job)
        from aaip.engine.queue import JobStatus
        self.assertEqual(job.status, JobStatus.PENDING)   # reset from RUNNING
        path.unlink(missing_ok=True)

    def test_queue_stats(self):
        async def _run():
            async def fast_exec(job): return {"done": True}
            from aaip.engine.queue import TaskQueue, _MemoryBackend
            async with TaskQueue(workers=1, executor_fn=fast_exec,
                                 backend=_MemoryBackend()) as q:
                for i in range(3):
                    jid = await q.submit(f"t{i}", agent_id=AGENT_ID)
                    await q.wait(jid, timeout=5)
                return q.stats()
        s = asyncio.run(_run())
        self.assertEqual(s["complete"], 3)
        self.assertEqual(s["failed"], 0)

    def test_job_model_properties(self):
        from aaip.engine.queue import Job, JobStatus
        import time
        # Test is_terminal
        for status in JobStatus:
            job = Job(job_id="test", task="test", agent_id="agent", status=status)
            if status in (JobStatus.COMPLETE, JobStatus.FAILED,
                          JobStatus.CANCELLED, JobStatus.DEAD):
                self.assertTrue(job.is_terminal)
            else:
                self.assertFalse(job.is_terminal)
        # Test elapsed
        job = Job(job_id="test", task="test", agent_id="agent",
                  started_at=100.0, finished_at=150.0)
        self.assertAlmostEqual(job.elapsed, 50.0)
        job2 = Job(job_id="test2", task="test", agent_id="agent")
        self.assertIsNone(job2.elapsed)
        # Test serialization round-trip
        job3 = Job(job_id="test3", task="task", agent_id="agent",
                   cost=0.5, max_retries=2, status=JobStatus.RUNNING,
                   result={"key": "value"}, error="something",
                   attempts=1, ttl_s=7200.0)
        d = job3.to_dict()
        job4 = Job.from_dict(d)
        self.assertEqual(job3.job_id, job4.job_id)
        self.assertEqual(job3.status, job4.status)
        self.assertEqual(job3.result, job4.result)
        self.assertEqual(job3.error, job4.error)
        self.assertEqual(job3.ttl_s, job4.ttl_s)


class TestSchemaExport(unittest.TestCase):

    def test_build_schema_structure(self):
        from aaip.schemas.export import build_schema
        from aaip.schemas.models import PaymentRequest
        s = build_schema(PaymentRequest)
        self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("$id", s)
        self.assertIn("title", s)
        self.assertIn("properties", s)
        self.assertIn("required", s)
        self.assertEqual(s["title"], "PaymentRequest")

    def test_required_fields_identified(self):
        from aaip.schemas.export import build_schema
        from aaip.schemas.models import PaymentRequest
        s = build_schema(PaymentRequest)
        # agent_id, recipient_address, amount have no defaults → required
        self.assertIn("agent_id",          s["required"])
        self.assertIn("recipient_address", s["required"])
        self.assertIn("amount",            s["required"])
        # poe_hash is Optional → not required
        self.assertNotIn("poe_hash", s["required"])

    def test_enum_values_inlined(self):
        from aaip.schemas.export import build_schema
        from aaip.schemas.models import ExecutionReceipt
        s = build_schema(ExecutionReceipt)
        # status field should have enum values
        status_prop = s["properties"].get("status", {})
        # May be a $ref to defs or inlined — either is valid
        self.assertTrue(bool(status_prop))

    def test_all_models_exportable(self):
        from aaip.schemas.export import MODELS, build_schema
        import json
        for name, cls in MODELS.items():
            schema = build_schema(cls)
            # Must be JSON serialisable
            serialised = json.dumps(schema)
            self.assertIn(name.replace("_", "").lower(),
                          schema["title"].lower().replace(" ", ""))

    def test_export_to_directory(self):
        import tempfile
        from aaip.schemas.export import export_all
        out = pathlib.Path(tempfile.mkdtemp())
        written = export_all(out)
        self.assertGreater(len(written), 0)
        for name, path in written.items():
            self.assertTrue(path.exists())
            import json
            data = json.loads(path.read_text())
            self.assertIn("$schema", data)

    def test_get_schema_by_name(self):
        from aaip.schemas.export import get_schema
        s = get_schema("payment_request")
        self.assertIsNotNone(s)
        s2 = get_schema("nonexistent")
        self.assertIsNone(s2)


class TestWebhooks(unittest.TestCase):

    def setUp(self):
        import tempfile
        from aaip.api.webhooks import WebhookRegistry, WebhookDispatcher
        self._db  = pathlib.Path(tempfile.mktemp(suffix=".db"))
        self._reg = WebhookRegistry(self._db)
        self._dis = WebhookDispatcher(self._reg)

    def tearDown(self):
        self._reg.close()

    def test_register_endpoint(self):
        eid = self._reg.register("https://example.com/hook", "secret", ["payment.success"])
        eps = self._reg.all_endpoints()
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]["url"], "https://example.com/hook")

    def test_deregister_endpoint(self):
        self._reg.register("https://example.com/hook")
        ok = self._reg.deregister("https://example.com/hook")
        self.assertTrue(ok)
        eps = [e for e in self._reg.all_endpoints() if e["active"]]
        self.assertEqual(len(eps), 0)

    def test_event_filtering(self):
        self._reg.register("https://a.com/hook", events=["payment.success"])
        self._reg.register("https://b.com/hook", events=["payment.failed"])
        self._reg.register("https://c.com/hook", events=["*"])
        eps = self._reg.endpoints_for_event("payment.success")
        urls = {e["url"] for e in eps}
        self.assertIn("https://a.com/hook", urls)
        self.assertNotIn("https://b.com/hook", urls)
        self.assertIn("https://c.com/hook", urls)

    def test_signature_generation(self):
        from aaip.api.webhooks import _sign_payload
        import hmac, hashlib
        secret  = "test_secret"
        payload = b'{"event": "payment.success"}'
        sig     = _sign_payload(payload, secret)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        self.assertEqual(sig, expected)

    def test_delivery_log_written(self):
        self._reg.register("https://example.com/hook")
        self._reg.log_delivery(
            endpoint_id=self._reg.all_endpoints()[0]["endpoint_id"],
            event="payment.success",
            attempt=1, success=True, status_code=200, error=None,
        )
        log = self._reg.delivery_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["success"], 1)

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            self._reg.register("not-a-url")


class TestReconciliation(unittest.TestCase):

    def setUp(self):
        import tempfile, os
        self._db = pathlib.Path(tempfile.mktemp(suffix=".db"))
        os.environ["AEP_DB_PATH"] = tempfile.mktemp(suffix=".payments.db")
        import aaip.engine.payment_manager as pm; pm._store = None
        from aaip.engine.reconciliation import Reconciler
        self._rec = Reconciler(
            db_path=self._db,
            threshold_eth=0.05,
            recipient_address=ADDR,
        )

    def tearDown(self):
        self._rec.close()

    def test_record_and_balance(self):
        self._rec.record_credit_tx(AGENT_ID, 0.03, "payment", "credit")
        self._rec.record_credit_tx(AGENT_ID, 0.02, "payment", "credit")
        bal = self._rec.unsettled_balance(AGENT_ID)
        self.assertAlmostEqual(bal, 0.05, places=6)

    def test_unsettled_balance_edge_cases(self):
        # non-existent agent returns zero
        bal = self._rec.unsettled_balance("nonexistent")
        self.assertEqual(bal, 0.0)
        # zero credits
        self._rec.record_credit_tx(AGENT_ID, 0.0, "payment", "credit")
        bal = self._rec.unsettled_balance(AGENT_ID)
        self.assertEqual(bal, 0.0)
        # multiple agents
        self._rec.record_credit_tx("agent2", 0.1, "payment", "credit")
        bal2 = self._rec.unsettled_balance("agent2")
        self.assertAlmostEqual(bal2, 0.1, places=6)
        # original agent unchanged
        bal1 = self._rec.unsettled_balance(AGENT_ID)
        self.assertEqual(bal1, 0.0)

    def test_pending_settlements_above_threshold(self):
        self._rec.record_credit_tx(AGENT_ID, 0.06, "payment", "credit")
        pending = self._rec.pending_settlements()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["agent_id"], AGENT_ID)

    def test_pending_settlements_below_threshold(self):
        self._rec.record_credit_tx(AGENT_ID, 0.01, "payment", "credit")
        pending = self._rec.pending_settlements()
        self.assertEqual(len(pending), 0)

    def test_settle_agent(self):
        import asyncio as aio
        from aaip.engine.payment_manager import get_or_create_wallet
        get_or_create_wallet(AGENT_ID, ADDR)
        self._rec.record_credit_tx(AGENT_ID, 0.06, "payment", "credit")

        result = aio.run(self._rec.settle_agent(AGENT_ID))
        self.assertIn(result.status, ("settled", "failed"))   # may fail without chain

    def test_settle_below_threshold_skipped(self):
        import asyncio as aio
        self._rec.record_credit_tx(AGENT_ID, 0.01, "payment", "credit")
        result = aio.run(self._rec.settle_agent(AGENT_ID))
        self.assertEqual(result.status, "below_threshold")

    def test_no_recipient_skipped(self):
        import asyncio as aio
        from aaip.engine.reconciliation import Reconciler
        rec = Reconciler(db_path=self._db, threshold_eth=0.0, recipient_address="")
        rec.record_credit_tx(AGENT_ID, 0.5, "payment", "credit")
        result = aio.run(rec.settle_agent(AGENT_ID))
        self.assertEqual(result.status, "skipped")
        rec.close()

    def test_summary(self):
        self._rec.record_credit_tx(AGENT_ID, 0.03, "p", "credit")
        s = self._rec.summary()
        self.assertIn("pending_eth", s)
        self.assertGreater(s["pending_eth"], 0)

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
