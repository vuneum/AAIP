"""
AAIP Simulation Lab — Event Loop
Priority-queue based discrete-event scheduler.
"""
from __future__ import annotations
import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(order=True)
class Event:
    tick:     int
    priority: int                        # lower = higher priority at same tick
    name:     str     = field(compare=False)
    handler:  Callable = field(compare=False)
    payload:  Any      = field(compare=False, default=None)


class EventLoop:
    """Min-heap event queue for discrete-event simulation."""

    def __init__(self):
        self._heap: list[Event] = []
        self._seq: int = 0

    def schedule(self, tick: int, name: str, handler: Callable,
                 payload: Any = None, priority: int = 50) -> None:
        heapq.heappush(self._heap, Event(tick, priority, name, handler, payload))

    def drain_tick(self, tick: int) -> list[Event]:
        """Pop and return all events scheduled for `tick`."""
        due: list[Event] = []
        while self._heap and self._heap[0].tick <= tick:
            due.append(heapq.heappop(self._heap))
        return due

    def fire_all(self, tick: int, context: Any = None) -> list[Any]:
        results = []
        for event in self.drain_tick(tick):
            r = event.handler(event.payload, context)
            results.append(r)
        return results

    def pending(self) -> int:
        return len(self._heap)

    def clear(self) -> None:
        self._heap.clear()
