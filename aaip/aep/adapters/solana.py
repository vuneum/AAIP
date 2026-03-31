"""
aaip/aep/adapters/solana.py — Solana Payment Adapter

Sends SOL (or SPL token) payments on Solana mainnet / devnet.

Configuration (env vars):
  AEP_SOLANA_RPC_URL    e.g. https://api.devnet.solana.com
  AEP_SOLANA_KEYPAIR    Path to keypair JSON file  (default ~/.config/solana/id.json)
  AEP_SOLANA_TOKEN_MINT SPL token mint address (omit for native SOL)
  AEP_SOLANA_EXPLORER   Explorer base (default https://explorer.solana.com/tx/)

Secrets Management:
  Use AEP_SECRETS_BACKEND to configure where private keys are stored:
    - "env": Read from AEP_SOLANA_KEYPAIR environment variable (default)
    - "file": Read from file specified in AEP_SECRETS_PATH
    - "encrypted_file": Read encrypted key from file with AEP_SECRETS_PASSPHRASE

Requires:  pip install solana anchorpy  (not installed in this env — lazy import)

Usage::

    adapter = SolanaPaymentAdapter()
    result  = adapter.send_payment(
        to="RecipientBase58Address...",
        amount=0.1,           # in SOL
        metadata={"poe_hash": "..."},
    )
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import BasePaymentAdapter
from ..exceptions import AEPAdapterError, AEPConfigurationError
from ..secrets import get_solana_keypair_path, get_solana_private_key

log = logging.getLogger("aaip.aep.solana")

_DEVNET_EXPLORER  = "https://explorer.solana.com/tx/"
_MAINNET_EXPLORER = "https://explorer.solana.com/tx/"
_DEVNET_SUFFIX    = "?cluster=devnet"


class SolanaPaymentAdapter(BasePaymentAdapter):
    """
    Solana native-SOL payment adapter.

    Falls back to a stub mode when the `solana` package is not installed,
    so the rest of AEP remains importable without the Solana SDK.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        keypair_path: str | None = None,
        token_mint: str | None = None,
    ) -> None:
        self._rpc_url     = rpc_url      or os.environ.get("AEP_SOLANA_RPC_URL", "https://api.devnet.solana.com")
        # Use secrets management layer to get keypair path or private key
        if keypair_path is not None:
            self._keypair_path = keypair_path
        else:
            try:
                self._keypair_path = get_solana_keypair_path()
            except AEPConfigurationError as e:
                # Fall back to environment variable for backward compatibility
                self._keypair_path = os.environ.get("AEP_SOLANA_KEYPAIR",
                                                   os.path.expanduser("~/.config/solana/id.json"))
        self._token_mint  = token_mint   or os.environ.get("AEP_SOLANA_TOKEN_MINT")
        self._explorer    = os.environ.get("AEP_SOLANA_EXPLORER", _DEVNET_EXPLORER)
        self._is_devnet   = "devnet" in self._rpc_url
        # Store private key if using encrypted backend
        self._private_key = get_solana_private_key()

        # Lazy import — don't break the package if solana SDK absent
        try:
            from solana.rpc.api import Client
            from solana.keypair import Keypair
            from solana.transaction import Transaction
            from spl.token.client import Token
            self._client = Client(self._rpc_url)
            self._keypair = self._load_keypair()
            self._sdk_available = True
            log.info("SolanaAdapter initialised: rpc=%s", self._rpc_url)
        except ImportError:
            self._sdk_available = False
            log.warning(
                "solana SDK not installed — SolanaAdapter in stub mode. "
                "Run: pip install solana anchorpy"
            )

    # ── Interface ─────────────────────────────────────────────────────

    def send_payment(
        self,
        to: str,
        amount: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._sdk_available:
            return self._stub_result(to, amount)

        try:
            from solana.publickey import PublicKey
            from solana.system_program import transfer, TransferParams
            from solana.transaction import Transaction
            import math

            lamports = math.floor(amount * 1_000_000_000)   # 1 SOL = 1e9 lamports
            ix = transfer(TransferParams(
                from_pubkey=self._keypair.public_key,
                to_pubkey=PublicKey(to),
                lamports=lamports,
            ))
            tx = Transaction().add(ix)
            resp = self._client.send_transaction(tx, self._keypair)
            sig  = resp["result"]
            suffix = _DEVNET_SUFFIX if self._is_devnet else ""
            return {
                "tx_hash":     sig,
                "status":      "success",
                "block":       None,
                "gas_used":    None,
                "error":       None,
                "explorer_url": f"{self._explorer}{sig}{suffix}",
            }
        except Exception as exc:
            log.error("Solana payment failed: %s", exc)
            return {"tx_hash": None, "status": "failed", "block": None,
                    "gas_used": None, "error": str(exc), "explorer_url": None}

    def is_valid_address(self, address: str) -> bool:
        """Validate a base58 Solana public key (32–44 chars, base58 alphabet)."""
        if not address or not isinstance(address, str):
            return False
        _BASE58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        return 32 <= len(address) <= 44 and all(c in _BASE58 for c in address)

    # ── Internals ─────────────────────────────────────────────────────

    def _load_keypair(self):
        from solana.keypair import Keypair
        # Check if we have a direct private key from encrypted backend
        if self._private_key:
            try:
                # Private key is hex-encoded bytes
                secret_bytes = bytes.fromhex(self._private_key)
                return Keypair.from_secret_key(secret_bytes)
            except (ValueError, TypeError) as e:
                log.warning(f"Failed to load private key from encrypted backend: {e}")
                # Fall back to file path
        
        # Load from file path
        if not os.path.exists(self._keypair_path):
            raise AEPConfigurationError(
                f"Solana keypair not found at {self._keypair_path}. "
                "Run: solana-keygen new --outfile ~/.config/solana/id.json"
            )
        with open(self._keypair_path) as f:
            secret = json.load(f)
        return Keypair.from_secret_key(bytes(secret[:32]))

    def _stub_result(self, to: str, amount: float) -> dict[str, Any]:
        """Return a plausible stub result when SDK is absent."""
        import hashlib, time
        raw = f"stub:{to}:{amount}:{time.time_ns()}"
        fake_sig = hashlib.sha256(raw.encode()).hexdigest()[:87]
        suffix = _DEVNET_SUFFIX if self._is_devnet else ""
        log.warning("SolanaAdapter stub mode — no real transaction sent")
        return {
            "tx_hash":     fake_sig,
            "status":      "success",
            "block":       None,
            "gas_used":    None,
            "error":       None,
            "explorer_url": f"{self._explorer}{fake_sig}{suffix}",
            "stub":        True,
        }
