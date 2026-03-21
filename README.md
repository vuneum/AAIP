# AAIP + AEP
### The Trust + Payment Stack for the Autonomous Agent Economy
> AI agents execute real tasks, handle money, and make decisions autonomously.
> There is no standard way to prove an agent did the work it claims — or pay it trustlessly.
>
> **AAIP + AEP solves both.**
---
## Live On-Chain (Base Sepolia)

| Contract | Address | Explorer |
|---|---|---|
| PoEAnchor.sol | `0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94` | [BaseScan](https://sepolia.basescan.org/address/0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94) |

| TX | Hash | Purpose |
|---|---|---|
| Deploy | [0xb0db2c7d...](https://sepolia.basescan.org/tx/0xb0db2c7da8fdd7952c0841ff3a727d3414e10a737cd0538570ae0348a44b843a) | Contract deployment |
| Anchor #1 | [0x1140b773...](https://sepolia.basescan.org/tx/0x1140b773f2d9d8fb727c381fa151c1aa28a53d5e88596586f7b3e0782a3d2bb8) | First PoE anchored |
| Anchor #2 | [0xe0f88b53...](https://sepolia.basescan.org/tx/0xe0f88b53595e8da6ed6e84259ba335f32b55c704481b6d8f64a41ecf656af9b4) | Second PoE anchored |
| Anchor #3 | [0x3df287fd...](https://sepolia.basescan.org/tx/0x3df287fd1afb3ce0efcd52fc6938acdec7446a048ef2e837252d69adff600fb0) | Third PoE anchored |
---
## Architecture
| Layer | Protocol | What it does |
|---|---|---|
| Trust | **AAIP** | ed25519 identity, PoE, 3-validator consensus, 7 fraud signals, CAV, reputation |
| Payment | **AEP** | EVM lifecycle, idempotency, replay protection, billing, SQLite audit |
| On-Chain | **PoEAnchor.sol** | Immutable Base Sepolia registry: poe_hash => payment tx |
---
## Full Flow
```
Agent A (Requester)        Agent B (Worker)       Base Sepolia
     |                           |                    |
     |-- submit task ----------->|                    |
     |                  run_task() + sign PoE         |
     |              3 validators -> APPROVED          |
     |-- AEP execute_payment() ------EIP-1559 tx ---->|
     |                           PoEAnchor.anchor() ->|
     |<-- ExecutionReceipt with BaseScan URLs ---------|
```
---
## Quickstart
```bash
pip install aaip web3 python-dotenv
cp .env.example .env        # fill in your keys
python demo_two_agent.py --mock --fast   # no ETH needed
python demo_two_agent.py --fast          # real on-chain
```
---
