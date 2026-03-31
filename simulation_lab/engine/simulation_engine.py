"""
AAIP Simulation Engine — Central Research Orchestrator
Research-grade adversarial testing environment for the AAIP trust layer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("aaip.engine")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulationConfig:
    # Network topology
    validators:          int   = 50
    agents:              int   = 20
    malicious_ratio:     float = 0.20
    malicious_validators:float = 0.10

    # Workload
    tasks:               int   = 5000
    task_value_mean:     float = 0.002   # USDC
    task_value_std:      float = 0.001
    tasks_per_tick:      int   = 10

    # Protocol parameters
    consensus_threshold: float = 0.67    # super-majority
    jury_size:           int   = 5
    cav_threshold:       float = 10.0
    reputation_weight:   float = 0.3
    escrow_fee_rate:     float = 0.005

    # Scenario
    scenario:            str   = "baseline"
    attack_params:       dict  = field(default_factory=dict)

    # Reproducibility
    seed:                int   = 42
    parallel:            bool  = False
    ticks:               int   = 500
    verbose:             bool  = False


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulationResult:
    scenario:                  str
    config:                    dict
    total_tasks:               int   = 0
    completed_tasks:           int   = 0
    fraudulent_tasks:          int   = 0
    detected_fraud:            int   = 0

    # Core metrics
    validation_accuracy:       float = 0.0
    collusion_success_rate:    float = 0.0
    consensus_disagreement:    float = 0.0
    economic_loss:             float = 0.0
    task_latency_mean:         float = 0.0
    task_latency_p95:          float = 0.0
    system_throughput:         float = 0.0   # tasks/tick
    validator_reputation_drift:float = 0.0

    # Attack-specific
    attack_success_rate:       float = 0.0
    false_approval_rate:       float = 0.0
    sybil_capture_probability: float = 0.0
    bribery_success_rate:      float = 0.0
    judge_failure_rate:        float = 0.0
    spam_overload_rate:        float = 0.0

    # Economics
    protocol_revenue:          float = 0.0
    total_value_at_risk:       float = 0.0
    slashed_stake:             float = 0.0
    validator_reward_gini:     float = 0.0

    # Time series
    tick_series:               list  = field(default_factory=list)
    reputation_series:         list  = field(default_factory=list)
    latency_series:            list  = field(default_factory=list)
    consensus_series:          list  = field(default_factory=list)
    attack_series:             list  = field(default_factory=list)

    wall_time_seconds:         float = 0.0
    completed_at:              str   = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def to_csv_summary(self) -> str:
        fields = [
            ("scenario", self.scenario),
            ("validation_accuracy", self.validation_accuracy),
            ("collusion_success_rate", self.collusion_success_rate),
            ("attack_success_rate", self.attack_success_rate),
            ("economic_loss", self.economic_loss),
            ("task_latency_mean", self.task_latency_mean),
            ("system_throughput", self.system_throughput),
        ]
        header = ",".join(k for k, _ in fields)
        row    = ",".join(str(v) for _, v in fields)
        return f"{header}\n{row}"


# ─────────────────────────────────────────────────────────────────────────────
# SimulationEngine
# ─────────────────────────────────────────────────────────────────────────────

class SimulationEngine:
    """
    Central research-grade simulation engine.

    Responsibilities:
    - Manages global state (validators, agents, ledger)
    - Runs the tick loop
    - Dispatches to scenario-specific attack modules
    - Collects and aggregates metrics
    - Produces structured JSON results
    """

    SCENARIO_REGISTRY: dict[str, type] = {}

    def __init__(self, config: SimulationConfig):
        self.config  = config
        self.rng     = random.Random(config.seed)
        self._uid    = 0

        # Shared mutable state
        self.validators:  list[dict] = []
        self.agents:      list[dict] = []
        self.task_queue:  list[dict] = []
        self.ledger:      dict       = {}
        self.counters:    dict       = {}

        # Metric accumulators
        self._latencies:   list[float] = []
        self._tick_data:   list[dict]  = []
        self._rep_data:    list[dict]  = []
        self._attack_data: list[dict]  = []

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        cfg = self.config
        rng = self.rng

        n_malicious_validators = max(1, int(cfg.validators * cfg.malicious_validators))
        n_malicious_agents     = max(1, int(cfg.agents     * cfg.malicious_ratio))

        self.validators = [
            {
                "id":          f"V{i:04d}",
                "malicious":   i < n_malicious_validators,
                "stake":       rng.uniform(1000, 5000),
                "reputation":  rng.gauss(80, 10) if i >= n_malicious_validators else rng.gauss(60, 15),
                "online":      True,
                "tasks_seen":  0,
                "fraud_caught":0,
                "rewards":     0.0,
                "slashed":     0.0,
                "behavior":    "malicious" if i < n_malicious_validators else "honest",
            }
            for i in range(cfg.validators)
        ]

        self.agents = [
            {
                "id":          f"A{i:04d}",
                "malicious":   i < n_malicious_agents,
                "reputation":  rng.gauss(75, 12) if i >= n_malicious_agents else rng.gauss(50, 20),
                "quality":     rng.gauss(80, 8)  if i >= n_malicious_agents else rng.gauss(40, 20),
                "tasks_done":  0,
                "fraud_count": 0,
                "earnings":    0.0,
            }
            for i in range(cfg.agents)
        ]

        self.ledger   = {"protocol": 0.0}
        self.counters = {k: 0 for k in [
            "tasks_created", "tasks_completed", "fraud_detected",
            "fraud_total", "disputes", "consensus_failed",
            "attack_attempts", "attack_successes",
        ]}

    # ── Tick loop ─────────────────────────────────────────────────────────────

    def run(self) -> SimulationResult:
        cfg       = self.config
        self._setup()
        scenario  = self._load_scenario()
        wall_t0   = time.perf_counter()

        logger.info("Simulation start: scenario=%s  validators=%d  agents=%d  ticks=%d",
                    cfg.scenario, cfg.validators, cfg.agents, cfg.ticks)

        for tick in range(cfg.ticks):
            # Generate tasks
            n_new = cfg.tasks_per_tick
            if hasattr(scenario, "modify_task_rate"):
                n_new = scenario.modify_task_rate(n_new, tick, self)

            tasks = self._generate_tasks(n_new, tick)

            # Scenario pre-tick hook
            if hasattr(scenario, "pre_tick"):
                scenario.pre_tick(tick, self, tasks)

            # Process each task
            tick_latencies = []
            tick_attacks   = 0
            tick_fraud     = 0
            tick_approved_fraud = 0

            for task in tasks:
                t0 = time.perf_counter()
                result = self._process_task(task, scenario)
                latency_ms = (time.perf_counter() - t0) * 1000 + self.rng.gauss(80, 20)
                latency_ms = max(5.0, latency_ms)
                tick_latencies.append(latency_ms)
                self._latencies.append(latency_ms)

                if task.get("fraudulent"):
                    tick_fraud += 1
                    self.counters["fraud_total"] += 1
                    if result.get("approved"):
                        tick_approved_fraud += 1
                    else:
                        self.counters["fraud_detected"] += 1

                if result.get("attack_attempted"):
                    tick_attacks += 1
                    self.counters["attack_attempts"] += 1
                if result.get("attack_succeeded"):
                    self.counters["attack_successes"] += 1

                self.counters["tasks_completed"] += 1

            self.counters["tasks_created"] += len(tasks)

            # Scenario post-tick hook
            if hasattr(scenario, "post_tick"):
                scenario.post_tick(tick, self)

            # Reputation drift
            self._tick_reputation()

            # Capture tick metrics
            avg_rep_honest  = self._mean_reputation(malicious=False)
            avg_rep_mal     = self._mean_reputation(malicious=True)
            avg_lat = statistics.mean(tick_latencies) if tick_latencies else 0.0

            self._tick_data.append({
                "tick":           tick,
                "tasks":          len(tasks),
                "fraud_detected": tick_fraud - tick_approved_fraud,
                "attacks":        tick_attacks,
                "avg_latency_ms": round(avg_lat, 2),
                "consensus_failures": self.counters.get("consensus_failed", 0),
            })
            self._rep_data.append({
                "tick":           tick,
                "honest_rep":     round(avg_rep_honest, 2),
                "malicious_rep":  round(avg_rep_mal, 2),
                "separation":     round(avg_rep_honest - avg_rep_mal, 2),
            })
            self._attack_data.append({
                "tick":            tick,
                "attack_attempts": self.counters["attack_attempts"],
                "attack_successes":self.counters["attack_successes"],
                "success_rate":    round(
                    self.counters["attack_successes"] / max(1, self.counters["attack_attempts"]), 3
                ),
            })

        wall_elapsed = time.perf_counter() - wall_t0
        return self._build_result(scenario, wall_elapsed)

    # ── Task processing ───────────────────────────────────────────────────────

    def _generate_tasks(self, n: int, tick: int) -> list[dict]:
        cfg = self.config
        tasks = []
        for _ in range(n):
            executor = self.rng.choice(self.agents)
            value    = max(0.0001, self.rng.gauss(cfg.task_value_mean, cfg.task_value_std))
            tasks.append({
                "id":         f"T{self._next_uid()}",
                "tick":       tick,
                "executor":   executor["id"],
                "malicious_executor": executor["malicious"],
                "value":      value,
                "fraudulent": executor["malicious"] and self.rng.random() < 0.7,
                "domain":     self.rng.choice(["coding", "analysis", "writing", "math", "research"]),
            })
        return tasks

    def _process_task(self, task: dict, scenario) -> dict:
        cfg = self.config

        # Select validator panel (VRF-style)
        panel = self.rng.sample(self.validators, min(cfg.jury_size, len(self.validators)))

        # Get votes from scenario (may inject attack logic)
        if hasattr(scenario, "get_validator_votes"):
            votes = scenario.get_validator_votes(task, panel, self)
        else:
            votes = self._default_votes(task, panel)

        approve_count = sum(1 for v in votes if v["approve"])
        approve_rate  = approve_count / len(votes)
        approved      = approve_rate >= cfg.consensus_threshold

        if approve_rate < 0.3 or approve_rate > 0.7:
            pass  # clear consensus
        else:
            self.counters["consensus_failed"] += 1

        # Economics
        fee = task["value"] * cfg.escrow_fee_rate
        self.ledger["protocol"] = self.ledger.get("protocol", 0.0) + fee

        # Reputation updates for validators in panel
        for v in panel:
            validator = next((x for x in self.validators if x["id"] == v["id"]), None)
            if validator:
                validator["tasks_seen"] += 1
                validator["rewards"] += fee / len(panel)
                if task["fraudulent"] and not v.get("approve", True):
                    validator["fraud_caught"] += 1

        result = {
            "approved":          approved,
            "approve_rate":      approve_rate,
            "attack_attempted":  task.get("fraudulent", False),
            "attack_succeeded":  task.get("fraudulent", False) and approved,
        }

        # Track economic loss from approved fraud
        if task["fraudulent"] and approved:
            self.ledger["economic_loss"] = self.ledger.get("economic_loss", 0.0) + task["value"]

        return result

    def _default_votes(self, task: dict, panel: list[dict]) -> list[dict]:
        votes = []
        for v in panel:
            if v["malicious"] and task.get("malicious_executor"):
                # Malicious validators approve fraudulent tasks
                approve = self.rng.random() < 0.85
            elif task.get("fraudulent"):
                # Honest validators detect fraud
                approve = self.rng.random() < 0.15
            else:
                # Clean task: approve
                approve = self.rng.random() < 0.90
            votes.append({"id": v["id"], "approve": approve})
        return votes

    def _tick_reputation(self) -> None:
        for agent in self.agents:
            if agent["malicious"]:
                agent["reputation"] = max(0.0, agent["reputation"] - self.rng.uniform(0, 0.3))
            else:
                agent["reputation"] = min(100.0, agent["reputation"] + self.rng.uniform(0, 0.1))

    def _mean_reputation(self, malicious: bool) -> float:
        pool = [a["reputation"] for a in self.agents if a["malicious"] == malicious]
        return statistics.mean(pool) if pool else 0.0

    # ── Result assembly ───────────────────────────────────────────────────────

    def _build_result(self, scenario, wall_elapsed: float) -> SimulationResult:
        import datetime
        cfg = self.config
        c   = self.counters

        lats = sorted(self._latencies)
        avg_lat = statistics.mean(lats) if lats else 0.0
        p95_lat = lats[int(len(lats) * 0.95)] if lats else 0.0

        total_fraud    = c["fraud_total"]
        detected_fraud = c["fraud_detected"]
        val_accuracy   = (detected_fraud / max(1, total_fraud)) if total_fraud > 0 else 1.0
        false_approval = 1.0 - val_accuracy

        attack_success = (
            c["attack_successes"] / max(1, c["attack_attempts"])
            if c["attack_attempts"] > 0 else 0.0
        )

        # Reputation drift: std-dev of validator reputation changes
        rep_vals = [v["reputation"] for v in self.validators]
        rep_drift = statistics.stdev(rep_vals) if len(rep_vals) > 1 else 0.0

        # Reward Gini
        rewards = sorted(v["rewards"] for v in self.validators)
        reward_gini = self._gini(rewards)

        # Get scenario-specific metrics
        extra = {}
        if hasattr(scenario, "get_metrics"):
            extra = scenario.get_metrics(self)

        return SimulationResult(
            scenario                  = cfg.scenario,
            config                    = asdict(cfg),
            total_tasks               = c["tasks_created"],
            completed_tasks           = c["tasks_completed"],
            fraudulent_tasks          = total_fraud,
            detected_fraud            = detected_fraud,
            validation_accuracy       = round(val_accuracy, 4),
            collusion_success_rate    = round(extra.get("collusion_success_rate", attack_success if cfg.scenario == "collusion" else 0.0), 4),
            consensus_disagreement    = round(c["consensus_failed"] / max(1, c["tasks_completed"]), 4),
            economic_loss             = round(self.ledger.get("economic_loss", 0.0), 6),
            task_latency_mean         = round(avg_lat, 2),
            task_latency_p95          = round(p95_lat, 2),
            system_throughput         = round(c["tasks_completed"] / max(1, cfg.ticks), 2),
            validator_reputation_drift= round(rep_drift, 4),
            attack_success_rate       = round(attack_success, 4),
            false_approval_rate       = round(false_approval, 4),
            sybil_capture_probability = round(extra.get("sybil_capture_probability", 0.0), 4),
            bribery_success_rate      = round(extra.get("bribery_success_rate", 0.0), 4),
            judge_failure_rate        = round(extra.get("judge_failure_rate", 0.0), 4),
            spam_overload_rate        = round(extra.get("spam_overload_rate", 0.0), 4),
            protocol_revenue          = round(self.ledger.get("protocol", 0.0), 6),
            total_value_at_risk       = round(sum(t.get("value", 0) for t in self.task_queue), 6),
            slashed_stake             = round(sum(v["slashed"] for v in self.validators), 4),
            validator_reward_gini     = round(reward_gini, 4),
            tick_series               = self._tick_data,
            reputation_series         = self._rep_data,
            latency_series            = [{"tick": i * 10, "latency_ms": round(l, 2)}
                                         for i, l in enumerate(lats[::max(1, len(lats)//50)])],
            consensus_series          = [
                {"tick": d["tick"], "consensus_rate": round(1 - d["consensus_failures"] / max(1, d["tasks"]), 3)}
                for d in self._tick_data
            ],
            attack_series             = self._attack_data,
            wall_time_seconds         = round(wall_elapsed, 3),
            completed_at              = datetime.datetime.utcnow().isoformat(),
        )

    def _load_scenario(self):
        """Dynamically load a scenario by name."""
        try:
            from simulation_lab.scenarios.all_scenarios import get_scenario
            return get_scenario(self.config.scenario, self.config)
        except Exception:
            # Fallback to minimal inline baseline
            class _Baseline:
                def get_metrics(self, engine): return {}
            return _Baseline()

    @staticmethod
    def _gini(values: list[float]) -> float:
        if not values:
            return 0.0
        total = sum(values)
        if total == 0:
            return 0.0
        n   = len(values)
        cum = sum((i + 1) * v for i, v in enumerate(sorted(values)))
        return (2 * cum) / (n * total) - (n + 1) / n

    def _next_uid(self) -> int:
        self._uid += 1
        return self._uid

    # ── Class method registry ─────────────────────────────────────────────────

    @classmethod
    def register_scenario(cls, name: str, scenario_cls: type) -> None:
        cls.SCENARIO_REGISTRY[name] = scenario_cls

    @classmethod
    def run_scenario(cls, scenario: str, **kwargs) -> SimulationResult:
        cfg = SimulationConfig(scenario=scenario, **kwargs)
        return cls(cfg).run()

    @classmethod
    def run_parallel(cls, configs: list[SimulationConfig]) -> list[SimulationResult]:
        """Run multiple configs sequentially (parallel flag reserved for future threading)."""
        results = []
        for cfg in configs:
            engine = cls(cfg)
            results.append(engine.run())
        return results
