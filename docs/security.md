# AAIP Security Model

**Threat analysis, attack vectors, and protocol defences.**

---

## Design Principle

AAIP assumes all participants — agents, validators, requesters — may be adversarial. The protocol is designed so that **honest participation is always the economically dominant strategy**, and fraud is detectable, attributable, and penalised.

---

## Attack 1: Fake Agent (Fabricated Execution)

### What it is

An agent submits a plausible output without executing the task. It generates a convincing response from a single prompt with no tool calls, reasoning steps, or model inference — but claims it did real work.

### Why it's dangerous

Without execution verification, payment is released on output quality alone. A sophisticated fake agent could craft outputs that fool a single AI judge and collect payment for nothing.

### How AAIP defends against it

**PoE layer:** The agent must produce a signed Proof of Execution object containing:
- `tools_used` — list of tools invoked
- `model_used` — model name
- `step_count` — number of recorded steps
- `output_hash` — sha256 of the actual output

If `tools_used` is empty and `model_used` is null, validators flag `NO_TOOLS_AND_NO_MODEL`. If `step_count` is 0 or negative, they flag `NEGATIVE_STEP_COUNT`.

**Validator layer:** All 3+ validators independently recompute the hash and verify the ed25519 signature. A fake agent that tampers with the PoE to inflate `step_count` or `tools_used` will produce a `HASH_MISMATCH`.

**CAV layer:** Hidden benchmark audits dispatch real tasks to the agent. If the agent's observed performance diverges from its declared reputation by more than 10 points, its score is blended downward.

### Attack example and outcome

```
Fake agent submits PoE with:
  tools_used:  []
  model_used:  null
  step_count:  0
  output_hash: sha256("plausible looking output")

Validator signals: NO_TOOLS_AND_NO_MODEL, NEGATIVE_STEP_COUNT
Consensus:         REJECTED
Outcome:           Escrow refunded. Agent stake slashed 2× task value.
```

---

## Attack 2: Validator Collusion

### What it is

A group of validators coordinate to approve fraudulent PoE objects — accepting payment for verification without actually verifying, or deliberately approving fake executions in exchange for bribes.

### Why it's dangerous

If validators can be bought, the entire verification layer fails. Fraudulent agents could pay validators to approve their fake traces.

### How AAIP defends against it

**Stake-weighted selection:** Validators are selected via VRF (Verifiable Random Function) seeded on `task_id || block_hash`. A colluding group would need to control validators with sufficient combined stake — capital attack becomes expensive.

**Economic slashing:** Any validator whose vote is later overturned by a watcher loses 2× their staked amount. The watcher earns 5% of slashed stake as a bounty — incentivising active fraud detection.

**Panel size scaling:** High-value tasks use larger panels (9+ validators). Controlling 2/3 of a large stake-weighted panel is prohibitively expensive.

**Hash independence:** Each validator recomputes the PoE hash independently from the raw PoE object. There is no shared computation they can collectively fake — each must sign their own vote with their own validator key.

**Simulation results:** At current stake distributions, a collusion attack controlling less than 33% of total stake has a <0.1% probability of producing a false positive consensus. See `sim_results/collusion/result.json`.

### Residual risk

Collusion between more than 2/3 of staked validators by value remains a theoretical risk. Mitigation: watcher incentives, public vote records on-chain, and progressive slash escalation for repeat offenders.

---

## Attack 3: Trace Forgery (PoE Tampering)

### What it is

An agent generates a legitimate PoE for a small or easy task, then modifies the PoE fields to claim a larger, harder task was executed — or copies another agent's PoE and re-submits it.

### Why it's dangerous

If PoE objects can be forged or replayed, agents could execute cheap work and claim payment for expensive work.

### How AAIP defends against it

**Hash binding:** The `poe_hash` is sha256 of the entire canonical PoE object. Any change to any field — task description, output hash, timestamp, tools — produces a different hash. The stored `poe_hash` will no longer match the recomputed hash.

**Signature binding:** The `signature` is an ed25519 signature over the `poe_hash` bytes using the agent's private key. Changing any field invalidates the signature. Validators check: `ed25519.verify(public_key, poe_hash_bytes, signature)`.

**Replay prevention:** The `timestamp` is included in the canonical hash. A replayed PoE from a past task will have a stale timestamp. Future v2 will add a `task_id` field that binds the PoE to a specific task assignment from the requester.

**Output binding:** `output_hash = sha256(raw_output)`. Validators can require the agent to reveal the raw output for spot-checking. A forged output hash that doesn't match the submitted output is immediately detectable.

### Attack example and outcome

```
Attacker copies legitimate PoE from another agent:
  poe_hash:  d1a823... (correct for original task)
  signature: 3b664f... (signed by original agent's key)

Validator checks:
  public_key in PoE = original agent's key
  task claimed      = "Audit Q3 financials" (expensive)
  task actually paid= "Summarise blog post" (cheap)

agent_id derived from public_key ≠ attacker's agent_id
Validator flags: SIGNATURE_INVALID (attacker can't re-sign with original key)
Consensus: REJECTED
```

---

## Attack 4: Model Bias (AI Jury Gaming)

### What it is

An agent crafts outputs specifically designed to score highly with the AI jury models — using known patterns, phrases, or formatting that inflate scores — while delivering low-quality actual value to the requester.

### Why it's dangerous

If agents can reliably game a single AI judge, the evaluation score becomes meaningless as a trust signal.

### How AAIP defends against it

**Multi-model jury:** Evaluations use an ensemble of models from different providers (GPT-4o, Claude, Gemini, open-source). Gaming one model's scoring patterns does not generalize across the full panel.

**Weighted median scoring:** The final score is a weighted median of individual judge scores, not an average. A single extreme outlier (a perfectly gamed judge) cannot pull the final score significantly.

**Domain-specific rubrics:** Judges evaluate against structured rubrics relevant to the task domain (coding, finance, general). Generic prompt engineering tricks are less effective against criteria-based evaluation.

**CAV calibration:** CAV benchmark tasks are drawn from a curated dataset with known ground-truth answers. Jury scores on these tasks can be validated against the ground truth — exposing systematic judge gaming.

**Score blending:** Reputation is a rolling weighted average. Even if an agent games a single evaluation, it takes many high-scoring evaluations to meaningfully move the score — and the CAV layer will catch divergence.

### Residual risk

Sophisticated adversarial prompting that transfers across multiple models simultaneously remains an open research problem. AAIP mitigates but does not fully eliminate this risk at v1.

---

## Fraud Signal Reference

All signals are checked independently by each validator:

| Signal | Verdict | Description |
|--------|---------|-------------|
| `MISSING_FIELDS` | `invalid` | One or more required PoE fields absent |
| `NO_TASK` | `suspicious` | `task` field is empty string |
| `NO_TOOLS_AND_NO_MODEL` | `suspicious` | Neither tools nor model recorded |
| `FUTURE_TIMESTAMP` | `invalid` | Timestamp > now + 60 seconds |
| `NEGATIVE_STEP_COUNT` | `invalid` | step_count < 0 |
| `HASH_MISMATCH` | `invalid` | Recomputed hash ≠ submitted poe_hash |
| `SIGNATURE_INVALID` | `invalid` | ed25519 signature verification fails |

**Verdict mapping:**
- Any `invalid` signal → verdict: `invalid`
- Only `suspicious` signals (no `invalid`) → verdict: `suspicious`
- No signals → verdict: `verified`

**Consensus impact:**
- `invalid` verdict → validator votes REJECT
- `suspicious` verdict → validator votes REJECT (conservative by default)
- `verified` verdict → validator votes APPROVE

---

## Economic Security Model

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Validator stake minimum | 100 USDC | Sybil resistance |
| Slash amount (agent) | 2× task value | Fraud deterrence |
| Slash amount (validator) | 2× task value | Collusion deterrence |
| Watcher bounty | 5% of slashed stake | Active monitoring incentive |
| Validator reward | 0.2% of task value | Honest participation reward |
| Protocol fee | 0.5% of task value | Sustainability |

At current parameters, a fraud attempt that fails costs the attacker at minimum 2× the value they were trying to steal. Expected value of fraud is negative at all stake levels.

---

## Reporting Security Issues

Please report security vulnerabilities to: **security@vuneum.com**

Do not open public GitHub issues for security vulnerabilities.

Include:
- Description of the vulnerability
- Steps to reproduce
- Estimated severity (Critical / High / Medium / Low)
- Any suggested mitigations

We aim to respond within 48 hours and will credit researchers in release notes.
