"""
AEP — Agent Economy Protocol
Core API

This module exposes two primary functions:

    execute_payment(agent_id, recipient_address, amount, poe_hash, ...)
    anchor_proof(poe_hash, tx_hash, ...)

Both functions are adapter-agnostic and can be called:
  - from inside the AAIP pipeline (after PoE validation)
  - from any external backend, microservice, or CLI

Adapter selection
-----------------
AEP uses the MockPaymentAdapter by default.
Switch to EVMPaymentAdapter in production by passing it explicitly,
or by setting AEP_ADAPTER=evm in the environment.

Example::

    from aaip.aep import execute_payment
    result = execute_payment(
        agent_id="worker_1",
        recipient_address="0xabc...",
        amount=1.5,
        poe_hash="0xdeadbeef...",
    )
"""

from __future__ import annotations

import decimal
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .adapters.base import BasePaymentAdapter
from .adapters.mock import MockPaymentAdapter
from .exceptions import AEPAnchorError, AEPError
from .utils import (
    emit_anchor_log,
    emit_payment_log,
    normalise_poe_hash,
    validate_payment_inputs,
)

log = logging.getLogger("aaip.aep")
_anchor_lock = threading.Lock()  # protects concurrent writes to anchor JSON

# Default anchor store — JSON file next to this module.
_DEFAULT_ANCHOR_PATH = Path(
    os.environ.get("AEP_ANCHOR_PATH", str(Path.home() / ".aaip-anchors.json"))
)


# ── Adapter factory ───────────────────────────────────────────────────────────

def _default_adapter() -> BasePaymentAdapter:
    """
    Return the adapter specified by AEP_ADAPTER env var.

    AEP_ADAPTER=mock  → MockPaymentAdapter  (default)
    AEP_ADAPTER=evm   → EVMPaymentAdapter
    """
    adapter_name = os.environ.get("AEP_ADAPTER", "mock").lower()
    if adapter_name == "evm":
        from .adapters.evm import EVMPaymentAdapter  # lazy import
        return EVMPaymentAdapter()
    return MockPaymentAdapter()


# ── Public API ────────────────────────────────────────────────────────────────

def execute_payment(
    agent_id: str,
    recipient_address: str,
    amount: float,
    poe_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
    adapter: BasePaymentAdapter | None = None,
) -> dict[str, Any]:
    """
    Execute a payment after verifying inputs and dispatching
    to the configured blockchain adapter.

    This function is intentionally decoupled from AAIP internals:
    poe_hash is optional, so AEP can be used as a standalone
    payment layer in any backend workflow.

    Args:
        agent_id:           Identifier of the agent / service requesting payment.
        recipient_address:  On-chain address to send funds to.
        amount:             Payment amount in the adapter's native unit (e.g. ETH).
        poe_hash:           Optional — hash of the Proof-of-Execution that authorises
                            this payment. Stored in the anchor log for auditability.
        metadata:           Arbitrary key-value payload forwarded to the adapter.
        adapter:            Payment adapter instance. Defaults to AEP_ADAPTER env var
                            (mock if unset).

    Returns:
        {
            "status":    "success" | "failed",
            "tx_hash":   str | None,
            "poe_hash":  str | None,
            "amount":    float,
            "recipient": str,
            "agent_id":  str,
            "error":     str | None,
        }

    Raises:
        InvalidAgentIDError    — blank agent_id
        InvalidAmountError     — amount ≤ 0
        InvalidAddressError    — malformed address
    """
    metadata = metadata or {}
    adapter = adapter or _default_adapter()
    poe_hash = normalise_poe_hash(poe_hash)

    # ── Validate ──────────────────────────────────────────────────────
    validate_payment_inputs(agent_id, recipient_address, amount, adapter)

    # ── Enrich metadata ───────────────────────────────────────────────
    tx_metadata = {
        "agent_id": agent_id,
        "poe_hash": poe_hash or "",
        **metadata,
    }

    # ── Dispatch ──────────────────────────────────────────────────────
    log.debug("Dispatching payment: agent=%s amount=%s to=%s", agent_id, amount, recipient_address)
    t0 = time.monotonic()

    from aaip.engine.billing import PROTOCOL_FEE_RATE, PROTOCOL_TREASURY
    # Use Decimal for precise calculations to avoid IEEE 754 rounding errors
    fee_rate_decimal = decimal.Decimal(str(PROTOCOL_FEE_RATE))
    amount_decimal = decimal.Decimal(str(amount))
    
    worker_amount_decimal = amount_decimal * (decimal.Decimal('1') - fee_rate_decimal)
    fee_amount_decimal = amount_decimal * fee_rate_decimal
    
    # Round to 18 decimal places (common for ETH precision) and convert to float for adapter
    worker_amount = float(worker_amount_decimal.quantize(decimal.Decimal('1e-18'), rounding=decimal.ROUND_HALF_UP))
    fee_amount = float(fee_amount_decimal.quantize(decimal.Decimal('1e-18'), rounding=decimal.ROUND_HALF_UP))
    fee_rate = PROTOCOL_FEE_RATE  # Keep original float for compatibility

    try:
        # Pay worker
        adapter_result = adapter.send_payment(
            to=recipient_address,
            amount=worker_amount,
            metadata=tx_metadata,
        )

        # Pay protocol treasury (non-blocking — enqueue failed attempts in retry queue)
        if (
            adapter_result.get("status") == "success"
            and fee_amount > 0
            and PROTOCOL_TREASURY is not None
        ):
            def _retry_protocol_fee():
                """Background thread to retry protocol fee payment with exponential backoff"""
                max_retries = 3
                last_exception = None
                for attempt in range(max_retries + 1):
                    try:
                        adapter.send_payment(
                            to=PROTOCOL_TREASURY,
                            amount=fee_amount,
                            metadata={"type": "protocol_fee", "original_amount": amount,
                                      "fee_rate": fee_rate, "agent_id": agent_id},
                        )
                        # Success - break out of retry loop
                        log.debug("Protocol fee payment succeeded on attempt %d", attempt + 1)
                        return
                    except Exception as fee_exc:
                        last_exception = fee_exc
                        if attempt < max_retries:
                            # Exponential backoff: 0.5s, 1s, 2s
                            backoff = 0.5 * (2 ** attempt)
                            log.debug("Protocol fee payment attempt %d failed, retrying in %.1fs: %s", 
                                     attempt + 1, backoff, fee_exc)
                            time.sleep(backoff)
                        else:
                            log.warning("Protocol fee payment failed after %d attempts (non-fatal): %s", 
                                       max_retries + 1, fee_exc)
            
            # Start retry in background thread to avoid blocking
            import threading
            retry_thread = threading.Thread(target=_retry_protocol_fee, daemon=True)
            retry_thread.start()

    except AEPError:
        raise
    except Exception as exc:
        adapter_result = {
            "tx_hash": None,
            "status": "failed",
            "block": None,
            "gas_used": None,
            "error": str(exc),
        }

    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    result: dict[str, Any] = {
        "status": adapter_result.get("status", "failed"),
        "tx_hash": adapter_result.get("tx_hash"),
        "poe_hash": poe_hash,
        "amount": amount,
        "recipient": recipient_address,
        "agent_id": agent_id,
        "error": adapter_result.get("error"),
        "explorer_url": adapter_result.get("explorer_url"),
        "protocol_fee": fee_amount,
        "worker_amount": worker_amount,
        "fee_rate": fee_rate,
    }

    # ── Structured log ────────────────────────────────────────────────
    emit_payment_log(
        event="payment_executed",
        agent_id=agent_id,
        recipient=recipient_address,
        amount=amount,
        poe_hash=poe_hash,
        tx_hash=result["tx_hash"],
        status=result["status"],
        extra={"latency_ms": latency_ms},
    )

    # ── Auto-anchor on success ─────────────────────────────────────────
    if result["status"] == "success" and poe_hash and result["tx_hash"]:
        try:
            anchor_proof(
                poe_hash=poe_hash,
                tx_hash=result["tx_hash"],
                agent_id=agent_id,          # ADD THIS LINE
                store_path=_DEFAULT_ANCHOR_PATH,
            )
        except AEPAnchorError as exc:
            log.warning("Proof anchoring failed (non-fatal): %s", exc)

    return result


def anchor_proof(
    poe_hash:   str,
    tx_hash:    str,
    agent_id:   str | None = None,
    store_path: Path | str | None = None,
    extra:      dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Record PoE hash -> settlement tx_hash.
    Tries Base Sepolia on-chain first; falls back to local JSON.
    """
    from .adapters.anchor_chain import get_anchor_adapter
    _aid = agent_id or "unknown_agent"
    try:
        result = get_anchor_adapter().anchor(_aid, poe_hash, tx_hash)
        if result.get("status") == "success":
            emit_anchor_log(poe_hash, tx_hash,
                "base_sepolia" if result["on_chain"] else "local_json", "success")
            return result
    except Exception as exc:
        log.warning("Anchor adapter error: %s", exc)
    # Local JSON fallback
    store_path = Path(store_path or _DEFAULT_ANCHOR_PATH)
    record: dict[str, Any] = {
        "agent_id": _aid, "poe_hash": poe_hash,
        "tx_hash": tx_hash, "anchored_at": time.time(),
        "on_chain": False, **(extra or {}),
    }
    try:
        with _anchor_lock:
            anchors: list = []
            if store_path.exists():
                with store_path.open("r") as fh:
                    anchors = json.load(fh)
            anchors.append(record)
            tmp = store_path.with_suffix(".tmp")
            with tmp.open("w") as fh:
                json.dump(anchors, fh, indent=2)
            tmp.replace(store_path)
    except Exception as exc:
        emit_anchor_log(poe_hash, tx_hash, "local_json", "failed")
        raise AEPAnchorError(f"All anchor methods failed: {exc}", "ANCHOR_WRITE_FAILED") from exc
    emit_anchor_log(poe_hash, tx_hash, "local_json", "success")
    return record


def get_anchors(store_path: Path | str | None = None) -> list[dict[str, Any]]:
    """
    Return all recorded poe_hash → tx_hash anchor mappings.

    Args:
        store_path: Path to the JSON anchor file.

    Returns:
        List of anchor records, oldest first.
    """
    store_path = Path(store_path or _DEFAULT_ANCHOR_PATH)
    with _anchor_lock:
        if not store_path.exists():
            return []
        with store_path.open("r") as fh:
            return json.load(fh)
