# AAIP Simulation Lab

A discrete-event simulation and stress testing framework for the
**Autonomous Agent Infrastructure Protocol (AAIP)**.

Use it to analyse protocol behaviour, test security assumptions,
evaluate economic stability, and stress-test the validation layer —
all without touching the live backend or a real blockchain.

---

## Architecture

```
aaip-lab/
├── simulation/
│   ├── core.py            SimConfig, SimState, SimClock, EventBus
│   ├── agents.py          Agent population: HONEST, LAZY, GAMING, FABRICATOR, DEGRADING, COLLUDING, SYBIL
│   ├── validators.py      Validator set: HONEST, COLLUDING, LAZY, FAULTY
│   ├── watchers.py        Watcher monitors (fraud proof detection)
│   ├── tasks.py           Poisson task arrival, lifecycle (PENDING → COMPLETED / FRAUD_DETECTED)
│   ├── poe_simulation.py  PoE trace generation + 7-signal fraud detection (mirrors backend/poe.py)
│   ├── validation.py      AI jury scoring + multi-validator consensus
│   ├── cav_simulation.py  CAV hourly audit cycle (mirrors backend/cav.py)
│   ├── reputation.py      Rolling reputation updates, Gini coefficient, grade distribution
│   ├── economics.py       Escrow settlement, fee collection, fraud penalties, validator rewards
│   ├── scenarios.py       12 predefined scenarios (simulate + stress)
│   ├── metrics.py         Tick-level snapshots, final report, JSON/CSV/summary export
│   └── engine.py          Main tick loop — wires all modules together
├── aaip_lab.py            CLI entry point
└── tests/
    └── test_simulation.py 23 unit + integration tests
```

### Protocol Mapping

| AAIP Component        | Simulation Module          | Key Logic Mirrored |
|-----------------------|----------------------------|--------------------|
| PoE (backend/poe.py)  | poe_simulation.py          | 7 fraud signals, SHA-256 hash verification |
| CAV (backend/cav.py)  | cav_simulation.py          | hourly cycle, deviation threshold (10 pts), blend weight (0.3) |
| Jury (consensus.py)   | validation.py              | multi-judge scoring, t-distribution CI, agreement levels |
| Reputation            | reputation.py              | rolling avg (last 10), CAV injection, Gini coefficient |
| Payments              | economics.py               | escrow charge/credit, protocol fee (0.5%), validator rewards, fraud penalty (2×) |
| Validators / Watchers | validators.py / watchers.py| VRF-style selection, collusion pool, fraud proof submission |

---

## Quick Start

```bash
# Single simulation run (default config)
python aaip_lab.py simulate

# Custom parameters
python aaip_lab.py simulate --agents 200 --validators 15 --malicious-ratio 0.20 \
                            --tasks 800 --days 14 --csv

# Stress test (5× default task volume, validator failures)
python aaip_lab.py stress --agents 300 --stress-mult 10 --days 3

# Run a predefined scenario
python aaip_lab.py scenario normal_operation
python aaip_lab.py scenario validator_collusion_attack --days 14
python aaip_lab.py scenario high_throughput_stress --csv

# List all scenarios
python aaip_lab.py scenarios
```

---

## CLI Reference

```
aaip-lab simulate   [options]   Run a custom simulation
aaip-lab stress     [options]   Run a stress test (high load defaults)
aaip-lab scenario   <name> [options]   Run a named scenario
aaip-lab scenarios              List all predefined scenarios

Network:
  --agents N              Number of agents              (default: 100)
  --validators N          Number of validators          (default: 10)
  --watchers N            Number of watchers            (default: 5)
  --malicious-ratio 0.10  Fraction of malicious agents  (default: 0.10)
  --mal-validator-ratio   Fraction of malicious validators (default: 0.0)

Workload:
  --tasks N               Tasks per day                 (default: 500)
  --days N                Simulated days                (default: 30 / scenario)
  --stress-mult 5.0       Task volume multiplier        (default: 1.0)
  --tick-minutes 5        Simulated minutes per tick    (default: 5)

Protocol:
  --cav-threshold 10.0    CAV deviation threshold
  --cav-weight 0.3        CAV reputation blend weight
  --dispute-prob 0.01     Base probability of dispute per task
  --val-failure-rate 0.0  Validator failure probability per tick

Output:
  --out ./lab_output      Output directory
  --json                  Write full JSON report  (always written)
  --csv                   Write tick-level CSV time series
  --seed 42               Random seed
  --verbose               Debug-level logging
```

---

## Scenarios

| Scenario                    | Mode     | Description |
|-----------------------------|----------|-------------|
| `normal_operation`          | simulate | Baseline: 10% malicious, healthy ecosystem |
| `large_ecosystem`           | simulate | 500 agents, 15% malicious, 2000 tasks/day |
| `validator_collusion_attack`| simulate | 30% validators collude, watcher detection tested |
| `reputation_farming`        | simulate | High GAMING agent fraction, tight CAV threshold |
| `dispute_spam_attack`       | stress   | 25% dispute rate — dispute system saturation |
| `malicious_executor_network`| simulate | 50% fabricators — PoE fraud detection recall test |
| `high_throughput_stress`    | stress   | 10× task volume — latency and throughput ceiling |
| `validator_node_failures`   | stress   | 40% validators offline — Byzantine fault tolerance |
| `poe_trace_overload`        | stress   | 5× volume with 30% malicious — PoE pipeline stress |
| `cav_audit_burst`           | stress   | 10 agents per CAV cycle — audit system capacity |
| `economic_stress`           | stress   | Micro-transaction volume — ledger stability |
| `degrading_agent_cascade`   | simulate | 40% DEGRADING agents — reputation system lag test |

---

## Output

All runs write to `./lab_output/<scenario_name>/`.

**report.json** — full structured report:
```json
{
  "scenario_name": "normal_operation",
  "total_tasks": 14250,
  "fraud_detection_rate": 0.87,
  "final_mean_reputation": 79.1,
  "final_honest_mean_rep": 82.8,
  "final_malicious_mean_rep": 45.6,
  "reputation_separation": 37.2,
  "protocol_revenue": 0.0712,
  "avg_validation_latency_ms": 152.3,
  "grade_distribution": {"Elite":4,"Gold":12,"Silver":44,"Bronze":27,"Unrated":13},
  "tick_snapshots": [...]
}
```

**timeseries.csv** (with `--csv`) — one row per snapshot tick:
```
tick,sim_time,tasks_created,tasks_completed,fraud_detected,mean_reputation,...
```

**Terminal summary** — printed at end of every run:
```
╔══════════════════════════════════════════════════════════╗
║   AAIP Simulation Lab — normal_operation                ║
╚══════════════════════════════════════════════════════════╝
  TASK OUTCOMES
  ─────────────────────────────────────────────────────────
  Total tasks       : 14,250
  Fraud detect rate : 87.0%
  ...
```

---

## Agent Behaviours

| Behaviour    | Description | PoE | Gaming |
|--------------|-------------|-----|--------|
| `HONEST`     | Genuine execution, real traces | valid | none |
| `LAZY`       | Real output, minimal PoE submission | often unverified | none |
| `DEGRADING`  | Quality decays over time | valid | none |
| `GAMING`     | Boosts eval score, CAV reveals gap | valid | +5–15 pts on jury |
| `FABRICATOR` | Submits fake PoE traces | fabricated | none |
| `COLLUDING`  | Covered by corrupt validators | valid | none |
| `SYBIL`      | Many thin identities, high variance | mixed | none |

---

## Extending the Framework

**Add a new scenario** — edit `simulation/scenarios.py`:
```python
_register(Scenario(
    name        = "my_scenario",
    description = "...",
    mode        = "simulate",
    tags        = ["custom"],
    config      = SimConfig(num_agents=200, ...),
))
```

**Add a new agent behaviour** — extend `AgentBehavior` enum in `agents.py`,
add a `QUALITY_PROFILE` entry, and override `produce_output_score()` /
`produce_cav_score()` / `will_fabricate_poe()` as needed.

**Add a new fraud signal** — extend `PoESimulator._detect_fraud()` in
`poe_simulation.py`. The signal will automatically appear in fraud flag
distributions and detection rate metrics.

**Add new metrics** — add fields to `TickSnapshot` and `SimulationReport`
in `metrics.py`, populate them in `MetricsCollector.capture_tick()` and
`build_report()`.

---

## Running Tests

```bash
python3 -m pytest tests/test_simulation.py -v          # requires pytest
python3 tests/test_simulation.py                        # self-contained runner
```

23 tests covering: core, agents, validators, PoE, jury, consensus, CAV,
reputation, economics, scenarios, integration, and export.

---

## Design Decisions

- **Discrete-event, not continuous.** Each tick is one simulated period.
  The clock is deterministic and reproducible via `--seed`. No async or
  threading — the entire simulation runs in a single loop, making it easy
  to inspect and profile.

- **Mirrors production logic exactly.** The 7 PoE fraud signals, CAV
  deviation threshold (10 pts), adjustment weight (0.3), jury consensus
  scoring, and escrow fee rate (0.5%) are taken directly from the AAIP
  codebase. Simulation parameters and production parameters are kept in sync.

- **No blockchain calls.** The ledger is an in-memory dict. All economics
  are simulated in USDC units without on-chain settlement, as specified.

- **Separation of true quality from observable reputation.** Each agent
  has a `true_quality` (hidden from the protocol) and a `reputation`
  (protocol-visible). The separation between these two is what the
  simulation measures — it's the core research variable.
