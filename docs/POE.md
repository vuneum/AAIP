# AAIP Proof of Execution (PoE)

PoE is AAIP's fraud-prevention layer. It proves an agent genuinely performed work — not fabricated output.

---

## PoE v1 — Current

**What is built:**

Agents record every significant step during task execution: tool calls, reasoning steps, LLM calls, API calls. Each step contains a timestamp, input hash, output hash, and latency. The full trace is hashed with SHA-256.

The hash is submitted alongside the evaluation. The AAIP backend recomputes the hash independently and runs 7 fraud detection signals:

| Signal | Verdict | Trigger |
|---|---|---|
| `MISSING_FIELDS` | `invalid` | Required PoE field absent |
| `NO_TASK` | `suspicious` | task field is empty string |
| `NO_TOOLS_AND_NO_MODEL` | `suspicious` | tools_used == [] AND model_used == null |
| `FUTURE_TIMESTAMP` | `invalid` | timestamp > now + 60 seconds |
| `NEGATIVE_STEP_COUNT` | `invalid` | step_count < 0 |
| `HASH_MISMATCH` | `invalid` | Recomputed hash does not match poe_hash |
| `SIGNATURE_INVALID` | `invalid` | ed25519 signature verification fails |

Verdicts: `verified` | `suspicious` | `invalid` | `unverified`

**Privacy model:** Tool inputs and outputs are stored as hashes — raw content is never transmitted to AAIP. Agents retain full IP over their implementation.

---

## PoE v2 — Planned

- Agent signs trace with its registered private key
- API call receipts — third-party API responses included as signed evidence
- Receipt chaining — each step cryptographically references the previous
- Selective disclosure — share proof of specific steps without revealing others
- Dispute evidence — PoE trace used as primary evidence in payment disputes

---

## PoE v3 — Research

- **TEE attestation** — execution inside a Trusted Execution Environment (Intel TDX, AWS Nitro Enclaves). TEE produces a signed attestation that specific code ran with specific inputs.
- **ZK verification** — prove properties of execution (e.g., "used model X", "called API Y") without revealing inputs. zkVM integration (RISC Zero or SP1).
- **Privacy-preserving proofs** — full execution verification without leaking agent logic.

---

## Python SDK Usage

```python
from aaip import ProofOfExecution

with ProofOfExecution(task_id="t-001", agent_id=agent_id, task_description="Research task") as poe:
    poe.tool("web_search", inputs={"q": "AI trends 2025"}, output={"results": [...]}, latency_ms=120)
    poe.reason("Found 5 relevant sources, synthesizing main themes")
    poe.llm_call("gpt-4o", tokens_in=200, tokens_out=500, latency_ms=800)
    poe.api_call("https://api.example.com/data", latency_ms=50)

print(poe.hash)     # SHA-256 of full trace
print(poe.summary)  # step count, tool count, duration
```

---

## Trace Schema (v1)

```json
{
  "task_id": "t-001",
  "agent_id": "yourco/myagent/abc123",
  "task_description": "Research AI trends",
  "started_at_ms": 1710000000000,
  "completed_at_ms": 1710000003500,
  "steps": [
    {
      "step_type": "tool_call",
      "name": "web_search",
      "timestamp_ms": 1710000000500,
      "input_hash": "sha256:...",
      "output_hash": "sha256:...",
      "latency_ms": 120,
      "status": "success"
    }
  ],
  "total_tool_calls": 1,
  "total_llm_calls": 1,
  "poe_hash": "sha256:..."
}
```

---

## On-Chain Anchor

When a PoE receives APPROVED consensus from the validator panel,
the poe_hash is permanently anchored on Base Sepolia via PoEAnchor.sol.

```
Verdict: APPROVED
    │
    ▼
PoEAnchor.sol.anchor(poe_hash)
    │
    ▼
Returns: tx_hash (BaseScan verifiable)
```

**Live contract:**
`0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94` on Base Sepolia

[View on BaseScan →](https://sepolia.basescan.org/address/0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94)

The on-chain record is permanent and tamper-evident. Any party can
independently verify that a specific poe_hash was approved at a
specific block timestamp by querying the contract directly.
