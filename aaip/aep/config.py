"""
aaip/aep/config.py — Centralised AEP Configuration

All tunables come from environment variables.
Import `cfg` anywhere — it reads env at import time.

  AEP_RPC_URL          RPC endpoint (triggers EVMAdapter when set)
  AEP_PRIVATE_KEY      Hex-encoded private key (0x-prefixed) — NEVER logged
  AEP_CHAIN_ID         Override chain ID (auto-detected if omitted)
  AEP_TOKEN_ADDRESS    ERC-20 token address (optional)
  AEP_ADAPTER          "mock" | "evm" | auto
  AEP_GAS_LIMIT        Gas limit (default 21000)
  AEP_PRIORITY_GWEI    EIP-1559 priority fee in Gwei (default 1.5)
  AEP_ANCHOR_PATH      Anchor store path (default ~/.aaip-anchors.json)
  AEP_DB_PATH          SQLite DB path (default ~/.aaip-payments.db)
  AEP_DEMO_MODE        "1"|"true" — fast mode
  AEP_PAYMENT_AMOUNT   Default demo amount (default 0.05)
  AEP_PAYMENT_SYMBOL   Token symbol shown in UI (default ETH)
  AEP_NONCE_WINDOW_S   Replay-protection window in seconds (default 300)
  AEP_API_HOST         FastAPI host (default 0.0.0.0)
  AEP_API_PORT         FastAPI port (default 8000)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AEPConfig:
    rpc_url: str              = field(default_factory=lambda: os.environ.get("AEP_RPC_URL", ""))
    private_key: str          = field(default_factory=lambda: os.environ.get("AEP_PRIVATE_KEY", ""))
    chain_id: int | None      = field(default_factory=lambda: int(os.environ["AEP_CHAIN_ID"]) if "AEP_CHAIN_ID" in os.environ else None)
    token_address: str | None = field(default_factory=lambda: os.environ.get("AEP_TOKEN_ADDRESS"))
    adapter_name: str         = field(default_factory=lambda: os.environ.get("AEP_ADAPTER", "auto"))
    gas_limit: int            = field(default_factory=lambda: int(os.environ.get("AEP_GAS_LIMIT", "21000")))
    priority_gwei: float      = field(default_factory=lambda: float(os.environ.get("AEP_PRIORITY_GWEI", "1.5")))
    anchor_path: Path         = field(default_factory=lambda: Path(os.environ.get("AEP_ANCHOR_PATH", str(Path.home() / ".aaip-anchors.json"))))
    db_path: Path             = field(default_factory=lambda: Path(os.environ.get("AEP_DB_PATH", str(Path.home() / ".aaip-payments.db"))))
    demo_mode: bool           = field(default_factory=lambda: os.environ.get("AEP_DEMO_MODE", "").lower() in ("1", "true", "yes"))
    payment_amount: float     = field(default_factory=lambda: float(os.environ.get("AEP_PAYMENT_AMOUNT", "0.05")))
    payment_symbol: str       = field(default_factory=lambda: os.environ.get("AEP_PAYMENT_SYMBOL", "ETH"))
    nonce_window_s: int       = field(default_factory=lambda: int(os.environ.get("AEP_NONCE_WINDOW_S", "300")))
    api_host: str             = field(default_factory=lambda: os.environ.get("AEP_API_HOST", "0.0.0.0"))
    api_port: int             = field(default_factory=lambda: int(os.environ.get("AEP_API_PORT", "8000")))

    _EXPLORERS: dict[int, str] = field(default_factory=lambda: {
        1:        "https://etherscan.io/tx/",
        11155111: "https://sepolia.etherscan.io/tx/",
        8453:     "https://basescan.org/tx/",
        84532:    "https://sepolia.basescan.org/tx/",
        137:      "https://polygonscan.com/tx/",
        42161:    "https://arbiscan.io/tx/",
    }, repr=False)

    # ── FIX: mask private_key in repr to prevent log leaks ──────────
    def __repr__(self) -> str:
        masked = "***" if self.private_key else "(not set)"
        return (
            f"AEPConfig(adapter={self.adapter_name!r}, rpc_url={self.rpc_url!r}, "
            f"private_key={masked}, chain_id={self.chain_id}, "
            f"payment_amount={self.payment_amount}, symbol={self.payment_symbol!r})"
        )

    @property
    def use_evm(self) -> bool:
        if self.adapter_name == "evm":   return True
        if self.adapter_name == "mock":  return False
        return bool(self.rpc_url)

    def explorer_url(self, tx_hash: str, chain_id: int | None = None) -> str | None:
        cid  = chain_id or self.chain_id
        base = self._EXPLORERS.get(cid) if cid else None
        return f"{base}{tx_hash}" if base else None

    def mock_explorer_url(self, tx_hash: str) -> str:
        return f"https://sepolia.etherscan.io/tx/{tx_hash}"


cfg = AEPConfig()
