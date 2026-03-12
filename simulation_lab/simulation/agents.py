"""
AAIP Simulation Lab — Agents
Simulates the full population of AI agents in the network.
Each agent has a capability profile, a true quality score, and a behaviour type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .core import SimState, SimConfig


# ─────────────────────────────────────────────────────────────────────────────
# Agent Types
# ─────────────────────────────────────────────────────────────────────────────

class AgentBehavior(str, Enum):
    HONEST          = "honest"           # performs genuinely, submits real PoE
    LAZY            = "lazy"             # real execution, minimal PoE
    DEGRADING       = "degrading"        # starts strong, quality falls over time
    GAMING          = "gaming"           # optimises for eval metrics, not real quality
    FABRICATOR      = "fabricator"       # fabricates PoE traces
    COLLUDING       = "colluding"        # coordinates with corrupt validators
    SYBIL           = "sybil"            # spins up many identities, thin capability


DOMAINS = ["coding", "finance", "general", "translation", "summarization", "data_analysis", "research"]

QUALITY_PROFILE = {
    AgentBehavior.HONEST:     (82.0, 8.0),   # mean, std of true quality
    AgentBehavior.LAZY:       (70.0, 12.0),
    AgentBehavior.DEGRADING:  (85.0, 5.0),   # degrades over time
    AgentBehavior.GAMING:     (75.0, 6.0),   # good on eval, weaker in CAV
    AgentBehavior.FABRICATOR: (40.0, 15.0),  # poor real quality, fakes PoE
    AgentBehavior.COLLUDING:  (55.0, 10.0),  # relies on corrupt validators
    AgentBehavior.SYBIL:      (50.0, 20.0),  # high variance, thin coverage
}


# ─────────────────────────────────────────────────────────────────────────────
# SimAgent
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimAgent:
    agent_id:       str
    owner:          str
    domain:         str
    behavior:       AgentBehavior
    true_quality:   float           # ground-truth capability (hidden from protocol)
    reputation:     float           # protocol-visible rolling score
    eval_history:   list[float]     = field(default_factory=list)
    cav_history:    list[dict]      = field(default_factory=list)
    task_count:     int             = 0
    fraud_count:    int             = 0
    detected_count: int             = 0
    earnings:       float           = 0.0
    is_active:      bool            = True
    ticks_alive:    int             = 0
    degradation_rate: float         = 0.0   # quality loss per tick for DEGRADING agents
    last_cav_tick:  int             = -999

    # Fabricator-specific — probability of submitting fake trace
    fabrication_prob: float         = 0.0
    # Gaming-specific — eval boost vs. true quality
    gaming_boost:     float         = 0.0

    @property
    def is_malicious(self) -> bool:
        return self.behavior not in (AgentBehavior.HONEST, AgentBehavior.LAZY)

    @property
    def grade(self) -> str:
        if self.reputation >= 95:  return "Elite"
        if self.reputation >= 90:  return "Gold"
        if self.reputation >= 80:  return "Silver"
        if self.reputation >= 70:  return "Bronze"
        return "Unrated"

    def tick(self, state: SimState) -> None:
        """Update agent state each simulation tick."""
        self.ticks_alive += 1
        if self.behavior == AgentBehavior.DEGRADING:
            self.true_quality = max(20.0, self.true_quality - self.degradation_rate)

    def produce_output_score(self, state: SimState) -> float:
        """
        Simulate the score an agent would receive for a genuine task.
        Honest agents score close to true quality; gaming agents boost on evals.
        """
        base = state.gauss(self.true_quality, 8.0, 0.0, 100.0)
        if self.behavior == AgentBehavior.GAMING:
            return min(100.0, base + self.gaming_boost)
        return base

    def produce_cav_score(self, state: SimState) -> float:
        """
        CAV score reflects true quality more accurately — gaming boost doesn't apply.
        """
        return state.gauss(self.true_quality, 10.0, 0.0, 100.0)

    def will_fabricate_poe(self, state: SimState) -> bool:
        return self.behavior == AgentBehavior.FABRICATOR and state.bernoulli(self.fabrication_prob)

    def update_reputation(self, new_score: float, weight: float = 1.0) -> None:
        """Blended rolling reputation update."""
        self.eval_history.append(new_score)
        window = self.eval_history[-10:]  # last 10 evals
        raw_avg = sum(window) / len(window)
        # Soft blend: don't jump more than 5 pts per update
        delta = (raw_avg - self.reputation) * min(1.0, weight)
        self.reputation = round(max(0.0, min(100.0, self.reputation + delta)), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Agent Factory
# ─────────────────────────────────────────────────────────────────────────────

def build_agent_population(state: SimState) -> dict[str, SimAgent]:
    """
    Instantiate the full agent population from SimConfig.
    Returns agent_id → SimAgent mapping.
    """
    cfg     = state.config
    rng     = state.rng
    agents: dict[str, SimAgent] = {}

    n_malicious = int(cfg.num_agents * cfg.malicious_agent_ratio)
    n_honest    = cfg.num_agents - n_malicious

    # Distribute malicious agents across behavior types
    mal_types = [
        AgentBehavior.GAMING,
        AgentBehavior.FABRICATOR,
        AgentBehavior.DEGRADING,
        AgentBehavior.COLLUDING,
        AgentBehavior.SYBIL,
    ]
    mal_dist = []
    for i in range(n_malicious):
        mal_dist.append(mal_types[i % len(mal_types)])
    rng.shuffle(mal_dist)

    def _make(behavior: AgentBehavior, idx: int) -> SimAgent:
        aid   = f"agent_{state.uid()}"
        owner = f"co_{idx % 20:03d}"
        domain = rng.choice(DOMAINS)
        mean_q, std_q = QUALITY_PROFILE[behavior]
        true_q = max(5.0, min(99.0, rng.gauss(mean_q, std_q)))

        # Initial reputation bootstrapped near true quality with some noise
        init_rep = max(20.0, min(95.0, rng.gauss(true_q, 5.0)))

        agent = SimAgent(
            agent_id=aid,
            owner=owner,
            domain=domain,
            behavior=behavior,
            true_quality=true_q,
            reputation=init_rep,
        )

        if behavior == AgentBehavior.DEGRADING:
            # Degrade 0.1–0.4 quality points per tick
            agent.degradation_rate = rng.uniform(0.05, 0.25)

        if behavior == AgentBehavior.FABRICATOR:
            agent.fabrication_prob = rng.uniform(0.6, 0.95)

        if behavior == AgentBehavior.GAMING:
            agent.gaming_boost = rng.uniform(5.0, 15.0)

        return agent

    # Honest agents
    for i in range(n_honest):
        agent = _make(AgentBehavior.HONEST, i)
        agents[agent.agent_id] = agent

    # Lazy agents (subset of honest pool — 20% of honest)
    lazy_count = max(1, int(n_honest * 0.2))
    lazy_ids = rng.sample(list(agents.keys()), lazy_count)
    for aid in lazy_ids:
        agents[aid].behavior = AgentBehavior.LAZY

    # Malicious agents
    for i, btype in enumerate(mal_dist):
        agent = _make(btype, n_honest + i)
        agents[agent.agent_id] = agent

    return agents
