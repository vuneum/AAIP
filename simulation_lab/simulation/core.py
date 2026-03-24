"""
AAIP Simulation Lab — Core Engine
Discrete-event simulation clock, state container, and event bus.
"""

from __future__ import annotations

import time
import uuid
import random
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger("aaip.sim.core")


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Clock
# ─────────────────────────────────────────────────────────────────────────────

class SimClock:
    """
    Discrete-event simulation clock.
    Each tick represents one simulated minute.
    """

    def __init__(self, start: Optional[datetime] = None, tick_minutes: int = 1):
        self.start      = start or datetime(2025, 1, 1, 0, 0, 0)
        self.current    = self.start
        self.tick_mins  = tick_minutes
        self.ticks      = 0
        self._wall_start = time.perf_counter()

    def advance(self) -> datetime:
        self.current += timedelta(minutes=self.tick_mins)
        self.ticks   += 1
        return self.current

    @property
    def day(self) -> int:
        return (self.current - self.start).days

    @property
    def hour_of_day(self) -> int:
        return self.current.hour

    @property
    def wall_elapsed(self) -> float:
        return time.perf_counter() - self._wall_start

    def __str__(self) -> str:
        return self.current.strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────────────────────────
# Event Bus
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    event_type: str
    payload:    dict = field(default_factory=dict)
    timestamp:  Optional[datetime] = None
    source_id:  Optional[str] = None


class EventBus:
    """Simple synchronous event bus for simulation components."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._log: list[Event] = []

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event: Event) -> None:
        self._log.append(event)
        for handler in self._handlers.get(event_type := event.event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.warning("Event handler error [%s]: %s", event_type, e)

    def events_of_type(self, event_type: str) -> list[Event]:
        return [e for e in self._log if e.event_type == event_type]

    def clear(self) -> None:
        self._log.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimConfig:
    """Top-level simulation configuration. All durations in simulated minutes."""

    # Network composition
    num_agents:             int   = 100
    num_validators:         int   = 10
    num_watchers:           int   = 5
    malicious_agent_ratio:  float = 0.10    # fraction of agents that are adversarial
    malicious_validator_ratio: float = 0.0  # fraction of validators that collude

    # Task parameters
    tasks_per_day:          int   = 500
    sim_days:               int   = 30
    tick_minutes:           int   = 5       # one simulated tick = 5 minutes

    # Task value distribution (USDC)
    task_value_mean:        float = 0.002
    task_value_std:         float = 0.001
    task_value_min:         float = 0.0005
    task_value_max:         float = 0.050

    # Protocol parameters (mirroring real AAIP config)
    cav_agents_per_run:         int   = 3
    cav_deviation_threshold:    float = 10.0
    cav_adjustment_weight:      float = 0.3
    cav_cooldown_ticks:         int   = 288   # 24h / 5min = 288 ticks

    jury_num_judges:            int   = 3
    jury_agreement_threshold:   float = 15.0  # std_dev < this = high agreement

    poe_fraud_check_enabled:    bool  = True
    reputation_window:          int   = 10    # last N evals for rolling avg

    # Escrow
    escrow_fee_rate:            float = 0.005  # 0.5%
    dispute_probability_base:   float = 0.01   # 1% of tasks disputed

    # Stress parameters
    stress_multiplier:          float = 1.0    # task volume multiplier
    validator_failure_rate:     float = 0.0    # probability a validator fails per tick
    network_partition_prob:     float = 0.0    # probability of network partition event

    # Output
    seed:                   int   = 42
    verbose:                bool  = False

    def tasks_per_tick(self) -> float:
        """Average tasks arriving per simulation tick."""
        ticks_per_day = (24 * 60) / self.tick_minutes
        return (self.tasks_per_day * self.stress_multiplier) / ticks_per_day

    def total_ticks(self) -> int:
        ticks_per_day = int((24 * 60) / self.tick_minutes)
        return self.sim_days * ticks_per_day


# ─────────────────────────────────────────────────────────────────────────────
# Simulation State Container
# ─────────────────────────────────────────────────────────────────────────────

class SimState:
    """
    Central mutable state for the entire simulation.
    All components read from and write to this object.
    """

    def __init__(self, config: SimConfig):
        self.config         = config
        self.clock          = SimClock(tick_minutes=config.tick_minutes)
        self.bus            = EventBus()
        self.rng            = random.Random(config.seed)

        # Registry maps — id → object
        self.agents:       dict[str, Any] = {}
        self.validators:   dict[str, Any] = {}
        self.watchers:     dict[str, Any] = {}
        self.tasks:        dict[str, Any] = {}
        self.poe_records:  dict[str, Any] = {}
        self.cav_runs:     dict[str, Any] = {}
        self.payments:     dict[str, Any] = {}
        self.disputes:     dict[str, Any] = {}
        self.ledger:       dict[str, list] = defaultdict(list)  # agent_id → entries

        # Protocol-level counters (fast path — avoid scanning dicts each tick)
        self.counters: dict[str, int | float] = defaultdict(float)
        self.tick_history: list[dict] = []

    # ── Helpers ──────────────────────────────────────────────────────────────

    def uid(self) -> str:
        return uuid.uuid4().hex[:12]

    def gauss(self, mean: float, std: float, lo: float = 0.0, hi: float = float("inf")) -> float:
        return max(lo, min(hi, self.rng.gauss(mean, std)))

    def bernoulli(self, p: float) -> bool:
        return self.rng.random() < p

    def choice(self, seq):
        return self.rng.choice(seq)

    def sample(self, seq, k: int):
        return self.rng.sample(seq, min(k, len(seq)))

    def snapshot_counters(self) -> dict:
        return dict(self.counters)

    def inc(self, key: str, amount: float = 1.0) -> None:
        self.counters[key] += amount
