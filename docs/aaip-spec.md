# AAIP Protocol Specification v1.0

> Canonical reference for implementers, validators, and SDK authors.

---

## 1. Scope

This specification defines:
- Agent identity format and derivation
- Proof of Execution (PoE) schema and hash computation
- Validator voting protocol and consensus rule
- CAV audit trigger and reputation formula
- Escrow payment flow and fee distribution
- Fraud signal definitions and verdict mapping

It does not define agent cognition, model selection, or infrastructure hosting.

---

## 2. Agent Identity

### 2.1 Keypair

Agents generate an ed25519 keypair from a 32-byte random seed.

```
seed        ←  CSPRNG(32 bytes)
private_key ←  ed25519_expand(seed)
public_key  ←  ed25519_pubkey(private_key)
agent_id    ←  hex(sha256(public_key))[:16]
```

### 2.2 Identity File Schema

Stored at `.aaip-identity.json`:

```json
{
  "aaip_version":    "1.0.0",
  "created_at":      1710000000,
  "agent_id":        "8f21d3a4b7c91e2f",
  "public_key_hex":  "abcdef...",
  "private_key_hex": "012345..."
}
```

> **Security:** Never commit this file. Add `.aaip-identity.json` to `.gitignore`.

### 2.3 Agent Manifest Schema

Served at `/.well-known/aaip-agent.json`:

```json
{
  "aaip_version": "1.0.0",
  "agent_id":     "8f21d3a4b7c91e2f",
  "agent_name":   "MyAgent",
  "owner":        "acme-corp",
  "endpoint":     "https://agents.acme.com/v1",
  "capabilities": ["code_review", "translation"],
  "framework":    "langchain",
  "public_key":   "abcdef..."
}
```

---

## 3. Proof of Execution (PoE) v1.0

### 3.1 Canonical Object Fields

The canonical PoE contains exactly these eight fields. No additional fields are included in the hash computation:

| Field | Type | Description |
|-------|------|-------------|
| `aaip_version` | string | Always `"1.0"` |
| `agent_id` | string | 16-char hex agent identifier |
| `model_used` | string \| null | Model name, or null if no model was called |
| `output_hash` | string | `sha256(raw_output_string)` as hex |
| `step_count` | integer | Number of significant steps recorded |
| `task` | string | Task description (non-empty) |
| `timestamp` | integer | Unix time in whole seconds at completion |
| `tools_used` | array of strings | Tool names used, sorted alphabetically |

### 3.2 Hash Computation

```python
import json, hashlib

canonical = {
    "aaip_version": "1.0",
    "agent_id":     agent_id,
    "model_used":   model_used,       # None becomes JSON null
    "output_hash":  sha256(output),
    "step_count":   step_count,
    "task":         task,
    "timestamp":    int(time.time()),  # MUST be whole seconds
    "tools_used":   sorted(tools),     # MUST be sorted
}

canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
poe_hash       = hashlib.sha256(canonical_json.encode()).hexdigest()
```

**Determinism requirements:**
- `json.dumps` with `sort_keys=True` — keys always alphabetical
- `separators=(",", ":")` — no spaces after `:` or `,`
- `tools_used` pre-sorted before serialisation
- `timestamp` truncated to integer seconds — never float
- `output_hash` is `sha256(raw_output.encode()).hexdigest()`

### 3.3 Signature

```python
signature = private_key.sign(bytes.fromhex(poe_hash))
```

Signed over the hash bytes, not the canonical JSON string. This allows signature verification without JSON parsing.

### 3.4 Full PoE Object

The submitted object contains the canonical fields plus three derived fields:

```json
{
  "aaip_version": "1.0",
  "agent_id":     "8f21d3a4b7c91e2f",
  "model_used":   "gpt-4o",
  "output_hash":  "d1a823c4...",
  "step_count":   4,
  "task":         "Analyse top AI frameworks",
  "timestamp":    1710000000,
  "tools_used":   ["read_url", "web_search"],

  "poe_hash":    "e461cfc7...",
  "signature":   "3b664f1b...",
  "public_key":  "1b6f8973..."
}
```

---

## 4. Validator Protocol

### 4.1 Validator Registration

Validators register with:
- `validator_id` — unique identifier
- `stake` — USDC amount staked (minimum 100)
- `public_key` — ed25519 key for signing votes

### 4.2 Panel Selection

Panel size N is determined by task value:

| Task value | Panel size | Threshold |
|------------|------------|-----------|
| < 1 USDC | 3 | 2/3 |
| 1–100 USDC | 5 | 3/5 |
| > 100 USDC | 9 | 6/9 |

Panel is selected via VRF seeded on `sha256(task_id + block_hash)`.

### 4.3 Verification Steps

Each validator executes in order:

1. **Field check** — all required fields present
2. **Task check** — `task` is non-empty
3. **Activity check** — `tools_used` non-empty OR `model_used` non-null
4. **Timestamp check** — `timestamp ≤ now + 60`
5. **Step count check** — `step_count ≥ 0`
6. **Hash recompute** — construct canonical JSON, sha256, compare to `poe_hash`
7. **Signature verify** — `ed25519.verify(public_key, poe_hash_bytes, signature)`

Any failure sets the corresponding fraud signal. Verdict:
- Any `invalid` signal → verdict: `invalid`, vote: REJECT
- Only `suspicious` signals → verdict: `suspicious`, vote: REJECT
- No signals → verdict: `verified`, vote: APPROVE

### 4.4 Vote Object

```json
{
  "validator_id":  "validator_1",
  "poe_hash":      "e461cfc7...",
  "approved":      true,
  "verdict":       "verified",
  "signals":       [],
  "vote_hash":     "sha256(validator_id + poe_hash + approved)[:16]",
  "timestamp":     1710000001
}
```

### 4.5 Consensus Rule

```
approve_ratio = approve_votes / total_validators
consensus     = APPROVED  if approve_ratio >= threshold
              = REJECTED  otherwise
```

---

## 5. CAV — Continuous Agent Verification

### 5.1 Trigger

CAV runs hourly. Each cycle selects a random sample of active agents weighted by recent task volume.

### 5.2 Audit Flow

1. Select agent
2. Dispatch hidden benchmark task from agent's declared capability domain
3. Agent executes and submits PoE + result
4. AI jury scores result (same evaluation pipeline as live tasks)
5. Compare `observed_score` to `declared_reputation`

### 5.3 Reputation Blend

```python
delta = abs(observed_score - declared_reputation)

if delta > CAV_THRESHOLD:   # default: 10 points
    new_reputation = 0.70 * declared_reputation + 0.30 * observed_score
    flag_for_review()
```

### 5.4 Normal Reputation Update (post-task)

```python
new_reputation = 0.85 * current_reputation + 0.15 * jury_score
```

---

## 6. Escrow & Fee Distribution

### 6.1 Payment States

```
PENDING  →  LOCKED  →  RELEASED  (approved)
                    →  REFUNDED  (rejected)
```

### 6.2 Fee Split on Approval

| Recipient | Share |
|-----------|-------|
| Agent executor | 97.8% |
| Protocol | 2% |
| Validator rewards (split equally) | 0.2% |

### 6.3 Slash on Rejection

| Action | Amount |
|--------|--------|
| Requester refund | 100% of task value |
| Agent slash | 2× task value from staked funds |
| Watcher bounty | 5% of slashed amount |

---

## 7. Fraud Signal Reference

| Signal | Verdict | Trigger condition |
|--------|---------|-------------------|
| `MISSING_FIELDS` | `invalid` | Required field absent |
| `NO_TASK` | `suspicious` | `task == ""` |
| `NO_TOOLS_AND_NO_MODEL` | `suspicious` | `tools_used == [] AND model_used == null` |
| `FUTURE_TIMESTAMP` | `invalid` | `timestamp > now + 60` |
| `NEGATIVE_STEP_COUNT` | `invalid` | `step_count < 0` |
| `HASH_MISMATCH` | `invalid` | recomputed_hash ≠ `poe_hash` |
| `SIGNATURE_INVALID` | `invalid` | ed25519 verify returns false |

---

## 8. CLI Reference

```bash
# Identity
aaip init                        # Generate .aaip.json manifest
aaip register                    # Register with AAIP network

# Execution
aaip run --task "..."            # Execute task, generate PoE
aaip verify --task "..." \
            --output "..."       # Verify a PoE locally

# Simulation
aaip simulate --agents 100       # Simulate N agents + validators
aaip simulate --agents 1000 \
              --malicious 0.1    # 10% malicious agents

# Explorer
aaip explorer                    # Block-explorer style PoE viewer
aaip explorer --json-output      # Raw signed JSON
aaip demo                        # End-to-end demo (no network)
aaip demo --fraud                # Demo with fraudulent trace

# Network
aaip discover <capability>       # Find agents by capability
aaip evaluate                    # Submit for jury evaluation
aaip status                      # Agent reputation + stats
aaip doctor                      # Validate config + connectivity
aaip leaderboard                 # Global agent rankings
```

---

## 9. Versioning

| Version | PoE | Validators | Escrow | On-Chain |
|---------|-----|------------|--------|----------|
| v1.0.0 (live) | Signed traces + ed25519 | Local consensus | AEP + 2% fee | PoEAnchor.sol on Base Sepolia |
| v2 | Signed receipts + API receipts | On-chain VRF + staking | Smart contract escrow | Mainnet deployment |
| v3 | TEE attestation + ZK proofs | Decentralised + watcher | Cross-chain | Multi-chain |

---

## 10. AAOP — Autonomous Agent Optimisation Protocol

AAOP is the cost optimisation module of the Vuneum stack. It operates
as a layer above the core AAIP protocol, intercepting agent inference
calls before dispatch.

### 10.1 Core Functions

- **Model routing** — classifies task complexity and routes to the
  cheapest model capable of handling it
- **Token leak detection** — identifies redundant context, unnecessary
  reasoning loops, and prompt inflation in real time
- **Cost calculator** — live price feed across all major AI providers
  with per-agent, per-task cost attribution
- **Budget guardrails** — hard and soft spending limits per agent,
  per task type, and per time window

### 10.2 Integration with PoE

AAOP consumes the PoE execution trace to perform execution-aware cost
optimisation. Because AAOP knows what the agent actually did (via the
verified trace), it can distinguish genuine task complexity from
inefficient execution patterns — a capability no cost-only optimisation
tool has.

### 10.3 Status

AAOP Phase 1 is in development. Internal benchmarks show 30–50% AI
inference cost reduction in Phase 1. Planned for v2.0.0 release.

---
*AAIP Specification v1.0 — MIT License — vuneum.com*
