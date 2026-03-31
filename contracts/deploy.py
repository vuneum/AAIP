#!/usr/bin/env python3
"""
Deploy PoEAnchor.sol to Base Sepolia.
Usage:  python contracts/deploy.py [--authorise ADDRESS]
Writes POE_ANCHOR_ADDRESS to .env automatically.
If PoEAnchor.bin is missing, the script will exit with instructions to recompile.
"""
import os, json, sys, argparse
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key
from web3 import Web3
from eth_account import Account

load_dotenv()
RPC_URL     = os.environ["AEP_RPC_URL"]
PRIVATE_KEY = os.environ["AEP_PRIVATE_KEY"]
CHAIN_ID    = int(os.environ.get("AEP_CHAIN_ID", "84532"))
ENV_FILE    = Path(__file__).parent.parent / ".env"
ABI_PATH    = Path(__file__).parent / "abi.json"
BYTECODE_PATH = Path(__file__).parent / "PoEAnchor.bin"

def load_bytecode():
    """Load bytecode from compiled binary file, exit with instructions if missing."""
    if not BYTECODE_PATH.exists():
        sys.stderr.write(f"Error: {BYTECODE_PATH} not found.\n")
        sys.stderr.write("You must compile the contract with solc:\n")
        sys.stderr.write("  solc --bin --abi --optimize --runs 200 contracts/PoEAnchor.sol\n")
        sys.stderr.write("This will produce PoEAnchor.bin and abi.json in the contracts directory.\n")
        sys.stderr.write("Alternatively, if you have the bytecode as a hex string, create the file manually.\n")
        sys.exit(1)
    with open(BYTECODE_PATH, "r") as f:
        hex_str = f.read().strip()
    if not hex_str.startswith("0x"):
        hex_str = "0x" + hex_str
    return hex_str

def deploy(authorise_address: Optional[str] = None):
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    assert w3.is_connected(), f"Cannot connect to {RPC_URL}"
    print(f"Chain ID: {w3.eth.chain_id}  (expected 84532)")
    account = Account.from_key(PRIVATE_KEY)
    bal = w3.eth.get_balance(account.address)
    print(f"Deployer: {account.address}")
    print(f"Balance:  {w3.from_wei(bal,'ether'):.6f} ETH")
    assert bal > 0, "No ETH — get testnet ETH first (see Section 2.3)"
    
    with open(ABI_PATH) as f:
        ABI = json.load(f)
    BYTECODE = load_bytecode()
    
    contract = w3.eth.contract(abi=ABI, bytecode=BYTECODE)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    block = w3.eth.get_block("latest")
    base  = block.get("baseFeePerGas", Web3.to_wei("0.001", "gwei"))
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
    addr = receipt["contractAddress"]
    assert addr is not None, "Contract address missing in receipt"
    addr_str = str(addr)
    print(f"\nCONTRACT DEPLOYED: {addr_str}")
    print(f"BaseScan: https://sepolia.basescan.org/address/{addr_str}")
    set_key(str(ENV_FILE), "POE_ANCHOR_ADDRESS", addr_str)
    print(f"POE_ANCHOR_ADDRESS written to .env")
    
    if authorise_address is not None:
        print(f"Authorising {authorise_address}...")
        contract_instance = w3.eth.contract(address=addr, abi=ABI)
        auth_tx = contract_instance.functions.authorise(authorise_address).build_transaction({
            "chainId": CHAIN_ID, "gas": 100_000, "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "maxFeePerGas": base*2+tip, "maxPriorityFeePerGas": tip,
        })
        signed_auth = account.sign_transaction(auth_tx)
        auth_hash = w3.eth.send_raw_transaction(signed_auth.raw_transaction)
        print(f"Authorise tx: https://sepolia.basescan.org/tx/{auth_hash.hex()}")
        auth_receipt = w3.eth.wait_for_transaction_receipt(auth_hash, timeout=60)
        if auth_receipt["status"] == 1:
            print("Authorisation successful.")
        else:
            print("Authorisation transaction failed.")
    
    return addr

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy PoEAnchor contract")
    parser.add_argument("--authorise", type=str, metavar="ADDRESS",
                        help="Address to authorise after deployment")
    args = parser.parse_args()
    deploy(authorise_address=args.authorise)