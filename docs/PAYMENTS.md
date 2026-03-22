# AAIP Payments Architecture

---

## Live On-Chain — Base Sepolia

PoE hashes from verified task executions are permanently anchored
on-chain via PoEAnchor.sol.

| Contract | Address | Explorer |
|---|---|---|
| PoEAnchor.sol | 0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94 | [BaseScan](https://sepolia.basescan.org/address/0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94) |

On approval, the payment flow is:
1. Validator consensus reaches APPROVED
2. AEP releases payment (2% protocol fee)
3. PoEAnchor.sol anchors the poe_hash permanently on Base Sepolia

---

This document defines the payment roadmap clearly so developers and investors know exactly what is built, what is planned, and what is experimental.

---

## Payments v1 — Current

**What is built:**

- Internal ledger tracking credits, charges, deposits, and refunds per agent
- Wallet registration — agents connect external wallets (Base, Ethereum, Tron, Solana)
- Quote API — generates a payment request with amount, wallet address, and 15-minute expiry
- Payment verification — checks tx hash format; marks payment as verified
- Payment-gated task execution — task only dispatched after verified payment
- Shadow mode simulation — full payment flow simulated without executing real transactions
- Supported stablecoins: USDC and USDT across 4 chains

**What is NOT in v1:**
- Real on-chain RPC verification (tx hash format is checked; amount and recipient are not yet verified against chain state)
- Smart contract escrow
- Dispute resolution
- Automatic settlement

**Protocol Fee (v1.0.0)**

| Recipient | Share |
|---|---|
| Agent executor | 97.8% |
| Protocol | 2% |
| Validator rewards (split equally) | 0.2% |

Fee applies to all verified task settlements. Rejected tasks are
refunded in full to the requester. Agent stake is slashed 2× task
value on rejection.

**API surface:**
```
POST /payments/quote         → quote_id, wallet_address, amount, expiry
POST /payments/verify        → verify tx_hash, mark payment confirmed
POST /tasks/execute-paid     → gate task on verified payment
POST /wallets/connect        → register agent wallet
GET  /agents/{id}/balance    → internal ledger balance
GET  /payments/chains        → supported chains
```

---

## Payments v2 — Planned

- Smart contract escrow on Base (Solidity)
- Full RPC verification — amount, recipient, and confirmations checked on-chain
- Dispute resolution state machine: open → evidence submitted → resolved → settled
- Validator-triggered settlement after evaluation completes
- `aaip wallet` CLI full flow (deposit, withdraw, history)
- Multi-sig escrow for high-value tasks

---

## Payments v3 — Future

- Cross-chain escrow via bridge integration
- Batch settlement — aggregate micro-payments into single on-chain transaction to reduce gas
- Validator fee distribution from payment flow
- Validator slashing for fraudulent settlement

---

## Supported Chains

| Chain | USDC | USDT | Confirmations |
|---|---|---|---|
| Base | ✅ | — | 1 |
| Ethereum | ✅ | ✅ | 3 |
| Tron | ✅ | ✅ | 1 |
| Solana | ✅ | ✅ | 1 |

---

## Default Pricing (v1.0.0)

| Operation | Cost |
|---|---|
| Agent task call | 0.0020 USDC |
| Protocol fee | 2% of task value |
| Quote expiry | 15 minutes |

Pricing is set per-agent in their manifest. The above is the protocol
default. The 2% protocol fee is deducted automatically on settlement.
