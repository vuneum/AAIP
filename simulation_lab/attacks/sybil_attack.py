"""
AAIP Attack Module — Sybil Validator Attack

Attacker generates hundreds of fake validators to capture consensus.
Models Sybil resistance of selection mechanisms.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass


@dataclass
class SybilAttackConfig:
    sybil_validators:          int   = 100  # fake validators injected
    honest_validators:         int   = 50
    validator_selection_method:str   = "random"   # random | stake_weighted | reputation_weighted
    sybil_stake:               float = 100.0      # each Sybil has minimal stake
    min_stake_threshold:       float = 500.0      # protocol minimum stake requirement
    registration_fee:          float = 10.0       # USDC per registration


class SybilAttack:
    """
    Simulates a Sybil attack on validator selection.

    Attack mechanism:
    1. Attacker registers N sybil validators with minimal stake.
    2. Depending on selection method, sybil nodes may dominate panels.
    3. Stake-weighted selection resists sybil attacks naturally.
    4. Random selection is fully vulnerable.
    5. Reputation-weighted selection has partial resistance.

    Key insight: capture probability = sybil_count / total_validators
    under random selection, but much lower under stake-weighted.
    """

    def __init__(self, config: SybilAttackConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._sybil_selections   = 0
        self._total_selections   = 0
        self._corrupted_panels   = 0
        self._total_panels       = 0
        self._sybil_ids: set[str] = set()

    def inject_sybils(self, validators: list[dict]) -> list[dict]:
        """Inject sybil validators into the validator pool."""
        sybils = []
        for i in range(self.cfg.sybil_validators):
            vid = f"SYB{i:04d}"
            sybils.append({
                "id":        vid,
                "malicious": True,
                "sybil":     True,
                "stake":     self.cfg.sybil_stake,
                "reputation":30.0 + self.rng.gauss(0, 5),
                "online":    True,
                "tasks_seen":0,
                "fraud_caught":0,
                "rewards":   0.0,
                "slashed":   0.0,
                "behavior":  "sybil",
            })
            self._sybil_ids.add(vid)
        return validators + sybils

    def select_panel(self, validators: list[dict], panel_size: int) -> list[dict]:
        """
        Select validator panel using configured method.
        Different methods have dramatically different sybil resistance.
        """
        self._total_panels += 1
        method = self.cfg.validator_selection_method

        if method == "stake_weighted":
            panel = self._stake_weighted_select(validators, panel_size)
        elif method == "reputation_weighted":
            panel = self._reputation_weighted_select(validators, panel_size)
        else:
            # Random — fully vulnerable to sybil
            panel = self.rng.sample(validators, min(panel_size, len(validators)))

        sybil_in_panel = sum(1 for v in panel if v["id"] in self._sybil_ids)
        self._sybil_selections += sybil_in_panel
        self._total_selections += len(panel)

        # Panel is "corrupted" if sybils have majority
        if sybil_in_panel / max(1, len(panel)) >= 0.5:
            self._corrupted_panels += 1

        return panel

    def _stake_weighted_select(self, validators: list[dict], n: int) -> list[dict]:
        total_stake = sum(v["stake"] for v in validators)
        if total_stake == 0:
            return self.rng.sample(validators, min(n, len(validators)))
        weights = [v["stake"] / total_stake for v in validators]
        selected = []
        remaining = list(validators)
        rem_weights = list(weights)
        for _ in range(min(n, len(remaining))):
            idx = self._weighted_choice(rem_weights)
            selected.append(remaining.pop(idx))
            rem_weights.pop(idx)
            total = sum(rem_weights)
            if total > 0:
                rem_weights = [w / total for w in rem_weights]
        return selected

    def _reputation_weighted_select(self, validators: list[dict], n: int) -> list[dict]:
        total_rep = sum(max(0.1, v["reputation"]) for v in validators)
        weights   = [max(0.1, v["reputation"]) / total_rep for v in validators]
        selected  = []
        remaining = list(validators)
        rem_weights = list(weights)
        for _ in range(min(n, len(remaining))):
            idx = self._weighted_choice(rem_weights)
            selected.append(remaining.pop(idx))
            rem_weights.pop(idx)
            total = sum(rem_weights)
            if total > 0:
                rem_weights = [w / total for w in rem_weights]
        return selected

    def _weighted_choice(self, weights: list[float]) -> int:
        r   = self.rng.random()
        cum = 0.0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return i
        return len(weights) - 1

    def get_votes(self, task: dict, panel: list[dict]) -> list[dict]:
        votes = []
        for v in panel:
            is_sybil = v["id"] in self._sybil_ids
            if is_sybil and task.get("fraudulent"):
                approve = self.rng.random() < 0.90  # sybils approve fraud
            elif task.get("fraudulent"):
                approve = self.rng.random() < 0.12
            else:
                approve = self.rng.random() < 0.91
            votes.append({"id": v["id"], "approve": approve, "sybil": is_sybil})
        return votes

    def get_metrics(self) -> dict:
        sybil_fraction = len(self._sybil_ids) / max(1, len(self._sybil_ids) + self.cfg.honest_validators)
        theoretical_capture = sybil_fraction  # under random selection
        actual_capture = self._corrupted_panels / max(1, self._total_panels)
        return {
            "sybil_capture_probability":    round(actual_capture, 4),
            "theoretical_capture_probability": round(theoretical_capture, 4),
            "sybil_fraction_in_panels":     round(self._sybil_selections / max(1, self._total_selections), 4),
            "corrupted_panels":             self._corrupted_panels,
            "total_panels":                 self._total_panels,
            "selection_method":             self.cfg.validator_selection_method,
            "sybil_resistance_score":       round(1 - actual_capture / max(0.001, theoretical_capture), 4),
        }
