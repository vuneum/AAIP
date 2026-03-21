"""
AAIP Simulation Lab — Proof of Execution (PoE) Simulation
Mirrors backend/poe.py fraud detection logic in the simulation layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .core import SimState
from .agents import SimAgent, AgentBehavior
from .tasks import SimTask


# ─────────────────────────────────────────────────────────────────────────────
# Simulated PoE Trace
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimPoETrace:
    trace_id:       str
    task_id:        str
    agent_id:       str
    started_ms:     int
    completed_ms:   int
    step_count:     int
    tool_calls:     int
    llm_calls:      int
    api_calls:      int
    reasoning_steps: int
    total_tokens:   int
    hash_submitted: bool
    hash_valid:     bool
    fraud_flags:    list[str] = field(default_factory=list)
    verdict:        str       = "unverified"   # verified|suspicious|invalid|unverified
    is_fabricated:  bool      = False

    @property
    def duration_ms(self) -> int:
        return self.completed_ms - self.started_ms


# ─────────────────────────────────────────────────────────────────────────────
# PoE Generator
# ─────────────────────────────────────────────────────────────────────────────

class PoESimulator:
    """
    Simulates PoE trace generation and server-side validation,
    mirroring the fraud detection logic in backend/poe.py.
    """

    # Duration distributions (ms) by agent behavior
    DURATION_DIST = {
        AgentBehavior.HONEST:     (3500, 1200),
        AgentBehavior.LAZY:       (2000, 800),
        AgentBehavior.DEGRADING:  (3000, 1000),
        AgentBehavior.GAMING:     (3200, 900),
        AgentBehavior.FABRICATOR: (200,  400),   # often suspiciously fast
        AgentBehavior.COLLUDING:  (2800, 1000),
        AgentBehavior.SYBIL:      (1500, 700),
    }

    def generate(self, task: SimTask, agent: SimAgent, state: SimState) -> SimPoETrace:
        rng = state.rng
        fabricated = agent.will_fabricate_poe(state)

        mean_dur, std_dur = self.DURATION_DIST.get(agent.behavior, (3000, 1000))
        duration_ms = max(50, int(rng.gauss(mean_dur, std_dur)))

        base_ms = state.clock.ticks * 60_000
        started_ms   = base_ms
        completed_ms = base_ms + duration_ms

        # Step counts — fabricators use minimal/inconsistent steps
        if fabricated:
            tool_calls   = rng.randint(0, 2)
            llm_calls    = rng.randint(0, 1)
            api_calls    = 0
            reasoning    = 0
            declared_tools = tool_calls + rng.randint(0, 3)  # mismatch introduced
            total_steps  = tool_calls + llm_calls
            tokens       = rng.randint(0, 200)
        else:
            tool_calls   = rng.randint(1, 5)
            llm_calls    = rng.randint(1, 3)
            api_calls    = rng.randint(0, 2)
            reasoning    = rng.randint(1, tool_calls)
            declared_tools = tool_calls
            total_steps  = tool_calls + llm_calls + api_calls + reasoning
            tokens       = rng.randint(200, 2000)

        # Hash — honest agents always submit valid hash; fabricators sometimes don't
        hash_submitted = not (agent.behavior == AgentBehavior.LAZY and rng.random() < 0.4)
        hash_valid     = hash_submitted and not fabricated

        # Run fraud detection (mirrors detect_fraud_signals in backend/poe.py)
        flags = self._detect_fraud(
            duration_ms   = duration_ms,
            started_ms    = started_ms,
            completed_ms  = completed_ms,
            step_count    = total_steps,
            tool_calls    = tool_calls,
            declared_tools= declared_tools,
            reasoning     = reasoning,
            hash_submitted= hash_submitted,
            hash_valid    = hash_valid,
            fabricated    = fabricated,
            state         = state,
        )

        # Verdict
        if not hash_submitted:
            verdict = "unverified"
        elif not hash_valid:
            verdict = "invalid"
        elif flags:
            verdict = "suspicious"
        else:
            verdict = "verified"

        return SimPoETrace(
            trace_id       = f"poe_{state.uid()}",
            task_id        = task.task_id,
            agent_id       = agent.agent_id,
            started_ms     = started_ms,
            completed_ms   = completed_ms,
            step_count     = total_steps,
            tool_calls     = tool_calls,
            llm_calls      = llm_calls,
            api_calls      = api_calls,
            reasoning_steps= reasoning,
            total_tokens   = tokens,
            hash_submitted = hash_submitted,
            hash_valid     = hash_valid,
            fraud_flags    = flags,
            verdict        = verdict,
            is_fabricated  = fabricated,
        )

    def _detect_fraud(
        self, duration_ms, started_ms, completed_ms, step_count,
        tool_calls, declared_tools, reasoning, hash_submitted, hash_valid,
        fabricated, state: SimState,
    ) -> list[str]:
        flags = []

        # 1. No steps
        if step_count == 0:
            flags.append("NO_EXECUTION_STEPS")

        # 2. Impossibly fast (< 100ms with tool calls)
        if duration_ms < 100 and tool_calls > 0:
            flags.append("SUSPICIOUSLY_FAST_EXECUTION")

        # 3. Invalid timestamps
        if completed_ms <= started_ms:
            flags.append("INVALID_TIMESTAMPS")

        # 4. Future timestamp (simulated — rare random noise)
        if state.bernoulli(0.001):
            flags.append("FUTURE_TIMESTAMP")

        # 5. Tool count mismatch
        if abs(declared_tools - tool_calls) > 2:
            flags.append("TOOL_COUNT_MISMATCH")

        # 6. No reasoning for complex task
        if tool_calls > 3 and reasoning == 0:
            flags.append("NO_REASONING_FOR_COMPLEX_TASK")

        # 7. Hash invalid
        if hash_submitted and not hash_valid:
            flags.append("HASH_MISMATCH")

        return flags
