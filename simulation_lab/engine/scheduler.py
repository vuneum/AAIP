"""
AAIP Simulation Lab — Scheduler
Manages recurring and one-shot simulation hooks (CAV audits, attacks, etc.)
"""
from __future__ import annotations
from typing import Callable, Optional


class Scheduler:
    """
    Lightweight tick scheduler.
    Supports periodic events (every N ticks) and one-shot callbacks.
    """

    def __init__(self):
        self._periodic:  list[tuple[int, int, Callable]] = []  # (period, offset, fn)
        self._one_shots: dict[int, list[Callable]]       = {}

    def every(self, n_ticks: int, fn: Callable, offset: int = 0) -> "Scheduler":
        self._periodic.append((n_ticks, offset, fn))
        return self

    def at(self, tick: int, fn: Callable) -> "Scheduler":
        self._one_shots.setdefault(tick, []).append(fn)
        return self

    def fire(self, tick: int, context) -> None:
        for period, offset, fn in self._periodic:
            if (tick - offset) % period == 0:
                fn(tick, context)

        for fn in self._one_shots.pop(tick, []):
            fn(tick, context)
