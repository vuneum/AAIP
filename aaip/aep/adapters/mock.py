"""AEP — Mock Payment Adapter. Deterministic, in-memory, zero deps."""

from __future__ import annotations
import hashlib, json, time
from typing import Any
from .base import BasePaymentAdapter

# Fake Sepolia explorer base for demo mode
_MOCK_EXPLORER = "https://sepolia.etherscan.io/tx/"


class MockPaymentAdapter(BasePaymentAdapter):
    def __init__(self, fail_on: list[str] | None = None) -> None:
        self.ledger: list[dict[str, Any]] = []
        self._fail_on: set[str] = set(fail_on or [])

    def send_payment(self, to: str, amount: float, metadata: dict | None = None) -> dict[str, Any]:
        metadata = metadata or {}
        if to in self._fail_on:
            result = {"tx_hash": None, "status": "failed", "block": None,
                      "gas_used": None, "error": f"Simulated failure for {to}", "explorer_url": None}
            self.ledger.append(result)
            return result
        raw = f"{to}:{amount}:{time.time_ns()}:{json.dumps(metadata, sort_keys=True)}"
        tx_hash = "0x" + hashlib.sha256(raw.encode()).hexdigest()
        result = {"tx_hash": tx_hash, "status": "success", "block": 7_654_321,
                  "gas_used": 21_000, "error": None,
                  "explorer_url": f"{_MOCK_EXPLORER}{tx_hash}"}
        self.ledger.append(result)
        return result

    def is_valid_address(self, address: str) -> bool:
        if not address or not isinstance(address, str): return False
        if address.startswith("0x"):
            return len(address) == 42 and all(c in "0123456789abcdefABCDEF" for c in address[2:])
        return len(address) > 0
