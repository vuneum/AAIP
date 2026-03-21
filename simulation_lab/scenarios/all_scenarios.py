"""
AAIP Simulation Lab — Scenario Implementations (all in one file for clean imports)
"""
from __future__ import annotations
import random
from dataclasses import dataclass

from simulation_lab.attacks.collusion_attack     import CollusionAttack, CollusionAttackConfig
from simulation_lab.attacks.sybil_attack         import SybilAttack, SybilAttackConfig
from simulation_lab.attacks.bribery_attack       import BriberyAttack, BriberyAttackConfig
from simulation_lab.attacks.adversarial_task_attack import AdversarialTaskAttack, AdversarialTaskConfig
from simulation_lab.attacks.spam_attack          import SpamAttack, SpamAttackConfig
from simulation_lab.attacks.ai_judge_bias_attack import AIJudgeBiasAttack, AIJudgeBiasConfig


# ─────────────────────────────────────────────────────────────────────────────
# Base Scenario
# ─────────────────────────────────────────────────────────────────────────────

class BaseScenario:
    name = "base"
    def __init__(self, config):
        self.config = config
    def get_metrics(self, engine) -> dict:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Baseline
# ─────────────────────────────────────────────────────────────────────────────

class BaselineScenario(BaseScenario):
    name = "baseline"
    """Healthy ecosystem — no active attacks. Establishes performance baseline."""

    def get_validator_votes(self, task, panel, engine):
        rng = engine.rng
        votes = []
        for v in panel:
            if task.get("fraudulent"):
                approve = rng.random() < 0.10   # honest detection
            else:
                approve = rng.random() < 0.93
            votes.append({"id": v["id"], "approve": approve})
        return votes


# ─────────────────────────────────────────────────────────────────────────────
# 2. Collusion Scenario
# ─────────────────────────────────────────────────────────────────────────────

class CollusionScenario(BaseScenario):
    name = "collusion"

    def __init__(self, config):
        super().__init__(config)
        params = config.attack_params
        attack_cfg = CollusionAttackConfig(
            collusion_rate          = params.get("collusion_rate", 0.30),
            validator_pool_size     = config.validators,
            reputation_decay        = params.get("reputation_decay", 0.05),
            coordination_probability= params.get("coordination_probability", 0.85),
        )
        self.attack = CollusionAttack(attack_cfg, random.Random(config.seed + 1))

    def pre_tick(self, tick, engine, tasks):
        if tick == 0:
            self.attack.setup(engine.validators)

    def get_validator_votes(self, task, panel, engine):
        return self.attack.get_validator_votes(task, panel, engine)

    def get_metrics(self, engine) -> dict:
        return self.attack.get_metrics()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sybil Scenario
# ─────────────────────────────────────────────────────────────────────────────

class SybilScenario(BaseScenario):
    name = "sybil"

    def __init__(self, config):
        super().__init__(config)
        params = config.attack_params
        attack_cfg = SybilAttackConfig(
            sybil_validators          = params.get("sybil_validators", 100),
            honest_validators         = config.validators,
            validator_selection_method= params.get("validator_selection_method", "random"),
            sybil_stake               = params.get("sybil_stake", 100.0),
        )
        self.attack = SybilAttack(attack_cfg, random.Random(config.seed + 2))

    def pre_tick(self, tick, engine, tasks):
        if tick == 0:
            # Inject sybil validators into the pool
            engine.validators = self.attack.inject_sybils(engine.validators)

    def get_validator_votes(self, task, panel, engine):
        # Use sybil-aware panel selection
        sybil_panel = self.attack.select_panel(engine.validators, len(panel))
        return self.attack.get_votes(task, sybil_panel)

    def get_metrics(self, engine) -> dict:
        return self.attack.get_metrics()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bribery Scenario
# ─────────────────────────────────────────────────────────────────────────────

class BriberyScenario(BaseScenario):
    name = "bribery"

    def __init__(self, config):
        super().__init__(config)
        params = config.attack_params
        attack_cfg = BriberyAttackConfig(
            task_reward             = config.task_value_mean,
            bribe_ratio             = params.get("bribe_ratio", 2.0),
            validator_risk_tolerance= params.get("validator_risk_tolerance", 0.5),
            detection_probability   = params.get("detection_probability", 0.15),
        )
        self.attack = BriberyAttack(attack_cfg, random.Random(config.seed + 3))

    def get_validator_votes(self, task, panel, engine):
        if task.get("fraudulent") and task.get("malicious_executor"):
            return self.attack.attempt_bribe(task, panel, engine)
        votes = []
        for v in panel:
            approve = engine.rng.random() < (0.10 if task.get("fraudulent") else 0.92)
            votes.append({"id": v["id"], "approve": approve})
        return votes

    def get_metrics(self, engine) -> dict:
        return self.attack.get_metrics()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Adversarial Scenario
# ─────────────────────────────────────────────────────────────────────────────

class AdversarialScenario(BaseScenario):
    name = "adversarial"

    def __init__(self, config):
        super().__init__(config)
        from simulation_lab.attacks.adversarial_task_attack import AdversarialTechnique
        params = config.attack_params
        technique = AdversarialTechnique(
            params.get("technique", AdversarialTechnique.PROMPT_INJECTION.value)
        )
        attack_cfg = AdversarialTaskConfig(
            technique               = technique,
            judge_susceptibility    = params.get("judge_susceptibility", 0.30),
            adversarial_task_ratio  = params.get("adversarial_task_ratio", 0.40),
        )
        self.attack = AdversarialTaskAttack(attack_cfg, random.Random(config.seed + 4))

    def get_validator_votes(self, task, panel, engine):
        return self.attack.get_votes(task, panel)

    def get_metrics(self, engine) -> dict:
        m = self.attack.get_metrics()
        return {"judge_failure_rate": m["judge_failure_rate"], **m}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Spam Scenario
# ─────────────────────────────────────────────────────────────────────────────

class SpamScenario(BaseScenario):
    name = "spam"

    def __init__(self, config):
        super().__init__(config)
        params = config.attack_params
        attack_cfg = SpamAttackConfig(
            spam_task_count   = params.get("spam_task_count", 10000),
            task_reward       = params.get("task_reward", 0.00001),
            validator_capacity= config.validators * config.tasks_per_tick,
            spam_burst_tick   = params.get("spam_burst_tick", int(config.ticks * 0.3)),
            burst_duration    = params.get("burst_duration", int(config.ticks * 0.15)),
        )
        self.attack = SpamAttack(attack_cfg, random.Random(config.seed + 5))

    def modify_task_rate(self, base_rate: int, tick: int, engine) -> int:
        return self.attack.modify_task_rate(base_rate, tick)

    def get_validator_votes(self, task, panel, engine):
        votes = []
        for v in panel:
            approve = engine.rng.random() < (0.10 if task.get("fraudulent") else 0.92)
            votes.append({"id": v["id"], "approve": approve})
        return votes

    def get_metrics(self, engine) -> dict:
        m = self.attack.get_metrics()
        return {"spam_overload_rate": m["spam_overload_rate"], **m}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Mixed Attack Scenario
# ─────────────────────────────────────────────────────────────────────────────

class MixedAttackScenario(BaseScenario):
    """
    Combines collusion + bribery + adversarial techniques simultaneously.
    Represents a sophisticated, multi-vector attack.
    """
    name = "mixed"

    def __init__(self, config):
        super().__init__(config)
        rng = random.Random(config.seed + 99)
        params = config.attack_params

        self.collusion = CollusionAttack(
            CollusionAttackConfig(collusion_rate=0.20), rng
        )
        self.bribery = BriberyAttack(
            BriberyAttackConfig(
                task_reward=config.task_value_mean,
                bribe_ratio=params.get("bribe_ratio", 1.5),
            ), rng
        )
        from simulation_lab.attacks.adversarial_task_attack import AdversarialTechnique
        self.adversarial = AdversarialTaskAttack(
            AdversarialTaskConfig(
                technique=AdversarialTechnique.SEMANTIC_AMBIGUITY,
                adversarial_task_ratio=0.30,
            ), rng
        )
        self._phase = "collusion"  # collusion → bribery → adversarial → all

    def pre_tick(self, tick, engine, tasks):
        total = engine.config.ticks
        if tick == 0:
            self.collusion.setup(engine.validators)
        # Rotate attack phases to simulate adaptive adversary
        if tick < total * 0.33:
            self._phase = "collusion"
        elif tick < total * 0.66:
            self._phase = "bribery"
        else:
            self._phase = "all"

    def get_validator_votes(self, task, panel, engine):
        if self._phase == "collusion":
            return self.collusion.get_validator_votes(task, panel, engine)
        elif self._phase == "bribery":
            if task.get("fraudulent"):
                return self.bribery.attempt_bribe(task, panel, engine)
        # "all" phase or fallback: adversarial
        return self.adversarial.get_votes(task, panel)

    def get_metrics(self, engine) -> dict:
        cm = self.collusion.get_metrics()
        bm = self.bribery.get_metrics()
        am = self.adversarial.get_metrics()
        return {
            "collusion_success_rate": cm["collusion_success_rate"],
            "bribery_success_rate":   bm["bribery_success_rate"],
            "judge_failure_rate":     am["judge_failure_rate"],
            "phase":                  self._phase,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Registry helper
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_MAP = {
    "baseline":    BaselineScenario,
    "collusion":   CollusionScenario,
    "sybil":       SybilScenario,
    "bribery":     BriberyScenario,
    "adversarial": AdversarialScenario,
    "spam":        SpamScenario,
    "mixed":       MixedAttackScenario,
}

def get_scenario(name: str, config):
    cls = SCENARIO_MAP.get(name, BaselineScenario)
    return cls(config)
