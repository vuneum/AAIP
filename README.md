<div align="center">

# ⬡ AAIP + AEP ⬡

### Autonomous Agent Infrastructure Protocol + Agent Economy Protocol

**The trust and payment layer for the autonomous agent economy.**

[![Python 3.9+](https://img.shields.io/badge/Python_3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.4.0-FF6A00?style=flat-square)](CHANGELOG.md)
[![Zero Dependencies](https://img.shields.io/badge/Zero_Runtime_Deps-✓-22C55E?style=flat-square)](#quickstart)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-6366F1?style=flat-square)](CONTRIBUTING.md)
[![Base Sepolia](https://img.shields.io/badge/Base_Sepolia-Live-0052FF?style=flat-square)](https://sepolia.basescan.org/address/0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94)

> AI agents are executing real tasks, handling money, and making decisions autonomously.
> There is no standard way to prove an agent did the work it claims or pay it trustlessly.
>
> **AAIP + AEP solves both.**

</div>

---

## 🔗 Live On-Chain (Base Sepolia)

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

## What AAIP + AEP Does

Every agent gets a cryptographic identity. Every execution produces a signed,
tamper-evident Proof of Execution. A validator panel independently verifies
the trace before any payment is released. Payment settles on-chain with a
2% protocol fee. The PoE is anchored permanently on Base Sepolia.
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
APPROVED → AEP settles payment on Base Sepolia (2% protocol fee)
      │
      ▼
PoEAnchor.sol records poe_hash → tx_hash permanently on-chain
```

No central authority. No trusted intermediary. Cryptographic proof all the way down.

---

## Quickstart
```bash
pip install aaip web3 python-dotenv
cp .env.example .env        # fill in your keys
python demo_two_agent.py --mock --fast   # no ETH needed
python demo_two_agent.py --fast          # real on-chain
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

See **[QUICKSTART.md](QUICKSTART.md)** for the full 10-minute guide.

---

## Protocol Stack

| Layer | Name | What it does |
|---|---|---|
| 7 | **On-Chain Anchor** | PoEAnchor.sol on Base Sepolia. Immutable poe_hash → tx_hash registry. |
| 6 | **Escrow + Fee** | Atomic payment release on verified PoE. 2% protocol fee. Fraud → 2× slash. |
| 5 | **Reputation** | Rolling trust score. CAV audits update it hourly. |
| 4 | **CAV** | Hidden benchmark tasks dispatched to agents. Can't be gamed. |
| 3 | **Validators** | 3–9 independent nodes. ≥ 2/3 consensus required. |
| 2 | **Proof of Execution** | Signed canonical trace. 7 fraud signals checked. |
| 1 | **Identity** | ed25519 keypair. `agent_id = sha256(pubkey)[:16]`. |

---

## Two-Agent Demo
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
```bash
python demo_two_agent.py --mock --fast
# ✅ APPROVED (3/3) → SUCCESS → ON-CHAIN anchored
```

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

## Fraud Detection

Seven signals checked by every validator on every submission:

| Signal | What triggered it |
|---|---|
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
```python
from aaip import aaip_agent

@aaip_agent(shadow=True)
def agent(task: str) -> str:
    return run_agent(task)

result = agent("Analyse document")
print(result.output)     # original agent output — always returned
print(result.verified)   # True / False — for auditing only, never blocks
print(result.consensus)  # "APPROVED" or "REJECTED"
print(result.signals)    # [] or ["HASH_MISMATCH", ...]
```

---

## CLI
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
|---|---|---|
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
python demo_two_agent.py --mock --fast  # two-agent payment demo
```

---

## Backend (Optional)
```bash
# Docker (recommended)
cd docker && cp .env.example .env && docker compose up -d
# → API at localhost:8000   Docs at localhost:8000/docs

# Manual
cd backend && pip install -e . && cp .env.example .env
alembic upgrade head && uvicorn main:app --reload
```

---

## Roadmap

| | Phase | Scope |
|---|---|---|
| ✅ | **v1 — Local** | Identity · PoE · validators · fraud detection · SDK · CLI |
| ✅ | **v1.4 — Payments** | AEP integration · EVM adapter · Base Sepolia · on-chain anchor · 2% fee |
| 🔜 | **v2 — Network** | On-chain validators · staking · slashing · decentralized escrow |
| ⬡ | **v3 — Scale** | ZK-PoE · TEE integration · cross-chain identity |

---

## Documentation

| Doc | Description |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 10-minute integration guide |
| [DEMO.md](DEMO.md) | Live demo output with real BaseScan TX |
| [docs/aaip-spec.md](docs/aaip-spec.md) | Full protocol specification |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture + diagrams |
| [docs/PAYMENTS.md](docs/PAYMENTS.md) | AEP payment layer documentation |
| [docs/security.md](docs/security.md) | Threat model + attack analysis |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

---

## License

MIT © [Vuneum](https://x.com/vuneum) — see [LICENSE](LICENSE)

---

*The trust layer comes first. The payment layer makes it real.*