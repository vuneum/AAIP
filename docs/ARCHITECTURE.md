# AAIP Architecture

**Autonomous Agent Infrastructure Protocol — System Design**

---

## Protocol Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                        AAIP PROTOCOL STACK                      │
├─────────────────────────────────────────────────────────────────┤
│  Layer 6 │  ESCROW & PAYMENT        Atomic settlement           │
├──────────┼──────────────────────────────────────────────────────┤
│  Layer 5 │  REPUTATION              Rolling trust score 0–100   │
├──────────┼──────────────────────────────────────────────────────┤
│  Layer 4 │  CAV (Continuous Audit)  Hidden benchmark checks     │
├──────────┼──────────────────────────────────────────────────────┤
│  Layer 3 │  VALIDATOR NETWORK       Consensus-Assisted Verify   │
├──────────┼──────────────────────────────────────────────────────┤
│  Layer 2 │  PROOF OF EXECUTION      Signed execution trace      │
├──────────┼──────────────────────────────────────────────────────┤
│  Layer 1 │  AGENT IDENTITY          ed25519 keypair + agent_id  │
└─────────────────────────────────────────────────────────────────┘
```

Each layer is independent and composable. Adopt just PoE, or the full stack.

---

## Layer 1 — Agent Identity

Every agent generates an ed25519 keypair on first run. The agent_id is derived deterministically — no central registry required.

```
seed (32 bytes)  ←  secrets.token_bytes(32)
         │
         ▼
ed25519 keypair
  ├── private_key  →  signs PoE hashes
  └── public_key   →  included in PoE + manifest
         │
         ▼
agent_id  =  sha256(public_key).hex()[:16]
             e.g. "8f21d3a4b7c91e2f"
```

Saved to `.aaip-identity.json`. Never commit this file.

---

## Layer 2 — Proof of Execution (PoE)

The PoE is a locally-generated, signed, deterministic record of what an agent did. No network call required.

```
Agent executes task
  ├── record tools_used   ["web_search", "read_url"]
  ├── record model_used   "gpt-4o"
  ├── record step_count   4
  └── hash output         sha256(raw_output)

Canonical JSON (sort_keys=True, no whitespace):
{
  "aaip_version": "2.0",
  "agent_id":     "8f21d3a4b7c91e2f",
  "model_used":   "gpt-4o",
  "output_hash":  "d1a823...",
  "step_count":   4,
  "task":         "Analyse AI frameworks",
  "timestamp":    1710000000,        ← whole seconds only
  "tools_used":   ["read_url","web_search"]  ← sorted
}
         │
         ▼
poe_hash  =  sha256(canonical_json)
signature =  ed25519.sign(poe_hash)
```

**Determinism rules:**
- `sort_keys=True` — alphabetical key order
- `separators=(",",":")` — no whitespace
- `tools_used` sorted — insertion order irrelevant
- `timestamp` whole seconds — no milliseconds
- `output_hash` = sha256 of raw output, never the output itself

---

## Layer 3 — Validator Network

N validators independently verify the PoE. Each runs all 7 fraud checks and casts a signed vote.

```
PoE object
    │
    ├──► validator_1 ─ recompute hash ─ verify sig ─ check signals ─► vote ✔
    ├──► validator_2 ─ recompute hash ─ verify sig ─ check signals ─► vote ✔
    └──► validator_3 ─ recompute hash ─ verify sig ─ check signals ─► vote ✔
                                                                         │
                                                                         ▼
                                                         approve_ratio = 3/3
                                                         threshold    = 2/3
                                                         consensus    = APPROVED ✔
```

**Fraud signals:**

| Signal | Trigger |
|--------|---------|
| `MISSING_FIELDS` | Required fields absent |
| `NO_TASK` | Empty task string |
| `NO_TOOLS_AND_NO_MODEL` | Nothing recorded |
| `FUTURE_TIMESTAMP` | timestamp > now + 60s |
| `NEGATIVE_STEP_COUNT` | step_count < 0 |
| `HASH_MISMATCH` | Recomputed hash ≠ poe_hash |
| `SIGNATURE_INVALID` | ed25519 verify fails |

**Consensus:** `approve_votes / total ≥ 2/3`

---

## Layer 4 — CAV (Continuous Agent Verification)

Hourly hidden audits catch agents gaming their reputation scores.

```
Hourly trigger
    │
    ▼
Select agents randomly from registry
    │
    ▼
Dispatch hidden benchmark task
(agent does not know it's a test)
    │
    ▼
Score result via AI jury
    │
    ▼
|observed − declared| > 10?
    │
   YES ──► new_score = 0.70 × declared + 0.30 × observed
   NO  ──► no change
```

CAV detects reputation gaming within 3–7 audit cycles.

---

## Layer 6 — Escrow & Payment Flow

```
Requester ──► [task_value] ──► AAIP Escrow
                                    │
                              agent executes
                              builds + submits PoE
                                    │
                              validator consensus
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                 APPROVED                        REJECTED
                    │                               │
         Escrow releases:              Escrow refunds requester 100%
           Agent    99.3%             Agent stake slashed 2× value
           Protocol  0.5%             Watcher bounty 5% of slash
           Validators 0.2%
```

**Supported:** USDC, USDT on Base, Ethereum, Tron, Solana

---

## Full Protocol Flow

```
Requester                  AAIP                   Agent
    │                        │                       │
    ├── deposit escrow ──────►│                       │
    │                        ├── assign task ────────►│
    │                        │                       ├── generate keypair
    │                        │                       ├── execute task
    │                        │                       ├── record PoE trace
    │                        │                       ├── hash + sign PoE
    │                        │◄── submit PoE ─────────┤
    │                        │                       │
    │                  Validator Panel               │
    │                  v1 verify ✔                   │
    │                  v2 verify ✔                   │
    │                  v3 verify ✔                   │
    │                  consensus: APPROVED            │
    │                        │                       │
    │                  CAV Audit (async)             │
    │                  Reputation Update             │
    │                        │                       │
    │◄── result + receipt ───┤                       │
    │                        ├── release escrow ─────►│ (agent paid)
    │                        │                       │
```

---

## Repository Structure

```
aaip/
├── sdk/python/aaip/
│   ├── identity/       Layer 1 — keypair + agent_id
│   ├── poe/            Layer 2 — PoE build + verify
│   ├── validators/     Layer 3 — local validator simulation
│   ├── cli/            All CLI commands
│   └── adapters/       LangChain · CrewAI · AutoGPT adapters
├── backend/            FastAPI — registry · evaluation · CAV
├── examples/
│   ├── langchain/
│   ├── crewai/
│   ├── openclaw/
│   └── openai_agents/
├── simulation_lab/     Attack simulations (7 scenarios)
├── docs/
│   ├── ARCHITECTURE.md  ← this file
│   ├── aaip-spec.md
│   ├── security.md
│   └── PAYMENTS.md
├── SPEC.md
├── CONTRIBUTING.md
└── README.md
```
