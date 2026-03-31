"""
AAIP Simulation Lab — Metrics Collector
Tracks all simulation metrics with time-series support and multi-format export.
"""
from __future__ import annotations
import csv
import json
import math
import statistics
from dataclasses import dataclass, asdict, field
from io import StringIO
from pathlib import Path
from typing import Any


@dataclass
class MetricPoint:
    tick:   int
    name:   str
    value:  float
    tags:   dict = field(default_factory=dict)


class MetricsCollector:
    """Collects named metrics across simulation ticks."""

    def __init__(self):
        self._points:  list[MetricPoint] = []
        self._gauges:  dict[str, float]  = {}
        self._counters:dict[str, float]  = {}

    def record(self, tick: int, name: str, value: float, **tags) -> None:
        self._points.append(MetricPoint(tick, name, value, tags))
        self._gauges[name] = value

    def increment(self, name: str, amount: float = 1.0) -> None:
        self._counters[name] = self._counters.get(name, 0.0) + amount

    def gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    def counter(self, name: str) -> float:
        return self._counters.get(name, 0.0)

    def series(self, name: str) -> list[dict]:
        return [{"tick": p.tick, "value": p.value}
                for p in self._points if p.name == name]

    def summary(self) -> dict[str, float]:
        """All latest gauge values + all counters."""
        return {**self._gauges, **self._counters}

    def to_json(self) -> str:
        return json.dumps({
            "gauges":   self._gauges,
            "counters": self._counters,
            "series":   [asdict(p) for p in self._points],
        }, indent=2)

    def to_csv(self) -> str:
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["tick", "name", "value"])
        for p in self._points:
            writer.writerow([p.tick, p.name, round(p.value, 6)])
        return buf.getvalue()

    def export_json(self, path: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json())
        return str(p)

    def export_csv(self, path: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_csv())
        return str(p)


@dataclass
class PerformanceMetrics:
    """
    Aggregates latency, throughput, and reliability metrics.
    """
    latencies:  list[float] = field(default_factory=list)
    throughput: list[float] = field(default_factory=list)

    def record_latency(self, ms: float) -> None:
        self.latencies.append(ms)

    def record_throughput(self, tasks_per_tick: float) -> None:
        self.throughput.append(tasks_per_tick)

    @property
    def mean_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.95)]

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.99)]

    @property
    def mean_throughput(self) -> float:
        return statistics.mean(self.throughput) if self.throughput else 0.0

    def summary(self) -> dict:
        return {
            "mean_latency_ms": round(self.mean_latency, 2),
            "p95_latency_ms":  round(self.p95_latency, 2),
            "p99_latency_ms":  round(self.p99_latency, 2),
            "mean_throughput": round(self.mean_throughput, 2),
        }
