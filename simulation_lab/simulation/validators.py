"""
AAIP Simulation Lab — Validators and Watchers

Validators: run deterministic PoE checks + sign results.
Watchers:   monitor validator behaviour, submit fraud proofs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from aaip.schemas.validator_types import ValidatorBehavior, is_malicious_validator
from .core import SimState


@dataclass
class SimValidator:
    validator_id:   str
    behavior:       ValidatorBehavior
    stake:          float           = 1000.0    # USDC staked
    is_online:      bool            = True
    tasks_validated: int            = 0
    fraud_proofs_accepted: int      = 0
    false_negatives: int            = 0         # fraud they missed
    false_positives: int            = 0         # honest tasks they rejected
    rewards_earned:  float          = 0.0
    slashed_amount:  float          = 0.0
    collusion_pool:  list[str]      = field(default_factory=list)  # agent_ids they cover
    failure_prob:    float          = 0.0
    latency_ms:      float          = 50.0      # base validation latency

    @property
    def is_malicious(self) -> bool:
        return is_malicious_validator(self.behavior)

    @property
    def effective_stake(self) -> float:
        return max(0.0, self.stake - self.slashed_amount)

    def is_available(self, state: SimState) -> bool:
        if self.behavior == ValidatorBehavior.FAULTY:
            return not state.bernoulli(self.failure_prob)
        if state.bernoulli(state.config.validator_failure_rate):
            return False
        return self.is_online

    def validate_poe(
        self,
        task,           # SimTask
        poe,            # SimPoETrace
        state: SimState,
    ) -> tuple[bool, list[str], float]:
        """
        Returns (fraud_detected, flags, latency_ms).
        Honest validators run real checks; colluders cover their pool.
        """
        latency = state.gauss(self.latency_ms, 10.0, 5.0, 500.0)

        if self.behavior == ValidatorBehavior.LAZY:
            # Rubber stamp — never detects fraud
            return False, [], latency

        if self.behavior == ValidatorBehavior.COLLUDING:
            if task.executor_id in self.collusion_pool:
                # Cover the malicious agent
                return False, [], latency

        # Honest + non-pool colluder path: run fraud checks
        flags = poe.fraud_flags if poe else []
        detected = len(flags) > 0
        return detected, flags, latency

    def tick(self, state: SimState) -> None:
        if self.behavior == ValidatorBehavior.FAULTY:
            self.is_online = not state.bernoulli(self.failure_prob)


def build_validator_set(state: SimState) -> dict[str, SimValidator]:
    cfg = state.config
    rng = state.rng
    validators: dict[str, SimValidator] = {}

    n_mal = int(cfg.num_validators * cfg.malicious_validator_ratio)
    n_honest = cfg.num_validators - n_mal

    for i in range(n_honest):
        vid = f"val_{state.uid()}"
        validators[vid] = SimValidator(
            validator_id=vid,
            behavior=ValidatorBehavior.HONEST,
            stake=rng.uniform(500.0, 5000.0),
            latency_ms=rng.uniform(20.0, 80.0),
        )

    mal_agent_ids = [
        aid for aid, a in state.agents.items() if a.is_malicious
    ]

    for i in range(n_mal):
        vid = f"val_{state.uid()}"
        # Colluding validators cover a subset of malicious agents
        pool = rng.sample(mal_agent_ids, min(5, len(mal_agent_ids)))
        validators[vid] = SimValidator(
            validator_id=vid,
            behavior=ValidatorBehavior.COLLUDING,
            stake=rng.uniform(500.0, 2000.0),
            collusion_pool=pool,
            latency_ms=rng.uniform(10.0, 30.0),  # faster — rubber stamp path
        )

    # Add some faulty validators
    n_faulty = max(1, int(n_honest * 0.1))
    faulty_ids = rng.sample(list(validators.keys()), n_faulty)
    for vid in faulty_ids:
        validators[vid].behavior = ValidatorBehavior.FAULTY
        validators[vid].failure_prob = rng.uniform(0.05, 0.3)

    return validators


# ─────────────────────────────────────────────────────────────────────────────
# Watchers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimWatcher:
    watcher_id:     str
    monitoring_set: list[str]   = field(default_factory=list)  # validator_ids watched
    fraud_proofs_submitted: int = 0
    fraud_proofs_accepted:  int = 0
    rewards_earned:         float = 0.0
    detection_latency_ticks: float = 2.0   # ticks before watcher notices
    detection_accuracy:      float = 0.85  # probability of catching genuine collusion

    def observe(self, validator_id: str, task, poe, state: SimState) -> Optional[dict]:
        """
        Observe a validator's decision. Return a fraud proof dict if collusion detected.
        Only fires if the validator is in the monitoring set.
        """
        if validator_id not in self.monitoring_set:
            return None
        validator = state.validators.get(validator_id)
        if not validator:
            return None
        # Watcher detects collusion with some accuracy
        if validator.behavior == ValidatorBehavior.COLLUDING and poe and poe.fraud_flags:
            if state.bernoulli(self.detection_accuracy):
                return {
                    "watcher_id":    self.watcher_id,
                    "validator_id":  validator_id,
                    "task_id":       task.task_id,
                    "evidence":      poe.fraud_flags,
                    "tick":          state.clock.ticks,
                }
        return None


def build_watcher_set(state: SimState) -> dict[str, SimWatcher]:
    cfg = state.config
    rng = state.rng
    watchers: dict[str, SimWatcher] = {}
    validator_ids = list(state.validators.keys())

    for i in range(cfg.num_watchers):
        wid = f"watcher_{state.uid()}"
        # Each watcher monitors a random subset of validators
        n_watch = max(1, int(len(validator_ids) * 0.6))
        monitoring = rng.sample(validator_ids, n_watch)
        watchers[wid] = SimWatcher(
            watcher_id=wid,
            monitoring_set=monitoring,
            detection_accuracy=rng.uniform(0.7, 0.95),
            detection_latency_ticks=rng.randint(1, 4),
        )

    return watchers
