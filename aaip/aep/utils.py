"""
AEP — Utilities

Input validation, structured logging, and small helpers
shared across the AEP module.
"""

import json
import logging
import re
import time
from typing import Any

from .exceptions import (
    InvalidAddressError,
    InvalidAgentIDError,
    InvalidAmountError,
)

log = logging.getLogger("aaip.aep")

# Matches a hex-encoded poe_hash (0x-prefixed, 64 hex chars) or None/empty.
_POE_HASH_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


# ── Input validation ──────────────────────────────────────────────────────────

def validate_payment_inputs(
    agent_id: str,
    recipient_address: str,
    amount: float,
    adapter,
) -> None:
    """
    Validate all execute_payment() inputs.

    Raises:
        InvalidAgentIDError    — if agent_id is blank
        InvalidAmountError     — if amount <= 0
        InvalidAddressError    — if recipient_address fails adapter check
    """
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise InvalidAgentIDError(agent_id)

    if not isinstance(amount, (int, float)) or amount <= 0:
        raise InvalidAmountError(amount)

    if not adapter.is_valid_address(recipient_address):
        raise InvalidAddressError(recipient_address)


def normalise_poe_hash(poe_hash: str | None) -> str | None:
    """
    Return poe_hash if it looks valid, or None.

    Accepts 64-char hex with or without '0x' prefix.
    Does NOT raise — missing or malformed poe_hash is allowed
    so AEP can operate as a standalone payment layer.
    """
    if not poe_hash:
        return None
    if _POE_HASH_RE.match(poe_hash.strip()):
        return poe_hash.strip().lower()
    log.warning("poe_hash %r does not match expected format — storing as-is", poe_hash)
    return poe_hash.strip()


# ── Structured logging ────────────────────────────────────────────────────────

def emit_payment_log(
    event: str,
    agent_id: str,
    recipient: str,
    amount: float,
    poe_hash: str | None,
    tx_hash: str | None,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a single structured JSON log line for a payment event."""
    payload: dict[str, Any] = {
        "event": event,
        "ts": time.time(),
        "agent_id": agent_id,
        "recipient": recipient,
        "amount": amount,
        "poe_hash": poe_hash,
        "tx_hash": tx_hash,
        "status": status,
    }
    if extra:
        payload.update(extra)

    log.info(json.dumps(payload))


def emit_anchor_log(
    poe_hash: str,
    tx_hash: str,
    backend: str,
    status: str,
) -> None:
    """Emit a structured log line for a proof anchoring event."""
    log.info(json.dumps({
        "event": "proof_anchored",
        "ts": time.time(),
        "poe_hash": poe_hash,
        "tx_hash": tx_hash,
        "backend": backend,
        "status": status,
    }))
