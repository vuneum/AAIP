"""
AAIP Simulation Lab — Validation
AI jury scoring, multi-validator consensus, and result aggregation.
Mirrors the consensus engine in backend/consensus.py.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from .core import SimState
from .agents import SimAgent, AgentBehavior
from .tasks import SimTask
from .poe_simulation import SimPoETrace
from .validators import SimValidator, ValidatorBehavior


# ─────────────────────────────────────────────────────────────────────────────
# Jury Evaluation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class JuryResult:
    judge_scores:       dict[str, float]
    final_score:        float
    score_variance:     float
    agreement_level:    str     # high|moderate|low|insufficient_data
    confidence_low:     float
    confidence_high:    float
    grade:              str


def simulate_jury(
    task: SimTask,
    agent: SimAgent,
    poe: Optional[SimPoETrace],
    state: SimState,
) -> JuryResult:
    """
    Simulate a multi-model jury evaluation.
    Honest agents score near true quality; gaming/fabricator agents get poe penalty.
    """
    cfg = state.config
    rng = state.rng

    # Base output score from the agent
    base_score = agent.produce_output_score(state)

    # PoE modifier — verified traces get a small boost; suspicious/invalid penalised
    poe_mod = 0.0
    if poe:
        if poe.verdict == "verified":
            poe_mod = rng.uniform(0.0, 3.0)
        elif poe.verdict == "suspicious":
            poe_mod = rng.uniform(-8.0, -2.0)
        elif poe.verdict == "invalid":
            poe_mod = rng.uniform(-15.0, -5.0)

    true_score = max(0.0, min(100.0, base_score + poe_mod))

    # Each judge independently scores with noise
    judge_scores: dict[str, float] = {}
    for j in range(cfg.jury_num_judges):
        noise = rng.gauss(0.0, 5.0)
        judge_scores[f"judge_{j}"] = max(0.0, min(100.0, true_score + noise))

    scores = list(judge_scores.values())
    n = len(scores)
    mean_score = statistics.mean(scores)
    variance = statistics.variance(scores) if n > 1 else 0.0
    std_dev   = math.sqrt(variance) if variance > 0 else 0.0

    # Confidence interval (t-distribution approximation)
    if n > 1:
        t = _t_critical(n - 1)
        margin = t * (std_dev / math.sqrt(n))
    else:
        margin = 0.0

    agreement = (
        "high"       if std_dev <= 5.0   else
        "moderate"   if std_dev <= 15.0  else
        "low"
    )

    grade = (
        "Elite"   if mean_score >= 95 else
        "Gold"    if mean_score >= 90 else
        "Silver"  if mean_score >= 80 else
        "Bronze"  if mean_score >= 70 else
        "Unrated"
    )

    return JuryResult(
        judge_scores   = judge_scores,
        final_score    = round(mean_score, 2),
        score_variance = round(variance, 2),
        agreement_level= agreement,
        confidence_low = round(max(0.0, mean_score - margin), 2),
        confidence_high= round(min(100.0, mean_score + margin), 2),
        grade          = grade,
    )


def _t_critical(df: int) -> float:
    """Approximate t critical value at 95% CI."""
    if df <= 0:  return 12.706
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
             6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
    return table.get(df, 1.96)


# ─────────────────────────────────────────────────────────────────────────────
# Validator Consensus
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConsensusResult:
    fraud_detected:     bool
    validator_votes:    dict[str, bool]     # vid → fraud_detected
    agreement_rate:     float               # fraction agreeing with majority
    colluding_detected: bool                # watcher caught collusion
    latency_ms:         float               # max validator latency
    fraud_flags:        list[str]


def run_validator_consensus(
    task: SimTask,
    poe: Optional[SimPoETrace],
    state: SimState,
) -> ConsensusResult:
    """
    Select a validator subset, run their PoE checks, compute consensus.
    Mirrors the validator network described in AAIP v3 architecture.
    """
    available = [
        v for v in state.validators.values()
        if v.is_available(state)
    ]
    if not available:
        # No validators — default to unverified
        return ConsensusResult(
            fraud_detected=False, validator_votes={}, agreement_rate=0.0,
            colluding_detected=False, latency_ms=0.0, fraud_flags=[],
        )

    # Select N validators (VRF-like random selection)
    n_select = min(len(available), state.config.jury_num_judges)
    selected = state.sample(available, n_select)

    votes: dict[str, bool] = {}
    all_flags: list[str] = []
    max_latency = 0.0

    for validator in selected:
        detected, flags, latency = validator.validate_poe(task, poe, state)
        votes[validator.validator_id] = detected
        if detected:
            all_flags.extend(flags)
        max_latency = max(max_latency, latency)
        validator.tasks_validated += 1

    # Majority vote
    n_fraud = sum(votes.values())
    n_total = len(votes)
    majority_fraud = n_fraud > n_total / 2

    agreement_rate = (
        n_fraud / n_total if majority_fraud
        else (n_total - n_fraud) / n_total
    )

    # Check if watchers detected collusion
    colluding_detected = False
    for watcher in state.watchers.values():
        for vid in votes:
            proof = watcher.observe(vid, task, poe, state)
            if proof:
                colluding_detected = True
                watcher.fraud_proofs_submitted += 1
                state.counters["watcher_fraud_proofs"] += 1

    return ConsensusResult(
        fraud_detected     = majority_fraud,
        validator_votes    = votes,
        agreement_rate     = round(agreement_rate, 3),
        colluding_detected = colluding_detected,
        latency_ms         = round(max_latency, 1),
        fraud_flags        = list(set(all_flags)),
    )
