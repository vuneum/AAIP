"""
AAIP Simulation Lab — Tasks
Task generation, lifecycle management, and Poisson arrival modeling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .core import SimState


class TaskStatus(str, Enum):
    PENDING         = "pending"
    EXECUTING       = "executing"
    POE_SUBMITTED   = "poe_submitted"
    VALIDATING      = "validating"
    JURY_SCORING    = "jury_scoring"
    COMPLETED       = "completed"
    DISPUTED        = "disputed"
    FAILED          = "failed"
    FRAUD_DETECTED  = "fraud_detected"


@dataclass
class SimTask:
    task_id:        str
    domain:         str
    description:    str
    requester_id:   str         # agent or external requester
    executor_id:    str         # agent assigned to execute
    value:          float       # USDC value
    created_tick:   int
    status:         TaskStatus  = TaskStatus.PENDING

    # Timing
    execution_start_tick:   Optional[int]   = None
    execution_end_tick:     Optional[int]   = None
    validation_end_tick:    Optional[int]   = None
    settlement_tick:        Optional[int]   = None

    # Scores
    jury_score:             Optional[float] = None
    poe_verdict:            Optional[str]   = None  # verified|suspicious|invalid|unverified
    fraud_flags:            list[str]       = field(default_factory=list)
    validator_votes:        dict[str, bool] = field(default_factory=dict)  # vid → fraud_detected
    consensus_fraud:        Optional[bool]  = None
    reputation_delta:       Optional[float] = None

    # Economics
    escrow_fee:             float           = 0.0
    settled:                bool            = False
    disputed:               bool            = False
    dispute_resolution:     Optional[str]   = None  # upheld | dismissed

    @property
    def latency_ticks(self) -> Optional[int]:
        if self.validation_end_tick and self.created_tick:
            return self.validation_end_tick - self.created_tick
        return None

    @property
    def was_fraud(self) -> bool:
        return self.consensus_fraud is True

    @property
    def was_detected(self) -> bool:
        return self.was_fraud and self.poe_verdict in ("suspicious", "invalid")


class TaskGenerator:
    """
    Generates tasks via Poisson process.
    Task arrival follows a daily pattern with a peak during business hours.
    """

    DOMAIN_WEIGHTS = {
        "coding":       0.25,
        "finance":      0.20,
        "general":      0.20,
        "translation":  0.10,
        "summarization":0.10,
        "data_analysis":0.10,
        "research":     0.05,
    }

    TASK_TEMPLATES = {
        "coding":       ["Implement feature X", "Debug function Y", "Write tests for Z"],
        "finance":      ["Analyse earnings report", "Model portfolio risk", "Forecast Q{n} revenue"],
        "general":      ["Summarise document", "Answer query about topic", "Draft response"],
        "translation":  ["Translate document to {lang}", "Localise content for {region}"],
        "summarization":["Summarise research paper", "Executive summary of report"],
        "data_analysis":["Analyse dataset for trends", "Run statistical analysis"],
        "research":     ["Research topic and produce report", "Literature review on subject"],
    }

    def __init__(self, state: SimState):
        self.state = state

    def generate_tick_tasks(self) -> list[SimTask]:
        """Generate tasks arriving this tick using Poisson sampling."""
        state = self.state
        cfg   = state.config
        lam   = cfg.tasks_per_tick()

        # Time-of-day modulation (more tasks during simulated business hours)
        hour = state.clock.hour_of_day
        if 9 <= hour <= 17:
            lam *= 1.4
        elif 0 <= hour <= 6:
            lam *= 0.4

        n_tasks = state.rng.poisson_approx(lam)
        tasks: list[SimTask] = []

        agent_ids = [
            aid for aid, a in state.agents.items() if a.is_active
        ]
        if not agent_ids:
            return []

        for _ in range(n_tasks):
            domain   = state.rng.choices(
                list(self.DOMAIN_WEIGHTS.keys()),
                weights=list(self.DOMAIN_WEIGHTS.values()),
            )[0]
            template = state.rng.choice(self.TASK_TEMPLATES[domain])
            executor = state.rng.choice(agent_ids)
            requester = state.rng.choice(agent_ids)
            while requester == executor and len(agent_ids) > 1:
                requester = state.rng.choice(agent_ids)

            value = state.gauss(
                cfg.task_value_mean,
                cfg.task_value_std,
                cfg.task_value_min,
                cfg.task_value_max,
            )
            fee = round(value * cfg.escrow_fee_rate, 6)

            task = SimTask(
                task_id=f"task_{state.uid()}",
                domain=domain,
                description=template,
                requester_id=requester,
                executor_id=executor,
                value=round(value, 6),
                escrow_fee=fee,
                created_tick=state.clock.ticks,
            )
            tasks.append(task)

        return tasks


# Patch random.Random for Poisson sampling
def _poisson_approx(rng: "random.Random", lam: float) -> int:
    """Approximate Poisson sample using Knuth algorithm (good for lam < 30)."""
    if lam <= 0:
        return 0
    if lam > 30:
        # Normal approximation
        return max(0, int(rng.gauss(lam, math.sqrt(lam)) + 0.5))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


import random as _random_module
_random_module.Random.poisson_approx = _poisson_approx
_random_module.Random.choices = _random_module.Random.choices  # already exists
