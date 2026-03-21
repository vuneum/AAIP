"""
AAIP Simulation Lab — Reputation System
Rolling reputation updates, drift tracking, grade distribution.
Mirrors backend/reputation.py rolling-average logic.
"""
from __future__ import annotations
from dataclasses import dataclass
from .core import SimState
from .agents import SimAgent
from .tasks import SimTask
from .validation import JuryResult, ConsensusResult


@dataclass
class ReputationUpdate:
    agent_id:       str
    old_reputation: float
    new_reputation: float
    delta:          float
    jury_score:     float
    tick:           int
    source:         str   # jury|cav|dispute


class ReputationEngine:
    """
    Applies jury results to agent reputation.
    Uses a rolling window (last N evals) exactly as the production system does.
    """

    def apply_jury_result(
        self,
        agent:   SimAgent,
        task:    SimTask,
        jury:    JuryResult,
        consensus: ConsensusResult,
        state:   SimState,
    ) -> ReputationUpdate:
        old_rep = agent.reputation

        # If fraud was consensus-detected, penalise harder
        if consensus.fraud_detected:
            score = max(0.0, jury.final_score - 20.0)
            agent.fraud_count += 1
            if consensus.fraud_flags:
                agent.detected_count += 1
        else:
            score = jury.final_score

        agent.update_reputation(score, weight=1.0)
        agent.eval_history.append(score)
        agent.task_count += 1

        return ReputationUpdate(
            agent_id       = agent.agent_id,
            old_reputation = old_rep,
            new_reputation = agent.reputation,
            delta          = round(agent.reputation - old_rep, 3),
            jury_score     = jury.final_score,
            tick           = state.clock.ticks,
            source         = "jury",
        )

    def reputation_distribution(self, state: SimState) -> dict:
        """Bucket agents by grade for metrics."""
        buckets = {"Elite": 0, "Gold": 0, "Silver": 0, "Bronze": 0, "Unrated": 0}
        for agent in state.agents.values():
            buckets[agent.grade] += 1
        return buckets

    def gini_coefficient(self, state: SimState) -> float:
        """Measure reputation inequality (0=equal, 1=maximal inequality)."""
        scores = sorted(a.reputation for a in state.agents.values())
        n = len(scores)
        if n == 0:
            return 0.0
        total = sum(scores)
        if total == 0:
            return 0.0
        cum = sum((i + 1) * s for i, s in enumerate(scores))
        return round((2 * cum) / (n * total) - (n + 1) / n, 4)

    def mean_reputation(self, state: SimState) -> float:
        scores = [a.reputation for a in state.agents.values()]
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def honest_vs_malicious_reputation(self, state: SimState) -> dict:
        honest  = [a.reputation for a in state.agents.values() if not a.is_malicious]
        mal     = [a.reputation for a in state.agents.values() if a.is_malicious]
        return {
            "honest_mean":    round(sum(honest) / len(honest), 2) if honest else 0.0,
            "malicious_mean": round(sum(mal)    / len(mal),    2) if mal    else 0.0,
            "separation":     round(
                (sum(honest) / len(honest) if honest else 0.0) -
                (sum(mal)    / len(mal)    if mal    else 0.0), 2
            ),
        }
