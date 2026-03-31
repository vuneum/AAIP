"""
AAIP Attack Module — AI Judge Bias Attack

Exploits systematic weaknesses in LLM evaluators:
structured hallucination, misleading reasoning chains,
confidence inflation, authority spoofing.
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from enum import Enum


class BiasExploit(str, Enum):
    STRUCTURED_HALLUCINATION  = "structured_hallucination"
    MISLEADING_REASONING      = "misleading_reasoning"
    CONFIDENCE_INFLATION      = "confidence_inflation"
    AUTHORITY_SPOOFING        = "authority_spoofing"
    FORMAT_ANCHORING          = "format_anchoring"
    VERBOSE_PADDING           = "verbose_padding"


@dataclass
class AIJudgeBiasConfig:
    exploit:                 BiasExploit = BiasExploit.STRUCTURED_HALLUCINATION
    judge_model_temperature: float = 0.7     # higher = more exploitable
    baseline_accuracy:       float = 0.85    # judge accuracy without attack
    exploit_degradation:     float = 0.30    # accuracy drop under attack
    multi_judge_correction:  float = 0.65    # probability multi-judge panel corrects
    consensus_correction:    float = 0.75    # validator consensus correction


EXPLOIT_DEGRADATION = {
    BiasExploit.STRUCTURED_HALLUCINATION: 0.30,
    BiasExploit.MISLEADING_REASONING:     0.22,
    BiasExploit.CONFIDENCE_INFLATION:     0.18,
    BiasExploit.AUTHORITY_SPOOFING:       0.25,
    BiasExploit.FORMAT_ANCHORING:         0.15,
    BiasExploit.VERBOSE_PADDING:          0.10,
}

# Temperature amplifies bias susceptibility
def temperature_amplifier(temp: float) -> float:
    return 1.0 + (temp - 0.5) * 0.4  # 0.5 temp → 1.0×, 1.0 temp → 1.2×


class AIJudgeBiasAttack:
    """
    Simulates exploitation of LLM judge biases.

    Multi-judge panel reduces attack effectiveness significantly.
    Validator consensus provides a second line of defense.

    Attack pipeline:
    1. Attacker crafts output with bias exploit embedded
    2. LLM judge is polled — accuracy degraded by exploit
    3. Multiple judges reduce individual bias through ensemble
    4. Validators check structural signals (PoE), not reasoning
    5. Final consensus may override biased judge scores
    """

    def __init__(self, config: AIJudgeBiasConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._judge_evaluations     = 0
        self._judge_wrong           = 0
        self._ensemble_corrected    = 0
        self._validator_corrected   = 0
        self._final_fraud_approved  = 0
        self._accuracy_history:     list[float] = []

    def simulate_judge_panel(self, task: dict, n_judges: int = 3) -> dict:
        """Simulate a panel of n_judges each potentially biased."""
        exploit     = self.cfg.exploit
        deg         = EXPLOIT_DEGRADATION.get(exploit, 0.20)
        temp_mult   = temperature_amplifier(self.cfg.judge_model_temperature)

        attacked_accuracy = self.cfg.baseline_accuracy - (deg * temp_mult)
        attacked_accuracy = max(0.10, min(0.99, attacked_accuracy))

        scores       = []
        wrong_judges = 0
        for _ in range(n_judges):
            self._judge_evaluations += 1
            if task.get("fraudulent"):
                # Correct = low score
                correct = self.rng.random() < attacked_accuracy
                score   = self.rng.uniform(10, 45) if correct else self.rng.uniform(60, 95)
                if not correct:
                    wrong_judges += 1
                    self._judge_wrong += 1
            else:
                # Legitimate task — judge rarely wrong
                score = self.rng.uniform(72, 98)
            scores.append(score)

        avg_score     = sum(scores) / len(scores)
        ensemble_wrong = wrong_judges == n_judges  # ALL judges failed

        if not ensemble_wrong and wrong_judges > 0:
            self._ensemble_corrected += 1  # majority overrode biased minority

        # Validator consensus correction
        val_corrected = False
        if ensemble_wrong and task.get("fraudulent"):
            val_corrected = self.rng.random() < self.cfg.consensus_correction
            if val_corrected:
                self._validator_corrected += 1
            else:
                self._final_fraud_approved += 1

        tick_accuracy = 1 - (self._judge_wrong / max(1, self._judge_evaluations))
        self._accuracy_history.append(tick_accuracy)

        return {
            "avg_score":         avg_score,
            "ensemble_wrong":    ensemble_wrong,
            "validator_corrected": val_corrected,
            "final_approved":    avg_score > 50 and not val_corrected,
            "exploit_used":      exploit.value,
            "individual_wrong":  wrong_judges,
        }

    def get_votes(self, task: dict, panel: list[dict]) -> list[dict]:
        eval_result = self.simulate_judge_panel(task, n_judges=len(panel))
        votes = []
        for v in panel:
            if eval_result["ensemble_wrong"] and not eval_result["validator_corrected"]:
                approve = self.rng.random() < 0.78
            elif task.get("fraudulent"):
                approve = self.rng.random() < 0.10
            else:
                approve = self.rng.random() < 0.92
            votes.append({"id": v["id"], "approve": approve})
        return votes

    def get_metrics(self) -> dict:
        judge_failure = self._judge_wrong / max(1, self._judge_evaluations)
        net_failure   = self._final_fraud_approved / max(1, self._judge_evaluations)
        ensemble_help = self._ensemble_corrected / max(1, self._judge_wrong)
        return {
            "judge_failure_rate":         round(judge_failure, 4),
            "ensemble_correction_rate":   round(ensemble_help, 4),
            "validator_correction_rate":  round(self._validator_corrected / max(1, self._judge_evaluations), 4),
            "net_fraud_approval_rate":    round(net_failure, 4),
            "exploit_used":               self.cfg.exploit.value,
            "accuracy_degradation":       round(EXPLOIT_DEGRADATION.get(self.cfg.exploit, 0.0), 4),
            "multi_judge_value":          round(judge_failure - net_failure, 4),
        }
