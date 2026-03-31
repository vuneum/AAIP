"""
AAIP Attack Module — Adversarial Task Attack

Executor produces outputs designed to fool AI judges.
Techniques: prompt injection, adversarial formatting, semantic ambiguity.
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from enum import Enum


class AdversarialTechnique(str, Enum):
    PROMPT_INJECTION    = "prompt_injection"
    ADVERSARIAL_FORMAT  = "adversarial_format"
    SEMANTIC_AMBIGUITY  = "semantic_ambiguity"
    STRUCTURED_HALLUCINATION = "structured_hallucination"
    MISLEADING_REASONING     = "misleading_reasoning"
    CONFIDENCE_INFLATION     = "confidence_inflation"


@dataclass
class AdversarialTaskConfig:
    technique:               AdversarialTechnique = AdversarialTechnique.PROMPT_INJECTION
    judge_susceptibility:    float = 0.30   # baseline LLM judge failure rate
    format_exploit_boost:    float = 0.20   # additional failure rate from formatting
    injection_boost:         float = 0.25   # additional failure from injection
    validator_correction:    float = 0.60   # probability validators correct a failed judge
    adversarial_task_ratio:  float = 0.40   # fraction of malicious tasks using adversarial technique


# Effect of each technique on judge failure probability
TECHNIQUE_FAILURE_BOOST = {
    AdversarialTechnique.PROMPT_INJECTION:          0.25,
    AdversarialTechnique.ADVERSARIAL_FORMAT:        0.18,
    AdversarialTechnique.SEMANTIC_AMBIGUITY:        0.20,
    AdversarialTechnique.STRUCTURED_HALLUCINATION:  0.22,
    AdversarialTechnique.MISLEADING_REASONING:      0.15,
    AdversarialTechnique.CONFIDENCE_INFLATION:      0.12,
}

# How well validators catch each technique
VALIDATOR_CORRECTION_BOOST = {
    AdversarialTechnique.PROMPT_INJECTION:          0.70,   # easy to detect in PoE
    AdversarialTechnique.ADVERSARIAL_FORMAT:        0.50,   # moderate
    AdversarialTechnique.SEMANTIC_AMBIGUITY:        0.30,   # hard
    AdversarialTechnique.STRUCTURED_HALLUCINATION:  0.55,
    AdversarialTechnique.MISLEADING_REASONING:      0.45,
    AdversarialTechnique.CONFIDENCE_INFLATION:      0.35,
}


class AdversarialTaskAttack:
    """
    Simulates adversarial output crafting to fool AI judges.

    Two-stage evaluation:
    1. AI judge evaluates output (may be fooled)
    2. Validator consensus can override the judge

    The gap between judge failure rate and final approval rate
    measures how much validators add to security.
    """

    def __init__(self, config: AdversarialTaskConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._judge_failures     = 0
        self._judge_evaluations  = 0
        self._validator_fixes    = 0
        self._final_approvals_of_fraud = 0
        self._adversarial_tasks  = 0

    def evaluate_task(self, task: dict, panel: list[dict]) -> dict:
        """
        Two-stage evaluation: AI judge → validator consensus.
        Returns enhanced task result with adversarial metrics.
        """
        technique  = self.cfg.technique
        is_adversarial = (
            task.get("fraudulent") and
            self.rng.random() < self.cfg.adversarial_task_ratio
        )

        if is_adversarial:
            self._adversarial_tasks += 1
            task["adversarial_technique"] = technique.value

        # Stage 1: AI judge
        base_failure  = self.cfg.judge_susceptibility
        extra_failure = TECHNIQUE_FAILURE_BOOST.get(technique, 0.0) if is_adversarial else 0.0
        judge_failure_prob = min(0.95, base_failure + extra_failure)

        self._judge_evaluations += 1
        judge_failed = task.get("fraudulent") and self.rng.random() < judge_failure_prob
        if judge_failed:
            self._judge_failures += 1
            judge_score = self.rng.uniform(70, 95)  # incorrectly high score
        elif task.get("fraudulent"):
            judge_score = self.rng.uniform(10, 40)  # correctly low score
        else:
            judge_score = self.rng.uniform(75, 98)  # legitimate task

        # Stage 2: Validators override judge
        correction_base  = self.cfg.validator_correction
        technique_correction = VALIDATOR_CORRECTION_BOOST.get(technique, 0.5)
        can_correct = judge_failed and self.rng.random() < (
            correction_base * technique_correction
        )

        if can_correct:
            self._validator_fixes += 1
            final_approved = False
        elif judge_failed:
            final_approved = True
            self._final_approvals_of_fraud += 1
        else:
            final_approved = judge_score > 50

        return {
            "judge_score":       judge_score,
            "judge_failed":      judge_failed,
            "validator_fixed":   can_correct,
            "final_approved":    final_approved,
            "is_adversarial":    is_adversarial,
            "technique":         technique.value if is_adversarial else None,
        }

    def get_votes(self, task: dict, panel: list[dict]) -> list[dict]:
        """Generate votes influenced by adversarial evaluation."""
        eval_result = self.evaluate_task(task, panel)
        votes = []
        for v in panel:
            if eval_result["judge_failed"] and not eval_result["validator_fixed"]:
                # Judge was fooled, validators follow judge signal
                approve = self.rng.random() < 0.75
            elif task.get("fraudulent"):
                approve = self.rng.random() < 0.12
            else:
                approve = self.rng.random() < 0.91
            votes.append({"id": v["id"], "approve": approve})
        return votes

    def get_metrics(self) -> dict:
        judge_failure_rate = self._judge_failures / max(1, self._judge_evaluations)
        validator_correction_rate = self._validator_fixes / max(1, self._judge_failures)
        net_failure_rate   = self._final_approvals_of_fraud / max(1, self._judge_evaluations)
        return {
            "judge_failure_rate":         round(judge_failure_rate, 4),
            "validator_correction_rate":  round(validator_correction_rate, 4),
            "net_adversarial_success":    round(net_failure_rate, 4),
            "adversarial_tasks":          self._adversarial_tasks,
            "technique":                  self.cfg.technique.value,
            "security_improvement":       round(judge_failure_rate - net_failure_rate, 4),
        }
