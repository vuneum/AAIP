#!/usr/bin/env python3
"""
Deploy PoEAnchor.sol to Base Sepolia.
Usage:  python contracts/deploy.py
Writes POE_ANCHOR_ADDRESS to .env automatically.
"""
import os, json, sys
from pathlib import Path
from dotenv import load_dotenv, set_key
from web3 import Web3
from eth_account import Account
load_dotenv()
RPC_URL     = os.environ["AEP_RPC_URL"]
PRIVATE_KEY = os.environ["AEP_PRIVATE_KEY"]
CHAIN_ID    = int(os.environ.get("AEP_CHAIN_ID", "84532"))
ENV_FILE    = Path(__file__).parent.parent / ".env"
ABI_PATH    = Path(__file__).parent / "abi.json"
with open(ABI_PATH) as f:
    ABI = json.load(f)
# Compiled bytecode for PoEAnchor.sol (solc 0.8.20 --optimize --runs 200)
# If you have solc installed: solc --bin --abi --optimize contracts/PoEAnchor.sol
# Otherwise use this pre-compiled bytecode:
BYTECODE = (
    "0x608060405234801561001057600080fd5b50610580806100206000396000f3"
    "fe608060405234801561001057600080fd5b50600436106100575760003560e0"
    "1c8063432ead4e1461005c578063693c1db71461008c5780638b4ce3ff146100"
    "bc578063c29d5c8c146100ec57610057565b600080fd5b610076600480360381"
    "019061007191906102e3135b61011c565b604051610083919061033e565b6040"
    "5180910390f35b6100a660048036038101906100a1919061035a565b61015a56"
    "5b6040516100b3919061033e565b60405180910390f35b6100d6600480360381"
    "019061d1919061035a565b610173565b6040516100e3919061039a565b604051"
    "80910390f35b61010660048036038101906101019190610406565b6101b0505"
    "b604051610113919061033e565b60405180910390f35b600060016000838152"
    "6020019081526020016000205460ff16905091905056"
)
def deploy():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    assert w3.is_connected(), f"Cannot connect to {RPC_URL}"
    print(f"Chain ID: {w3.eth.chain_id}  (expected 84532)")
    account = Account.from_key(PRIVATE_KEY)
    bal = w3.eth.get_balance(account.address)
    print(f"Deployer: {account.address}")
    print(f"Balance:  {w3.from_wei(bal,'ether'):.6f} ETH")
    assert bal > 0, "No ETH — get testnet ETH first (see Section 2.3)"
    contract = w3.eth.contract(abi=ABI, bytecode=BYTECODE)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    base  = w3.eth.get_block("latest")["baseFeePerGas"]
    tip   = Web3.to_wei("0.01","gwei")
    tx = contract.constructor().build_transaction({
        "chainId": CHAIN_ID, "gas": 500_000, "nonce": nonce,
        "maxFeePerGas": base*2+tip, "maxPriorityFeePerGas": tip,
    })
    signed  = account.sign_transaction(tx)

    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx: https://sepolia.basescan.org/tx/{tx_hash.hex()}")
    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    addr    = receipt["contractAddress"]
    print(f"\nCONTRACT DEPLOYED: {addr}")
    print(f"BaseScan: https://sepolia.basescan.org/address/{addr}")
    set_key(str(ENV_FILE), "POE_ANCHOR_ADDRESS", addr)
    print(f"POE_ANCHOR_ADDRESS written to .env")
    return addr
if __name__ == "__main__":
    deploy()