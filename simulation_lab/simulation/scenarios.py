"""
AAIP Simulation Lab — Scenario Definitions
Each scenario captures a realistic or adversarial protocol operating condition.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .core import SimConfig


@dataclass
class Scenario:
    name:        str
    description: str
    mode:        str          # simulate | stress
    config:      SimConfig
    tags:        list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Definitions
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, Scenario] = {}

def _register(s: Scenario) -> Scenario:
    SCENARIOS[s.name] = s
    return s


# 1. Normal operation — baseline honest ecosystem
_register(Scenario(
    name        = "normal_operation",
    description = "Healthy ecosystem: 100 agents, 10% malicious, moderate throughput.",
    mode        = "simulate",
    tags        = ["baseline", "simulate"],
    config      = SimConfig(
        num_agents             = 100,
        num_validators         = 10,
        num_watchers           = 5,
        malicious_agent_ratio  = 0.10,
        tasks_per_day          = 500,
        sim_days               = 14,
        seed                   = 42,
    ),
))

# 2. Large ecosystem — scale test for protocol efficiency
_register(Scenario(
    name        = "large_ecosystem",
    description = "500 agents, 15% malicious, high activity — tests registry and reputation at scale.",
    mode        = "simulate",
    tags        = ["scale", "simulate"],
    config      = SimConfig(
        num_agents             = 500,
        num_validators         = 20,
        num_watchers           = 10,
        malicious_agent_ratio  = 0.15,
        tasks_per_day          = 2000,
        sim_days               = 7,
        seed                   = 99,
    ),
))

# 3. Validator collusion attack — minority of corrupt validators covering fraud
_register(Scenario(
    name        = "validator_collusion_attack",
    description = "30% of validators collude with malicious agents. Tests watcher detection and slashing.",
    mode        = "simulate",
    tags        = ["security", "collusion", "simulate"],
    config      = SimConfig(
        num_agents                = 100,
        num_validators            = 15,
        num_watchers              = 8,
        malicious_agent_ratio     = 0.25,
        malicious_validator_ratio = 0.30,
        tasks_per_day             = 400,
        sim_days                  = 10,
        seed                      = 7,
    ),
))

# 4. Reputation farming — agents optimise evals, get caught by CAV
_register(Scenario(
    name        = "reputation_farming",
    description = "High fraction of GAMING agents boosting eval scores. CAV deviation detection stress test.",
    mode        = "simulate",
    tags        = ["security", "gaming", "simulate"],
    config      = SimConfig(
        num_agents             = 150,
        num_validators         = 10,
        num_watchers           = 5,
        malicious_agent_ratio  = 0.35,  # mostly GAMING type
        tasks_per_day          = 600,
        sim_days               = 21,
        cav_deviation_threshold= 8.0,   # tighter CAV threshold
        cav_adjustment_weight  = 0.4,
        seed                   = 13,
    ),
))

# 5. Dispute spam attack — adversaries flood dispute system
_register(Scenario(
    name        = "dispute_spam_attack",
    description = "Elevated dispute rate simulates requesters mass-disputing clean tasks.",
    mode        = "stress",
    tags        = ["security", "spam", "stress"],
    config      = SimConfig(
        num_agents              = 80,
        num_validators          = 10,
        num_watchers            = 4,
        malicious_agent_ratio   = 0.20,
        tasks_per_day           = 800,
        dispute_probability_base= 0.25,   # 25% of tasks disputed (vs normal 1%)
        sim_days                = 7,
        stress_multiplier       = 2.0,
        seed                    = 31,
    ),
))

# 6. Malicious executor network — concentrated fabricator cluster
_register(Scenario(
    name        = "malicious_executor_network",
    description = "50% fabricator agents submitting fake PoE traces. Tests fraud detection recall.",
    mode        = "simulate",
    tags        = ["security", "fraud", "simulate"],
    config      = SimConfig(
        num_agents             = 100,
        num_validators         = 12,
        num_watchers           = 6,
        malicious_agent_ratio  = 0.50,  # extreme — half are fabricators
        tasks_per_day          = 300,
        sim_days               = 10,
        poe_fraud_check_enabled= True,
        seed                   = 55,
    ),
))

# 7. High throughput stress — volume load test
_register(Scenario(
    name        = "high_throughput_stress",
    description = "10× task volume stress test. Measures latency, queue depth, validator saturation.",
    mode        = "stress",
    tags        = ["stress", "throughput"],
    config      = SimConfig(
        num_agents             = 200,
        num_validators         = 15,
        num_watchers           = 5,
        malicious_agent_ratio  = 0.10,
        tasks_per_day          = 500,
        sim_days               = 3,
        stress_multiplier      = 10.0,
        seed                   = 77,
    ),
))

# 8. Validator node failures — Byzantine fault tolerance
_register(Scenario(
    name        = "validator_node_failures",
    description = "40% of validators go offline randomly. Tests consensus under node failure.",
    mode        = "stress",
    tags        = ["stress", "fault-tolerance"],
    config      = SimConfig(
        num_agents              = 100,
        num_validators          = 20,
        num_watchers            = 5,
        malicious_agent_ratio   = 0.10,
        validator_failure_rate  = 0.40,
        tasks_per_day           = 500,
        sim_days                = 7,
        seed                    = 88,
    ),
))

# 9. PoE trace overload — extreme trace submission volume
_register(Scenario(
    name        = "poe_trace_overload",
    description = "Very high PoE submission rate with mix of valid and fabricated traces.",
    mode        = "stress",
    tags        = ["stress", "poe"],
    config      = SimConfig(
        num_agents             = 300,
        num_validators         = 15,
        num_watchers           = 8,
        malicious_agent_ratio  = 0.30,
        tasks_per_day          = 1000,
        sim_days               = 3,
        stress_multiplier      = 5.0,
        seed                   = 66,
    ),
))

# 10. CAV audit burst — manual CAV trigger stress test
_register(Scenario(
    name        = "cav_audit_burst",
    description = "Accelerated CAV cycles — every tick instead of hourly. Tests audit system capacity.",
    mode        = "stress",
    tags        = ["stress", "cav"],
    config      = SimConfig(
        num_agents             = 150,
        num_validators         = 10,
        num_watchers           = 5,
        malicious_agent_ratio  = 0.20,
        tasks_per_day          = 400,
        cav_agents_per_run     = 10,   # audit 10 agents per cycle instead of 3
        sim_days               = 5,
        seed                   = 44,
    ),
))

# 11. Economic stress — very low task values, high volume
_register(Scenario(
    name        = "economic_stress",
    description = "Micro-transaction volume stress — tests fee model and ledger stability.",
    mode        = "stress",
    tags        = ["stress", "economics"],
    config      = SimConfig(
        num_agents             = 200,
        num_validators         = 10,
        num_watchers           = 4,
        malicious_agent_ratio  = 0.10,
        tasks_per_day          = 5000,
        task_value_mean        = 0.00005,
        task_value_std         = 0.00002,
        task_value_min         = 0.00001,
        task_value_max         = 0.0005,
        sim_days               = 3,
        stress_multiplier      = 1.0,
        seed                   = 22,
    ),
))

# 12. Degrading agent cascade — many agents with time-decaying quality
_register(Scenario(
    name        = "degrading_agent_cascade",
    description = "Large fraction of DEGRADING agents — tests whether reputation system reacts in time.",
    mode        = "simulate",
    tags        = ["security", "drift", "simulate"],
    config      = SimConfig(
        num_agents             = 120,
        num_validators         = 10,
        num_watchers           = 5,
        malicious_agent_ratio  = 0.40,  # all malicious will be DEGRADING type
        tasks_per_day          = 400,
        sim_days               = 30,
        cav_deviation_threshold= 10.0,
        seed                   = 101,
    ),
))


def list_scenarios() -> list[dict]:
    return [
        {
            "name":        s.name,
            "mode":        s.mode,
            "description": s.description,
            "tags":        s.tags,
        }
        for s in SCENARIOS.values()
    ]


def get_scenario(name: str) -> Optional[Scenario]:
    return SCENARIOS.get(name)
