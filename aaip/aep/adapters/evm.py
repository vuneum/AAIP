"""
AEP — EVM Payment Adapter
EIP-1559 native-token transfers with block-explorer URL support.

Configuration (env vars — never hardcode keys):
  AEP_RPC_URL        e.g. https://sepolia.infura.io/v3/<KEY>
  AEP_PRIVATE_KEY    0x-prefixed hex private key (or use secrets management)
  AEP_CHAIN_ID       (auto-detected from RPC if omitted)
  AEP_GAS_LIMIT      (default 21000)
  AEP_PRIORITY_GWEI  (default 1.5)

Secrets Management:
  Use AEP_SECRETS_BACKEND to configure where private keys are stored:
    - "env": Read from AEP_PRIVATE_KEY environment variable (default)
    - "file": Read from file specified in AEP_SECRETS_PATH
    - "encrypted_file": Read encrypted key from file with AEP_SECRETS_PASSPHRASE
"""

from __future__ import annotations
import logging, os
from typing import Any
from .base import BasePaymentAdapter
from ..exceptions import AEPAdapterError, AEPConfigurationError
from ..secrets import get_evm_private_key

log = logging.getLogger("aaip.aep.evm")

_web3_available = False
try:
    from web3 import Web3
    _web3_available = True
except ImportError:
    pass

EXPLORER_URLS: dict[int, str] = {
    1:        "https://etherscan.io/tx/",
    11155111: "https://sepolia.etherscan.io/tx/",
    8453:     "https://basescan.org/tx/",
    84532:    "https://sepolia.basescan.org/tx/",
    137:      "https://polygonscan.com/tx/",
    42161:    "https://arbiscan.io/tx/",
}


class EVMPaymentAdapter(BasePaymentAdapter):
    def __init__(self, rpc_url=None, private_key=None, chain_id=None, gas_limit=21_000):
        if not _web3_available:
            raise AEPConfigurationError("web3 not installed. pip install 'web3>=6.0.0'")
        self._rpc_url   = rpc_url   or os.environ.get("AEP_RPC_URL", "")
        # Use secrets management layer to get private key
        if private_key is not None:
            self._raw_key = private_key
        else:
            try:
                self._raw_key = get_evm_private_key()
            except AEPConfigurationError as e:
                # Fall back to environment variable for backward compatibility
                self._raw_key = os.environ.get("AEP_PRIVATE_KEY", "")
                if not self._raw_key:
                    raise AEPConfigurationError(
                        f"EVM private key not found via secrets management: {e}. "
                        "Set AEP_PRIVATE_KEY or configure secrets backend."
                    )
        self._gas_limit = int(os.environ.get("AEP_GAS_LIMIT", str(gas_limit)))
        if not self._rpc_url:  raise AEPConfigurationError("AEP_RPC_URL is not set.")
        if not self._raw_key:  raise AEPConfigurationError("AEP_PRIVATE_KEY is not set.")
        self._w3 = Web3(Web3.HTTPProvider(self._rpc_url))
        if not self._w3.is_connected():
            raise AEPAdapterError(f"Cannot connect to RPC: {self._rpc_url}")
        self._account  = self._w3.eth.account.from_key(self._raw_key)
        self._chain_id = chain_id or (int(os.environ["AEP_CHAIN_ID"]) if "AEP_CHAIN_ID" in os.environ else self._w3.eth.chain_id)

    def send_payment(self, to, amount, metadata=None):
        try:
            checksum_to = Web3.to_checksum_address(to)
        except ValueError as exc:
            return _err(f"Invalid address: {exc}")
        amount_wei = Web3.to_wei(amount, "ether")
        try:
            base_fee = self._w3.eth.get_block("latest")["baseFeePerGas"]
            priority = Web3.to_wei(float(os.environ.get("AEP_PRIORITY_GWEI", "1.5")), "gwei")
            max_fee  = base_fee * 2 + priority
        except Exception:
            max_fee = priority = self._w3.eth.gas_price
        nonce = self._w3.eth.get_transaction_count(self._account.address, "pending")
        tx = {"type": 2, "chainId": self._chain_id, "to": checksum_to,
              "value": amount_wei, "gas": self._gas_limit,
              "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority, "nonce": nonce}
        try:
            signed  = self._account.sign_transaction(tx)
            tx_hash_bytes = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=120)
        except Exception as exc:
            return _err(str(exc))
        tx_hash = receipt["transactionHash"].hex()
        status  = "success" if receipt["status"] == 1 else "failed"
        return {"tx_hash": tx_hash, "status": status, "block": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "error": None if status == "success" else "Transaction reverted",
                "explorer_url": _explorer(self._chain_id, tx_hash)}

    def is_valid_address(self, address):
        if not address or not isinstance(address, str): return False
        try: Web3.to_checksum_address(address); return True
        except ValueError: return False


def _explorer(chain_id, tx_hash):
    base = EXPLORER_URLS.get(chain_id)
    return f"{base}{tx_hash}" if base else None

def _err(message):
    return {"tx_hash": None, "status": "failed", "block": None,
            "gas_used": None, "error": message, "explorer_url": None}
