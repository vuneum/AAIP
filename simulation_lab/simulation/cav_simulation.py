"""
AAIP Simulation Lab — CAV Simulation
Mirrors backend/cav.py: hourly random benchmark audits, deviation detection,
reputation adjustment.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .core import SimState
from .agents import SimAgent, AgentBehavior

CAV_TICKS_PER_CYCLE = 12   # every 12 ticks (= 1 hr at 5-min ticks)

@dataclass
class SimCAVRun:
    run_id:              str
    agent_id:            str
    task_domain:         str
    observed_score:      float
    expected_score:      float
    deviation:           float
    result:              str      # passed|failed|unreachable
    reputation_adjusted: bool
    adjustment_delta:    Optional[float]
    triggered_by:        str      # scheduled|manual|stress
    tick:                int


class CAVSimulator:
    """
    Runs hourly CAV cycles. Each cycle picks N eligible agents at random,
    assigns a hidden benchmark task, scores via CAV scorer (not jury),
    and adjusts reputation if deviation exceeds threshold.
    """

    def __init__(self, state: SimState):
        self.state = state

    def should_run_this_tick(self) -> bool:
        return self.state.clock.ticks % CAV_TICKS_PER_CYCLE == 0

    def run_cycle(self, triggered_by: str = "scheduled") -> list[SimCAVRun]:
        state  = self.state
        cfg    = state.config
        runs: list[SimCAVRun] = []

        eligible = self._eligible_agents()
        if not eligible:
            return runs

        selected = state.sample(eligible, min(cfg.cav_agents_per_run, len(eligible)))

        for agent in selected:
            run = self._audit_agent(agent, triggered_by)
            runs.append(run)
            state.cav_runs[run.run_id] = run
            agent.last_cav_tick = state.clock.ticks
            agent.cav_history.append({
                "tick": state.clock.ticks,
                "observed": run.observed_score,
                "expected": run.expected_score,
                "result":   run.result,
                "adjusted": run.reputation_adjusted,
            })
            state.inc("cav_total_runs")
            if run.result == "failed":
                state.inc("cav_failures")
            if run.reputation_adjusted:
                state.inc("cav_reputation_adjustments")

        return runs

    def _eligible_agents(self) -> list[SimAgent]:
        cfg   = self.state.config
        ticks = self.state.clock.ticks
        return [
            a for a in self.state.agents.values()
            if a.is_active
            and len(a.eval_history) >= 3
            and (ticks - a.last_cav_tick) >= cfg.cav_cooldown_ticks
        ]

    def _audit_agent(self, agent: SimAgent, triggered_by: str) -> SimCAVRun:
        state = self.state
        cfg   = state.config

        # Expected score = rolling average of last 10 evals
        history = agent.eval_history[-10:]
        expected = sum(history) / len(history) if history else agent.reputation

        # Observed score — CAV uses true quality (gaming boost doesn't apply)
        observed = agent.produce_cav_score(state)

        # If fabricator, CAV often catches the gap
        if agent.behavior == AgentBehavior.FABRICATOR:
            observed = state.gauss(agent.true_quality, 12.0, 0.0, 100.0)

        deviation = observed - expected
        threshold = cfg.cav_deviation_threshold
        rep_adjusted = abs(deviation) >= threshold

        if rep_adjusted:
            delta = deviation * cfg.cav_adjustment_weight
            agent.reputation = round(
                max(0.0, min(100.0, agent.reputation + delta)), 2
            )
            agent.eval_history.append(observed)  # inject CAV score into history
        else:
            delta = None

        result = (
            "passed" if observed >= expected - threshold else "failed"
        )

        return SimCAVRun(
            run_id             = f"cav_{state.uid()}",
            agent_id           = agent.agent_id,
            task_domain        = agent.domain,
            observed_score     = round(observed, 2),
            expected_score     = round(expected, 2),
            deviation          = round(deviation, 2),
            result             = result,
            reputation_adjusted= rep_adjusted,
            adjustment_delta   = round(delta, 2) if delta is not None else None,
            triggered_by       = triggered_by,
            tick               = state.clock.ticks,
        )
