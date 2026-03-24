from __future__ import annotations
import json, logging, os, time
from pathlib import Path
from typing import Any
log = logging.getLogger("aaip.aep.anchor_chain")
_web3_ok = False
try:
    from web3 import Web3
    from eth_account import Account
    _web3_ok = True
except ImportError:
    pass
_ABI_PATH = Path(__file__).parent.parent.parent.parent / "contracts" / "abi.json"
_INLINE_ABI = [
    {"inputs":[{"internalType":"string","name":"agentId","type":"string"},
               {"internalType":"bytes32","name":"poeHash","type":"bytes32"},
               {"internalType":"bytes32","name":"paymentTx","type":"bytes32"}],
     "name":"anchor","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"bytes32","name":"poeHash","type":"bytes32"}],
     "name":"isAnchored","outputs":[{"internalType":"bool","name":"","type":"bool"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],
     "name":"owner","outputs":[{"internalType":"address","name":"","type":"address"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"addr","type":"address"}],
     "name":"authorise","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"address","name":"addr","type":"address"}],
     "name":"deauthorise","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"address","name":"newOwner","type":"address"}],
     "name":"transferOwnership","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"address","name":"","type":"address"}],
     "name":"authorised","outputs":[{"internalType":"bool","name":"","type":"bool"}],
     "stateMutability":"view","type":"function"},
]
class OnChainAnchorAdapter:
    """Anchors PoE hashes to Base Sepolia via PoEAnchor.sol."""
    def __init__(self, rpc_url=None, private_key=None, contract_address=None):
        self._rpc    = rpc_url          or os.environ.get("AEP_RPC_URL","")
        self._key    = private_key      or os.environ.get("AEP_PRIVATE_KEY","")
        self._addr   = contract_address or os.environ.get("POE_ANCHOR_ADDRESS","")
        self._on     = bool(self._rpc and self._key and self._addr and _web3_ok)
        if self._on:
            self._w3  = Web3(Web3.HTTPProvider(self._rpc))
            self._acc = Account.from_key(self._key)
            abi = json.loads(_ABI_PATH.read_text()) if _ABI_PATH.exists() else _INLINE_ABI
            self._c   = self._w3.eth.contract(
                address=Web3.to_checksum_address(self._addr), abi=abi)
            log.info("OnChainAnchorAdapter ready at %s", self._addr)
        else:
            log.warning("OnChainAnchorAdapter disabled — chain not configured, using local JSON")
    def anchor(self, agent_id: str, poe_hash: str, payment_tx: str) -> dict[str, Any]:
        if not self._on:
            return self._local(agent_id, poe_hash, payment_tx)
        try:
            pb = bytes.fromhex(poe_hash.lstrip("0x").zfill(64))
            tb = bytes.fromhex(payment_tx.lstrip("0x").zfill(64))

            nonce = self._w3.eth.get_transaction_count(self._acc.address,"pending")
            base  = self._w3.eth.get_block("latest")["baseFeePerGas"]
            tip   = Web3.to_wei("0.01","gwei")
            tx = self._c.functions.anchor(agent_id, pb, tb).build_transaction({
                "chainId": self._w3.eth.chain_id, "gas": 80_000, "nonce": nonce,
                "maxFeePerGas": base*2+tip, "maxPriorityFeePerGas": tip,
            })
            signed  = self._acc.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            h   = receipt["transactionHash"].hex()
            ok  = receipt["status"] == 1
            url = f"https://sepolia.basescan.org/tx/0x{h}"
            log.info("Anchor %s on-chain: %s", "OK" if ok else "FAIL", url)
            return {"status":"success" if ok else "failed",
                    "anchor_tx":f"0x{h}","explorer_url":url,
                    "poe_hash":poe_hash,"agent_id":agent_id,"on_chain":True}
        except Exception as exc:
            log.error("On-chain anchor failed: %s", exc)
            return self._local(agent_id, poe_hash, payment_tx, error=str(exc))
    def _local(self, agent_id, poe_hash, payment_tx, error=None):
        store = Path(os.environ.get("AEP_ANCHOR_PATH","~/.aaip-anchors.json")).expanduser()
        if store.exists():
            content = store.read_text()
            recs = json.loads(content) if content.strip() else []
        else:
            recs = []
        recs.append({"agent_id":agent_id,"poe_hash":poe_hash,"payment_tx":payment_tx,
                     "anchored_at":time.time(),"on_chain":False,
                     "fallback_reason":error or "chain not configured"})
        tmp = store.with_suffix(".tmp")
        tmp.write_text(json.dumps(recs, indent=2))
        tmp.replace(store)
        return {"status":"success","anchor_tx":None,"explorer_url":None,
                "poe_hash":poe_hash,"agent_id":agent_id,"on_chain":False}
_singleton: OnChainAnchorAdapter | None = None
def get_anchor_adapter() -> OnChainAnchorAdapter:
    global _singleton
    if _singleton is None:
        _singleton = OnChainAnchorAdapter()
    return _singleton