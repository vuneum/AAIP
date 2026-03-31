<div align="center">

<br/>

# ⬡ AAIP
### Autonomous Agent Infrastructure Protocol

**The trust layer for the autonomous agent economy.**

<br/>

[![Python 3.9+](https://img.shields.io/badge/Python_3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-FF6A00?style=flat-square)](CHANGELOG.md)
[![Zero Dependencies](https://img.shields.io/badge/Zero_Runtime_Deps-✓-22C55E?style=flat-square)](#quickstart)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-6366F1?style=flat-square)](CONTRIBUTING.md)

<br/>

> AI agents are executing real tasks, handling money, and making decisions autonomously.
> There is no standard way to prove an agent did the work it claims — or that it did it honestly.
>
> **AAIP solves this.**

<br/>

</div>

---

## What AAIP Does

Every agent gets a cryptographic identity. Every execution produces a signed, tamper-evident Proof of Execution. A local validator panel independently verifies the trace before any payment is released.

```
Agent executes task
      │
      ▼
Signs PoE trace  ←  sha256(canonical execution) + ed25519 signature
      │
      ▼
3 validators verify independently  ←  ≥ 2/3 consensus required
      │
      ▼
APPROVED → escrow released    REJECTED → requester refunded + slash
```

No central authority. No trusted intermediary. Cryptographic proof all the way down.

---

## Quickstart

```bash
pip install aaip
```

**Integrate in 3 lines:**

```python
from aaip import aaip_agent

@aaip_agent
def my_agent(task: str) -> str:
    return "your result"          # ← your existing logic, unchanged

result = my_agent("Analyse AI frameworks")
print(result.verified)            # True
print(result.agent_id)            # "8f21d3a4b7c91e2f"
print(result.consensus)           # "APPROVED"
print(result.poe_hash)            # sha256 of signed execution trace
```

The decorator handles everything automatically — keypair generation, PoE construction,
ed25519 signing, and validator consensus. See **[QUICKSTART.md](QUICKSTART.md)** for the full 10-minute guide.

---

## Framework Support

**LangChain — one line**
```python
from aaip.quick import aaip_langchain
chain  = aaip_langchain(your_chain)
result = chain.invoke({"input": "your task"})   # result.verified → True
```

**CrewAI — one line**
```python
from aaip.quick import aaip_crewai
crew   = aaip_crewai(your_crew)
result = crew.kickoff(inputs={"topic": "AI trends"})   # result.verified → True
```

**Any agent — context manager**
```python
from aaip import aaip_task

with aaip_task("Summarise Q3 earnings report") as t:
    t.tool("read_pdf").tool("summarise").model("gpt-4o")
    t.output(summary)

print(t.result.verified)    # True
print(t.result.signals)     # [] — no fraud detected
```

---

## Protocol Stack

| Layer | Name | What it does |
|-------|------|--------------|
| 6 | **Escrow** | Atomic payment release on verified PoE. Fraud → 2× slash. |
| 5 | **Reputation** | Rolling trust score. CAV audits update it hourly. |
| 4 | **CAV** | Hidden benchmark tasks dispatched to agents. Can't be gamed. |
| 3 | **Validators** | 3–9 independent nodes. ≥ 2/3 consensus required. |
| 2 | **Proof of Execution** | Signed canonical trace. 7 fraud signals checked. |
| 1 | **Identity** | ed25519 keypair. `agent_id = sha256(pubkey)[:16]`. |

---

## Fraud Detection

Seven signals checked by every validator on every submission:

| Signal | What triggered it |
|--------|------------------|
| `MISSING_FIELDS` | Required PoE fields absent |
| `NO_TASK` | Empty task string |
| `NO_TOOLS_AND_NO_MODEL` | Nothing recorded — agent did nothing |
| `FUTURE_TIMESTAMP` | Trace timestamp is ahead of now |
| `NEGATIVE_STEP_COUNT` | Impossible execution state |
| `HASH_MISMATCH` | Recomputed hash ≠ submitted hash |
| `SIGNATURE_INVALID` | ed25519 signature verification failed |

```bash
aaip demo --fraud    # watch all signals fire on a tampered trace
```

---

## Shadow Mode

Run AAIP verification without blocking your agent's workflow. Useful for auditing behavior in production before enforcing full validator consensus.

```python
from aaip import aaip_agent

@aaip_agent(shadow=True)
def agent(task: str) -> str:
    return run_agent(task)

result = agent("Analyse document")
print(result.output)     # original agent output — always returned
print(result.verified)   # True / False — for auditing only, never blocks
print(result.consensus)  # "APPROVED" or "REJECTED"
print(result.signals)    # [] or ["HASH_MISMATCH", ...] — fraud signals detected
```

In shadow mode:
- The agent's original output is **always** returned regardless of verification result
- Verification runs in the background and never raises or blocks
- Results are logged to `result` for auditing and alerting
- Switch to enforcing mode by removing `shadow=True` when you're confident

Also available on `aaip_task`:

```python
from aaip import aaip_task

with aaip_task("Summarise report", shadow=True) as t:
    t.tool("read_pdf").model("gpt-4o")
    t.output(summary)

print(t.result.verified)   # audit without blocking
```

---

## CLI

Everything works offline. No API key, no account, no config.

```bash
aaip demo                               # full end-to-end protocol walkthrough
aaip demo --fraud                       # fraudulent trace → REJECTED
aaip run --task "Summarise this doc"    # generate a signed PoE
aaip verify --task "..." --output "..."  # verify any PoE locally
aaip simulate --agents 1000             # simulate 1000 agents
aaip simulate --malicious-ratio 0.3 --scenario collusion
aaip explorer --pretty                  # inspect a PoE trace
aaip leaderboard                        # agent reputation rankings
```

---

## Simulation Lab

Research-grade adversarial testing — 7 attack scenarios, stdlib only.

| Scenario | Attack vector | Protocol holds? |
|----------|---------------|----------------|
| `sybil` | Fake validator injection | ✅ <5% success (stake-weighted) |
| `collusion` | Coordinated validator ring | ✅ Capped at 24% |
| `adversarial` | LLM judge manipulation | ✅ Ensemble correction limits to 14% |
| `bribery` | Rational validator bribery | ✅ 0% (high-stake validators resist) |
| `spam` | Resource exhaustion | ✅ <1% impact |
| `mixed` | Multi-vector coordinated | ✅ Contained at 8% |

```bash
python simulation_lab/aaip_sim.py run --scenario collusion --validators 60 --tasks 5000
python simulation_lab/aaip_sim.py benchmark    # run all scenarios
```

---

## Examples

```bash
python examples/openclaw/agent.py       # custom agent, zero dependencies
python examples/langchain/agent.py      # LangChain + AAIP
python examples/crewai/crew.py          # CrewAI + AAIP
python examples/fraud_detection.py      # 4 fraud scenarios, all caught
```

---

## Backend (Optional)

The FastAPI backend — registry, evaluation, CAV — is optional.
All CLI and local verification commands work without it.

```bash
# Docker (recommended)
cd docker && cp .env.example .env && docker compose up -d
# → API at localhost:8000   Docs at localhost:8000/docs

# Manual
cd backend && pip install -e . && cp .env.example .env
alembic upgrade head && uvicorn main:app --reload
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `OPENROUTER_API_KEY` | Yes | Multi-model jury evaluation |
| `OPENAI_API_KEY` | Yes | Embeddings |
| `AAIP_DEV_MODE` | No | `true` to skip auth locally |
| `AAIP_ALLOWED_ORIGINS` | No | Comma-separated list of allowed CORS origins (default: localhost:3000,8000). Set to "*" to allow any origin (insecure). |

---

## Roadmap

| | Phase | Scope |
|-|-------|-------|
| ✅ | **v1 — Local** | Identity · PoE · validators · fraud detection · SDK · CLI |
| 🔜 | **v2 — Network** | On-chain validators · staking · slashing · escrow payments |
| ⬡ | **v3 — Scale** | ZK-PoE · TEE integration · cross-chain identity |

---

## Documentation

| Doc | Description |
|-----|-------------|
| [QUICKSTART.md](QUICKSTART.md) | 10-minute integration guide |
| [docs/aaip-spec.md](docs/aaip-spec.md) | Full protocol specification |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture + diagrams |
| [docs/security.md](docs/security.md) | Threat model + attack analysis |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

---

## License

MIT © [Vuneum](https://x.com/vuneum) — see [LICENSE](LICENSE)

---

<div align="center">
<br/>

*The trust layer comes first.*

<br/>
</div>
