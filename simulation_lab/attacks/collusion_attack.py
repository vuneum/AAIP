"""
AAIP Attack Module — Validator Collusion Attack

Malicious validators coordinate to approve invalid outputs.
Models coordinated Byzantine behavior with reputation decay.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass


@dataclass
class CollusionAttackConfig:
    collusion_rate:          float = 0.30   # fraction of validators that collude
    validator_pool_size:     int   = 50
    reputation_decay:        float = 0.05   # per-tick rep loss when detected
    coordination_probability:float = 0.85   # probability colluders actually coordinate
    detection_threshold:     float = 0.40   # watcher triggers above this approval rate on fraud


class CollusionAttack:
    """
    Simulates a coordinated validator collusion ring.

    Attack mechanism:
    1. A subset of validators form a collusion ring (offline coordination).
    2. When a malicious executor submits fraud, ring members vote APPROVE.
    3. If collusion ring exceeds consensus threshold, fraud passes.
    4. Watcher nodes observe anomalous approval rates and flag colluders.
    5. Detected colluders suffer reputation decay and stake slashing.
    """

    def __init__(self, config: CollusionAttackConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._successes  = 0
        self._attempts   = 0
        self._detections = 0
        self._colluders: set[str] = set()

    def setup(self, validators: list[dict]) -> None:
        """Mark validators as colluding based on collusion_rate."""
        n_colluders = max(1, int(len(validators) * self.cfg.collusion_rate))
        malicious   = [v for v in validators if v.get("malicious")]
        # Fill with honest validators if not enough malicious ones
        pool = malicious + [v for v in validators if not v.get("malicious")]
        for v in pool[:n_colluders]:
            v["colluding"] = True
            self._colluders.add(v["id"])

    def get_validator_votes(self, task: dict, panel: list[dict], engine) -> list[dict]:
        """
        Overrides default voting: colluding validators approve fraud unconditionally.
        """
        votes = []
        for v in panel:
            is_colluder = v["id"] in self._colluders

            if task.get("fraudulent"):
                self._attempts += 1
                if is_colluder and self.rng.random() < self.cfg.coordination_probability:
                    # Colluder approves fraud
                    approve = True
                    self._successes += 1
                elif not is_colluder:
                    # Honest validator rejects fraud
                    approve = self.rng.random() < 0.10
                else:
                    approve = self.rng.random() < 0.30
            else:
                # Clean task — everyone approves
                approve = self.rng.random() < 0.92

            votes.append({"id": v["id"], "approve": approve, "colluder": is_colluder})

        # Watcher anomaly detection
        colluder_approvals = sum(1 for v_vote, v in zip(votes, panel)
                                  if v_vote["colluder"] and v_vote["approve"]
                                  and task.get("fraudulent"))
        if colluder_approvals / max(1, len(panel)) > self.cfg.detection_threshold:
            self._detections += 1
            self._apply_reputation_decay(panel, engine)

        return votes

    def _apply_reputation_decay(self, panel: list[dict], engine) -> None:
        for v in panel:
            if v["id"] in self._colluders:
                validator = next((x for x in engine.validators if x["id"] == v["id"]), None)
                if validator:
                    validator["reputation"] = max(
                        0.0, validator["reputation"] - self.cfg.reputation_decay * 100
                    )
                    validator["slashed"] += validator["stake"] * 0.01  # 1% slash

    def get_metrics(self) -> dict:
        return {
            "collusion_success_rate":    round(self._successes / max(1, self._attempts), 4),
            "false_approval_rate":       round(self._successes / max(1, self._attempts), 4),
            "colluder_detection_rate":   round(self._detections / max(1, self._attempts), 4),
            "total_collusion_attempts":  self._attempts,
            "total_collusion_successes": self._successes,
        }
