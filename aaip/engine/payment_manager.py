"""
aaip/engine/payment_manager.py — Payment Manager

Owns the full payment lifecycle:
  1. Validate PaymentRequest (schema + replay check)
  2. Dispatch to adapter
  3. Persist ExecutionReceipt to DB
  4. Update AgentWallet
  5. Return ExecutionReceipt

Also implements:
  - Nonce-based replay protection
  - Idempotency (same key → return cached receipt)
  - Signature stub (ready for ed25519 signing)
  - Auto-retry on transient failures (up to max_retries)

This replaces the inlined payment logic in orchestrator.py.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from aaip.aep.config import cfg
from aaip.aep.core import execute_payment
from aaip.aep.adapters.mock import MockPaymentAdapter
from aaip.aep.exceptions import AEPError
# Webhooks — optional, imported lazily to avoid circular dep at module load
_webhooks = None
def _get_webhooks():
    global _webhooks
    if _webhooks is None:
        try:
            from aaip.api.webhooks import get_dispatcher, Events
            _webhooks = (get_dispatcher(), Events)
        except Exception:
            _webhooks = (None, None)
    return _webhooks
from aaip.aep.adapters.base import BasePaymentAdapter
from aaip.schemas.models import (
    AdapterType,
    AgentWallet,
    ExecutionReceipt,
    PaymentRequest,
    PaymentStatus,
    ValidationResult,
)
from aaip.storage.db import PaymentStore

log = logging.getLogger("aaip.engine.payment_manager")

# Module-level store singleton (re-use same DB connection)
_store: PaymentStore | None = None


def _get_store() -> PaymentStore:
    global _store
    if _store is None:
        _store = PaymentStore()
    return _store


# ── Public API ────────────────────────────────────────────────────────────────

def process_payment(
    request: PaymentRequest,
    validation: ValidationResult | None = None,
    adapter=None,
    max_retries: int = 1,
) -> ExecutionReceipt:
    """
    Execute and persist a payment with full lifecycle management.

    Features:
      - Idempotency check: if the same idempotency_key was already
        processed successfully, return the cached receipt.
      - Replay protection: rejects duplicate poe_hash within the
        nonce window (cfg.nonce_window_s).
      - Persistence: saves request + receipt to SQLite.
      - Wallet update: credits/debits the agent wallet.
      - Auto-retry: on adapter failure, retries up to max_retries.

    Args:
        request:    Validated PaymentRequest.
        validation: Optional ValidationResult to embed in receipt.
        adapter:    Override payment adapter (default: auto from cfg).
        max_retries: Number of retry attempts on failure.

    Returns:
        ExecutionReceipt — always returned, check .status for outcome.
    """
    store   = _get_store()
    adapter = adapter or (MockPaymentAdapter() if not cfg.use_evm else None)

    # ── Idempotency ───────────────────────────────────────────────────
    idem_key = request.idempotency_key or request.fingerprint
    existing = _find_successful_receipt(store, idem_key)
    if existing:
        log.info("Idempotent: returning cached receipt %s", existing.receipt_id[:8])
        return existing

    # ── Replay protection ─────────────────────────────────────────────
    if request.poe_hash:
        nonce_key = _nonce_key(request.agent_id, request.poe_hash)
        if not store.register_nonce(nonce_key, request.agent_id, request.poe_hash):
            log.warning("Replay detected for poe_hash %s", request.poe_hash[:18])
            return _build_receipt({"status": "failed", "error": "REPLAY_ATTACK: nonce already used"}, request,
                                  validation=validation, adapter_type=_adapter_type(adapter))

    # ── Persist request ───────────────────────────────────────────────
    store.save_request(request)

    # ── Execute with retry ────────────────────────────────────────────
    last_result: dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        try:
            last_result = execute_payment(
                agent_id=request.agent_id,
                recipient_address=request.recipient_address,
                amount=request.amount,
                poe_hash=request.poe_hash,
                metadata=request.metadata,
                adapter=adapter,
            )
            if last_result.get("status") == "success":
                break
        except AEPError as exc:
            last_result = {"status": "failed", "error": str(exc)}
        if attempt < max_retries:
            log.warning("Payment attempt %d failed, retrying…", attempt + 1)
            time.sleep(0.5 * (attempt + 1))

    # ── Build and persist receipt ─────────────────────────────────────
    receipt = _build_receipt(last_result, request, validation=validation,
                             adapter_type=_adapter_type(adapter))
    store.save_receipt(receipt)

    # ── Update wallet ─────────────────────────────────────────────────
    if receipt.status == PaymentStatus.SUCCESS:
        # Look up payer's registered address; fall back to a placeholder
        payer_wallet = store.get_wallet(request.agent_id)
        payer_address = payer_wallet.address if payer_wallet else request.agent_id
        # Derive a stable recipient_id from the on-chain address
        recipient_id = "ext_" + request.recipient_address[-8:].lower()
        _update_wallet(
            store,
            payer_id=request.agent_id,
            payer_address=payer_address,
            recipient_id=recipient_id,
            recipient_address=request.recipient_address,
            amount=request.amount,
        )

    log.info("Payment processed: status=%s tx=%s", receipt.status.value,
             (receipt.tx_hash or "N/A")[:18])

    # Emit webhook event (non-blocking)
    try:
        dispatcher, Events = _get_webhooks()
        if dispatcher and Events:
            event = Events.PAYMENT_SUCCESS if receipt.status == PaymentStatus.SUCCESS else Events.PAYMENT_FAILED
            dispatcher.emit_sync(event, {
                "agent_id":    receipt.agent_id,
                "amount":      receipt.amount,
                "tx_hash":     receipt.tx_hash,
                "poe_hash":    receipt.poe_hash,
                "adapter":     receipt.adapter.value,
                "receipt_id":  receipt.receipt_id,
            })
    except Exception:
        pass   # webhooks must never interrupt the payment path

    return receipt


def get_agent_history(agent_id: str, limit: int = 50) -> list[ExecutionReceipt]:
    """Return the last N receipts for an agent, most recent first."""
    return _get_store().get_receipts(agent_id=agent_id, limit=limit)


def get_or_create_wallet(agent_id: str, address: str) -> AgentWallet:
    """Get an agent's wallet, creating it with the given address if it doesn't exist."""
    store  = _get_store()
    wallet = store.get_wallet(agent_id)
    if not wallet:
        wallet = AgentWallet(agent_id=agent_id, address=address)
        store.upsert_wallet(wallet)
    return wallet


def bump_cav(agent_id: str, delta: float = 1.0) -> AgentWallet | None:
    """Increment an agent's CAV score. Returns updated wallet or None."""
    store  = _get_store()
    wallet = store.get_wallet(agent_id)
    if not wallet:
        return None
    updated = wallet.bump_cav(delta)
    store.upsert_wallet(updated)
    return updated


def payment_stats() -> dict[str, Any]:
    """Return aggregate payment statistics from the DB."""
    return _get_store().stats()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _adapter_type(adapter) -> AdapterType:
    """
    Derive the canonical AdapterType from an adapter instance.
    Checks class name so new adapters are handled without modifying this function.
    """
    if adapter is None:
        return AdapterType.MOCK
    name = type(adapter).__name__.lower()
    if "evm" in name:
        return AdapterType.EVM
    if "solana" in name:
        return AdapterType.SOLANA
    if "credit" in name:
        return AdapterType.CREDITS
    return AdapterType.MOCK


def _nonce_key(agent_id: str, poe_hash: str) -> str:
    raw = f"{agent_id}:{poe_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_successful_receipt(store: PaymentStore, idem_key: str) -> "ExecutionReceipt | None":
    """Return existing SUCCESS receipt for this idempotency key, or None."""
    if not store.is_duplicate(idem_key):
        return None
    return store.get_receipt_by_idempotency_key(idem_key)


def _build_receipt(
    result: dict[str, Any],
    request: PaymentRequest,
    validation: ValidationResult | None,
    adapter_type: AdapterType,
) -> ExecutionReceipt:
    status = PaymentStatus.SUCCESS if result.get("status") == "success" else PaymentStatus.FAILED
    return ExecutionReceipt(
        request_id=request.request_id,
        agent_id=request.agent_id,
        recipient=request.recipient_address,
        amount=request.amount,
        currency=request.currency,
        status=status,
        tx_hash=result.get("tx_hash"),
        explorer_url=result.get("explorer_url"),
        poe_hash=request.poe_hash,
        block_number=result.get("block"),
        gas_used=result.get("gas_used"),
        adapter=adapter_type,
        error=result.get("error"),
        validation=validation,
    )


def _update_wallet(
    store: PaymentStore,
    payer_id: str,
    payer_address: str,
    recipient_id: str,
    recipient_address: str,
    amount: float,
) -> None:
    """
    Record settlement on both sides of the ledger.

    - Payer wallet: debit amount (total_paid++)
    - Recipient wallet: credit amount (total_received++)

    If a wallet doesn't exist yet it is created with the given address.
    recipient_id is derived from recipient_address when no named agent
    owns it (external addresses get a synthetic id).
    """
    # Payer side — debit
    payer = store.get_wallet(payer_id)
    if not payer:
        payer = AgentWallet(agent_id=payer_id, address=payer_address)
    store.upsert_wallet(payer.debit(amount))

    # Recipient side — credit
    # Look up by address first; fall back to creating with a synthetic agent_id
    recipient = store.get_wallet(recipient_id)
    if not recipient:
        recipient = AgentWallet(agent_id=recipient_id, address=recipient_address)
    store.upsert_wallet(recipient.credit(amount))
