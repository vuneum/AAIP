"""
AAIP Attack Module — Spam Task Attack

Floods the system with thousands of low-value tasks to overwhelm validators.
"""
from __future__ import annotations
import random
from dataclasses import dataclass


@dataclass
class SpamAttackConfig:
    spam_task_count:     int   = 10000
    task_reward:         float = 0.00001   # near-zero value
    validator_capacity:  int   = 100       # tasks/tick capacity
    spam_burst_tick:     int   = 50        # when the spam burst starts
    burst_duration:      int   = 20        # how long the burst lasts


class SpamAttack:
    """
    Models resource exhaustion attack on the validator network.

    Mechanism:
    1. Attacker floods system with tiny-value tasks
    2. Validators exhaust capacity — legitimate tasks starve
    3. Latency spikes; some tasks time out
    4. Protocol revenue drops (spam tasks have tiny fees)
    """

    def __init__(self, config: SpamAttackConfig, rng: random.Random):
        self.cfg = config
        self.rng = rng
        self._spam_injected    = 0
        self._queue_depths:  list[int]   = []
        self._latency_spikes:list[float] = []
        self._legit_delayed  = 0
        self._timed_out      = 0

    def modify_task_rate(self, base_rate: int, tick: int) -> int:
        burst_end = self.cfg.spam_burst_tick + self.cfg.burst_duration
        if self.cfg.spam_burst_tick <= tick < burst_end:
            spam_rate = self.cfg.validator_capacity * 5  # 5× overload
            self._spam_injected += spam_rate
            return base_rate + spam_rate
        return base_rate

    def compute_latency(self, base_latency: float, tick: int, queue_depth: int) -> float:
        """Latency grows super-linearly with queue depth."""
        if queue_depth > self.cfg.validator_capacity:
            overload = queue_depth / self.cfg.validator_capacity
            spike    = base_latency * (overload ** 1.8)
            self._latency_spikes.append(spike)
            return spike
        return base_latency

    def get_metrics(self) -> dict:
        overload_ticks = len(self._latency_spikes)
        avg_spike = sum(self._latency_spikes) / max(1, len(self._latency_spikes))
        return {
            "spam_tasks_injected":  self._spam_injected,
            "overload_ticks":       overload_ticks,
            "avg_spike_latency_ms": round(avg_spike, 2),
            "spam_overload_rate":   round(overload_ticks / max(1, self.cfg.burst_duration), 4),
            "legit_tasks_delayed":  self._legit_delayed,
        }
