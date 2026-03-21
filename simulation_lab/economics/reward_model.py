"""
AAIP Simulation Lab — Economics
Reward model, staking model, and slashing mechanics.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class RewardModel:
    """
    Computes validator and agent rewards per task.
    Reward = task_value × fee_rate × share_weight
    """
    fee_rate:       float = 0.005
    validator_share:float = 0.40  # of protocol fee goes to validators
    staking_yield:  float = 0.0001  # per tick

    def compute_task_fee(self, task_value: float) -> float:
        return task_value * self.fee_rate

    def compute_validator_reward(self, fee: float, panel_size: int) -> float:
        return fee * self.validator_share / max(1, panel_size)

    def compute_staking_reward(self, stake: float) -> float:
        return stake * self.staking_yield


@dataclass
class StakingModel:
    """
    Validator staking requirements and delegation mechanics.
    """
    min_stake:            float = 500.0
    max_stake:            float = 10000.0
    slash_rate_mild:      float = 0.05   # for lazy behavior
    slash_rate_moderate:  float = 0.15   # for collusion
    slash_rate_severe:    float = 0.40   # for provable fraud

    def is_eligible(self, stake: float) -> bool:
        return stake >= self.min_stake

    def slash(self, stake: float, severity: str) -> tuple[float, float]:
        """Returns (remaining_stake, slashed_amount)."""
        rates = {
            "mild":     self.slash_rate_mild,
            "moderate": self.slash_rate_moderate,
            "severe":   self.slash_rate_severe,
        }
        rate    = rates.get(severity, self.slash_rate_mild)
        slashed = stake * rate
        return max(0.0, stake - slashed), slashed


@dataclass
class SlashingModel:
    """
    Tracks slashing events and their protocol impact.
    """
    def apply_fraud_penalty(self, validator: dict, severity: str = "moderate") -> float:
        staking = StakingModel()
        new_stake, slashed = staking.slash(validator.get("stake", 1000.0), severity)
        validator["stake"]   = new_stake
        validator["slashed"] = validator.get("slashed", 0.0) + slashed
        validator["reputation"] = max(0.0, validator.get("reputation", 50.0) - 15.0)
        return slashed
