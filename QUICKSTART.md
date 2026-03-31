# AAIP — 10-Minute Integration Guide

Add cryptographic execution verification to any agent in under 10 minutes.

---

## 1. Install (30 seconds)

```bash
pip install aaip
```

That's it. No API key, no account, no config. Everything runs locally.

---

## 2. Your first verified agent (2 minutes)

```python
from aaip import aaip_agent

@aaip_agent
def my_agent(task: str) -> str:
    # your existing agent logic here
    return "result"

result = my_agent("Analyse AI frameworks")

print(result.verified)    # True
print(result.agent_id)    # "8f21d3a4b7c91e2f"  (auto-generated, persisted)
print(result.consensus)   # "APPROVED"
print(result.output)      # "result"
print(result)             # [AAIP ✔ VERIFIED] agent=8f21d3a4 validators=3/3 hash=e461cfc7...
```

**That's the full integration.** One import, one decorator.

The decorator automatically:
- Generates your agent's ed25519 keypair on first run (saved to `.aaip-identity.json`)
- Records execution into a signed Proof of Execution
- Runs 3 local validators to verify the trace
- Returns your original output wrapped in an `AAIPResult`

---

## 3. Record tools and model (2 minutes)

```python
from aaip import aaip_agent

@aaip_agent(tools=["web_search", "read_url"], model="gpt-4o", validators=3)
def research_agent(task: str) -> str:
    results = web_search(task)
    return summarise(results)

result = research_agent("Latest AI safety research")
print(result.verified)       # True
print(result.approve_count)  # 3
```

---

## 4. Manual tool recording (3 minutes)

For more control, use the context manager:

```python
from aaip import aaip_task

with aaip_task("Summarise Q3 report") as t:
    data = read_pdf("q3.pdf")
    t.tool("read_pdf")

    summary = llm.complete(data)
    t.tool("llm_complete").model("gpt-4o")

    t.output(summary)

print(t.result.verified)   # True
print(t.result.poe_hash)   # deterministic sha256 of execution trace
```

---

## 5. LangChain (one line)

```python
from aaip.quick import aaip_langchain

# Wrap your existing chain
chain = aaip_langchain(your_chain)

# Use exactly as before — result is an AAIPResult
result = chain.invoke({"input": "Analyse this dataset"})
print(result.verified)
print(result.output)   # original chain output
```

---

## 6. CrewAI (one line)

```python
from aaip.quick import aaip_crewai

crew = aaip_crewai(your_crew)
result = crew.kickoff(inputs={"topic": "AI trends"})
print(result.verified)
```

---

## 7. Verify an existing PoE

```python
from aaip import verify

result = verify(poe_dict)
print(result.verified)
print(result.signals)   # [] if clean, or ["HASH_MISMATCH", ...] if fraud
```

---

## AAIPResult fields

| Field | Type | Description |
|-------|------|-------------|
| `output` | any | Original agent output |
| `verified` | bool | True if consensus APPROVED |
| `consensus` | str | "APPROVED" or "REJECTED" |
| `agent_id` | str | 16-char hex agent identifier |
| `poe_hash` | str | sha256 of canonical execution trace |
| `signature` | str | ed25519 signature over poe_hash |
| `approve_count` | int | Validators that approved |
| `total_validators` | int | Total validators in panel |
| `signals` | list | Fraud signals detected (empty if clean) |

---

## What happens automatically

| Thing | Manual work needed |
|-------|--------------------|
| Keypair generation | None — auto on first run |
| agent_id derivation | None — sha256(public_key)[:16] |
| PoE hash computation | None — deterministic from execution |
| ed25519 signing | None — happens in decorator |
| Validator consensus | None — runs locally |
| Identity persistence | None — saved to `.aaip-identity.json` |

**Add `.aaip-identity.json` to your `.gitignore`** — it contains your private key.

---

## That's it

Full protocol docs: [`docs/aaip-spec.md`](docs/aaip-spec.md)  
Security model: [`docs/security.md`](docs/security.md)  
More examples: [`examples/`](examples/)
