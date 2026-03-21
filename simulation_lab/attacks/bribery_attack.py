"""
AAIP Attack Module — Bribery Attack

Executor offers validators off-protocol incentives to approve invalid outputs.
Models rational validator decision-making under economic incentives.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass


@dataclass
class BriberyAttackConfig:
    task_reward:             float = 0.002    # legitimate task payout
    bribe_ratio:             float = 2.0      # bribe = bribe_ratio × task_reward
    validator_risk_tolerance:float = 0.5      # 0=very risk-averse, 1=reckless
    detection_probability:   float = 0.15     # probability a bribe is detected
    slash_on_detection:      float = 0.20     # fraction of stake slashed
    reputation_loss:         float = 25.0     # reputation points lost on detection


class BriberyAttack:
    """
    Models rational validator behavior under bribery pressure.

    Decision model for each validator:
        expected_profit = bribe_amount - (detection_prob × (stake_loss + rep_value_loss))
        if expected_profit > 0: accept bribe (with probability = risk_tolerance)

    Key insight: validators with low stake-to-reputation ratios are most resistant.
    High-stake validators have much more to lose.
    """

    def __init__(self, config: BriberyAttackConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._bribed_count       = 0
        self._bribe_attempts     = 0
        self._bribe_successes    = 0
        self._validator_bribed: dict[str, int] = {}  # vid → bribe_count

    def compute_bribe_decision(self, validator: dict, bribe_amount: float) -> bool:
        """
        Rational agent decision: accept bribe if E[profit] > 0.

        Expected cost of accepting:
          p_detect × (slash_fraction × stake + reputation_loss_in_USDC)

        We model reputation as worth ~0.5 USDC per point (configurable).
        """
        stake = validator.get("stake", 1000.0)
        rep   = validator.get("reputation", 50.0)

        reputation_value  = rep * 0.5  # USDC equivalent
        expected_loss     = self.cfg.detection_probability * (
            self.cfg.slash_on_detection * stake + reputation_value
        )
        expected_profit   = bribe_amount - expected_loss

        # Risk tolerance scales the acceptance threshold
        threshold = expected_profit / max(0.001, bribe_amount + expected_loss)
        accept_prob = max(0.0, min(1.0, threshold * self.cfg.validator_risk_tolerance + 0.1))

        return self.rng.random() < accept_prob

    def attempt_bribe(self, task: dict, panel: list[dict], engine) -> list[dict]:
        """
        For fraudulent tasks: attempt to bribe each panel validator.
        Returns modified vote list.
        """
        bribe_amount = task["value"] * self.cfg.bribe_ratio
        votes = []

        for v in panel:
            validator = next((x for x in engine.validators if x["id"] == v["id"]), None)
            if validator is None:
                votes.append({"id": v["id"], "approve": self.rng.random() < 0.12})
                continue

            if task.get("fraudulent"):
                self._bribe_attempts += 1
                accepted = self.compute_bribe_decision(validator, bribe_amount)

                if accepted:
                    self._bribed_count     += 1
                    self._bribe_successes  += 1
                    self._validator_bribed[v["id"]] = self._validator_bribed.get(v["id"], 0) + 1

                    # Check if detected
                    if self.rng.random() < self.cfg.detection_probability:
                        validator["reputation"] = max(0.0, validator["reputation"] - self.cfg.reputation_loss)
                        validator["slashed"]    += validator["stake"] * self.cfg.slash_on_detection

                    approve = True
                else:
                    approve = self.rng.random() < 0.10

                votes.append({"id": v["id"], "approve": approve, "bribed": accepted})
            else:
                votes.append({"id": v["id"], "approve": self.rng.random() < 0.92})

        return votes

    def get_metrics(self) -> dict:
        top_bribed = sorted(self._validator_bribed.items(), key=lambda x: -x[1])[:5]
        return {
            "bribery_success_rate":       round(self._bribe_successes / max(1, self._bribe_attempts), 4),
            "bribed_validator_count":     self._bribed_count,
            "bribe_attempts":             self._bribe_attempts,
            "top_bribed_validators":      top_bribed,
            "avg_bribe_amount":           round(self.cfg.task_reward * self.cfg.bribe_ratio, 6),
        }
