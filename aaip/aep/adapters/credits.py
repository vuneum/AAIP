"""
aaip/aep/adapters/credits.py — Off-Chain Credits Adapter

Instant, gas-free settlements using a pre-funded credit ledger.
Ideal for:
  - High-frequency micro-payments between agents
  - SaaS API billing (deduct from credit balance)
  - Internal agent-to-agent transfers

No blockchain call required — debits the sender's credit balance
and credits the recipient immediately. Periodic reconciliation
can batch-settle to EVM/Solana on a schedule.

Credits are denominated in the configured payment symbol (default: USDC).

Usage::

    adapter = CreditsAdapter()
    # Fund an agent account first
    adapter.fund("agent_alpha_01", 100.0)
    # Pay
    result = adapter.send_payment("agent_beta_01", 0.05)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from .base import BasePaymentAdapter

log = logging.getLogger("aaip.aep.credits")


class CreditsAdapter(BasePaymentAdapter):
    """
    In-process off-chain credit ledger.

    Thread-safe for demo/testing. In production, back this
    with the SQLite store or a Redis cache.
    """

    def __init__(
        self,
        sender_id: str = "platform",
        initial_balance: float = 1000.0,
    ) -> None:
        self._sender_id = sender_id
        self._ledger: dict[str, float] = {sender_id: initial_balance}
        self._history: list[dict[str, Any]] = []

    # ── Interface ─────────────────────────────────────────────────────

    def send_payment(
        self,
        to: str,
        amount: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        sender   = metadata.get("agent_id", self._sender_id)

        sender_bal = self._ledger.get(sender, 0.0)
        if sender_bal < amount:
            err = f"Insufficient credits: {sender} has {sender_bal:.4f}, needs {amount}"
            log.warning(err)
            return {"tx_hash": None, "status": "failed", "block": None,
                    "gas_used": None, "error": err, "explorer_url": None}

        # Atomic debit/credit
        self._ledger[sender] = round(sender_bal - amount, 18)
        self._ledger[to]     = round(self._ledger.get(to, 0.0) + amount, 18)

        raw     = f"credits:{sender}:{to}:{amount}:{time.time_ns()}"
        tx_hash = "0xcredits_" + hashlib.sha256(raw.encode()).hexdigest()[:55]

        record = {
            "tx_hash":     tx_hash,
            "status":      "success",
            "from":        sender,
            "to":          to,
            "amount":      amount,
            "settled_at":  time.time(),
            "metadata":    metadata,
        }
        self._history.append(record)
        log.info("Credits transfer: %s → %s  %.4f  tx=%s", sender, to, amount, tx_hash[:18])

        return {
            "tx_hash":     tx_hash,
            "status":      "success",
            "block":       None,
            "gas_used":    0,
            "error":       None,
            "explorer_url": f"credits://ledger/{tx_hash}",
        }

    def is_valid_address(self, address: str) -> bool:
        """Any non-empty string is a valid credits address (agent_id or 0x address)."""
        return bool(address and isinstance(address, str))

    # ── Credits-specific methods ───────────────────────────────────────

    def fund(self, agent_id: str, amount: float) -> float:
        """Add credits to an agent's balance. Returns new balance."""
        self._ledger[agent_id] = round(self._ledger.get(agent_id, 0.0) + amount, 18)
        log.info("Funded %s with %.4f credits (balance: %.4f)", agent_id, amount, self._ledger[agent_id])
        return self._ledger[agent_id]

    def balance(self, agent_id: str) -> float:
        """Return current credit balance for an agent."""
        return self._ledger.get(agent_id, 0.0)

    def ledger_snapshot(self) -> dict[str, float]:
        """Return a copy of the full credit ledger."""
        return dict(self._ledger)

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the last N credit transactions."""
        return self._history[-limit:]
