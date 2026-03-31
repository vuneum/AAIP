"""
AAIP Simulation Lab — Metrics
Time-series collection, aggregation, and export to JSON/CSV/report.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .core import SimState


# ─────────────────────────────────────────────────────────────────────────────
# Tick Snapshot
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TickSnapshot:
    tick:                      int
    sim_time:                  str
    tasks_created:             int   = 0
    tasks_completed:           int   = 0
    tasks_fraud_detected:      int   = 0
    tasks_disputed:            int   = 0
    poe_verified:              int   = 0
    poe_suspicious:            int   = 0
    poe_invalid:               int   = 0
    cav_runs:                  int   = 0
    cav_failures:              int   = 0
    mean_reputation:           float = 0.0
    mean_honest_reputation:    float = 0.0
    mean_malicious_reputation: float = 0.0
    reputation_gini:           float = 0.0
    validator_consensus_rate:  float = 0.0
    protocol_fee_tick:         float = 0.0
    avg_validation_latency_ms: float = 0.0
    active_agents:             int   = 0
    validator_online_rate:     float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Final Report
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulationReport:
    scenario_name:            str
    mode:                     str   # simulate|stress
    config_summary:           dict  = field(default_factory=dict)

    # Task outcomes
    total_tasks:              int   = 0
    completed_tasks:          int   = 0
    fraud_detected_tasks:     int   = 0
    disputed_tasks:           int   = 0
    task_success_rate:        float = 0.0
    fraud_detection_rate:     float = 0.0
    false_negative_rate:      float = 0.0   # fraud that slipped through

    # Performance
    avg_validation_latency_ms: float = 0.0
    p95_validation_latency_ms: float = 0.0
    peak_throughput_tpt:       float = 0.0  # tasks per tick
    system_throughput_tpd:     float = 0.0  # tasks per day

    # Reputation
    final_mean_reputation:     float = 0.0
    final_honest_mean_rep:     float = 0.0
    final_malicious_mean_rep:  float = 0.0
    reputation_gini:           float = 0.0
    reputation_separation:     float = 0.0
    grade_distribution:        dict  = field(default_factory=dict)

    # Economics
    total_value_settled:       float = 0.0
    protocol_revenue:          float = 0.0
    total_fraud_penalties:     float = 0.0
    total_validator_rewards:   float = 0.0
    protocol_revenue_rate:     float = 0.0

    # CAV
    cav_total_runs:            int   = 0
    cav_failure_rate:          float = 0.0
    cav_adjustment_rate:       float = 0.0

    # Validators
    validator_consensus_rate:  float = 0.0
    validator_fraud_proofs:    int   = 0
    colluding_validators_caught: int = 0

    # Security
    fraud_true_positives:      int   = 0
    fraud_false_negatives:     int   = 0
    fraud_false_positives:     int   = 0
    poe_verdict_distribution:  dict  = field(default_factory=dict)

    # Time series
    tick_snapshots:            list  = field(default_factory=list)

    # Stress-specific
    stress_peak_latency_ms:    float = 0.0
    stress_failure_rate:       float = 0.0
    stress_bottleneck:         str   = ""

    wall_time_seconds:         float = 0.0
    completed_at:              str   = ""


# ─────────────────────────────────────────────────────────────────────────────
# Metrics Collector
# ─────────────────────────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Attached to a SimState; records tick-level snapshots and
    computes final aggregated metrics at the end of the simulation.
    """

    def __init__(self, state: SimState):
        self.state     = state
        self.snapshots: list[TickSnapshot] = []
        self._latencies: list[float] = []
        self._tick_task_counts: list[int] = []

    def record_validation_latency(self, latency_ms: float) -> None:
        self._latencies.append(latency_ms)

    def capture_tick(
        self,
        tasks_created:  int,
        tasks_completed:int,
        fraud_detected: int,
        disputed:       int,
        poe_counts:     dict,
        cav_runs:       int,
        cav_failures:   int,
        rep_engine,
        tick_fee:       float,
        avg_latency:    float,
    ) -> TickSnapshot:
        state = self.state
        sep   = rep_engine.honest_vs_malicious_reputation(state)

        snap = TickSnapshot(
            tick                      = state.clock.ticks,
            sim_time                  = str(state.clock),
            tasks_created             = tasks_created,
            tasks_completed           = tasks_completed,
            tasks_fraud_detected      = fraud_detected,
            tasks_disputed            = disputed,
            poe_verified              = poe_counts.get("verified", 0),
            poe_suspicious            = poe_counts.get("suspicious", 0),
            poe_invalid               = poe_counts.get("invalid", 0),
            cav_runs                  = cav_runs,
            cav_failures              = cav_failures,
            mean_reputation           = rep_engine.mean_reputation(state),
            mean_honest_reputation    = sep["honest_mean"],
            mean_malicious_reputation = sep["malicious_mean"],
            reputation_gini           = rep_engine.gini_coefficient(state),
            protocol_fee_tick         = tick_fee,
            avg_validation_latency_ms = avg_latency,
            active_agents             = sum(1 for a in state.agents.values() if a.is_active),
            validator_online_rate     = (
                sum(1 for v in state.validators.values() if v.is_online) /
                max(1, len(state.validators))
            ),
        )
        self.snapshots.append(snap)
        self._tick_task_counts.append(tasks_created)
        return snap

    def build_report(
        self,
        scenario_name:  str,
        mode:           str,
        rep_engine,
        escrow_engine,
        wall_seconds:   float,
    ) -> SimulationReport:
        state = self.state
        c     = state.counters
        cfg   = state.config

        total_tasks       = int(c.get("tasks_created",        0))
        completed         = int(c.get("tasks_completed",      0))
        fraud_detected    = int(c.get("fraud_detected",       0))
        total_fraud       = int(c.get("total_actual_fraud",   0))
        disputed          = int(c.get("disputes_raised",      0))

        false_neg = max(0, total_fraud - fraud_detected)
        fraud_dr  = (fraud_detected / max(1, total_fraud)) if total_fraud > 0 else 0.0
        fnr       = (false_neg      / max(1, total_fraud)) if total_fraud > 0 else 0.0

        # Latency percentiles
        lats = sorted(self._latencies)
        avg_lat = statistics.mean(lats) if lats else 0.0
        p95_lat = lats[int(len(lats) * 0.95)] if lats else 0.0

        # Throughput
        peak_tpt = max(self._tick_task_counts) if self._tick_task_counts else 0
        ticks_per_day = (24 * 60) / cfg.tick_minutes
        tpd = total_tasks / max(1, cfg.sim_days)

        # PoE distribution across all tasks
        poe_dist: dict[str, int] = {"verified": 0, "suspicious": 0, "invalid": 0, "unverified": 0}
        for snap in self.snapshots:
            poe_dist["verified"]   += snap.poe_verified
            poe_dist["suspicious"] += snap.poe_suspicious
            poe_dist["invalid"]    += snap.poe_invalid

        sep = rep_engine.honest_vs_malicious_reputation(state)

        cav_runs       = int(c.get("cav_total_runs",           0))
        cav_failures   = int(c.get("cav_failures",             0))
        cav_adjustments= int(c.get("cav_reputation_adjustments",0))

        # CAV bottleneck hint for stress mode
        bottleneck = ""
        if avg_lat > 200:
            bottleneck = "validation_latency"
        elif (completed / max(1, total_tasks)) < 0.8:
            bottleneck = "task_throughput"
        elif cav_failures / max(1, cav_runs) > 0.3:
            bottleneck = "cav_audit_capacity"

        return SimulationReport(
            scenario_name             = scenario_name,
            mode                      = mode,
            config_summary            = {
                "agents":           cfg.num_agents,
                "validators":       cfg.num_validators,
                "watchers":         cfg.num_watchers,
                "malicious_ratio":  cfg.malicious_agent_ratio,
                "tasks_per_day":    cfg.tasks_per_day,
                "sim_days":         cfg.sim_days,
                "stress_multiplier":cfg.stress_multiplier,
            },
            total_tasks               = total_tasks,
            completed_tasks           = completed,
            fraud_detected_tasks      = fraud_detected,
            disputed_tasks            = disputed,
            task_success_rate         = round(completed / max(1, total_tasks), 4),
            fraud_detection_rate      = round(fraud_dr, 4),
            false_negative_rate       = round(fnr, 4),
            avg_validation_latency_ms = round(avg_lat, 2),
            p95_validation_latency_ms = round(p95_lat, 2),
            peak_throughput_tpt       = float(peak_tpt),
            system_throughput_tpd     = round(tpd, 1),
            final_mean_reputation     = rep_engine.mean_reputation(state),
            final_honest_mean_rep     = sep["honest_mean"],
            final_malicious_mean_rep  = sep["malicious_mean"],
            reputation_gini           = rep_engine.gini_coefficient(state),
            reputation_separation     = sep["separation"],
            grade_distribution        = rep_engine.reputation_distribution(state),
            total_value_settled       = round(c.get("total_escrow_charged",   0.0), 4),
            protocol_revenue          = round(c.get("protocol_fee_revenue",   0.0), 6),
            total_fraud_penalties     = round(c.get("fraud_penalties_collected",0.0),6),
            total_validator_rewards   = round(c.get("validator_rewards_paid", 0.0), 6),
            protocol_revenue_rate     = round(
                c.get("protocol_fee_revenue",0.0) / max(0.0001, c.get("total_escrow_charged",0.001)), 4
            ),
            cav_total_runs            = cav_runs,
            cav_failure_rate          = round(cav_failures / max(1, cav_runs), 4),
            cav_adjustment_rate       = round(cav_adjustments / max(1, cav_runs), 4),
            validator_consensus_rate  = round(c.get("consensus_rate_sum",0.0) / max(1, completed), 4),
            validator_fraud_proofs    = int(c.get("watcher_fraud_proofs", 0)),
            poe_verdict_distribution  = poe_dist,
            fraud_true_positives      = fraud_detected,
            fraud_false_negatives     = false_neg,
            tick_snapshots            = [asdict(s) for s in self.snapshots],
            stress_peak_latency_ms    = round(max(self._latencies) if self._latencies else 0.0, 2),
            stress_failure_rate       = round(1.0 - completed / max(1, total_tasks), 4),
            stress_bottleneck         = bottleneck,
            wall_time_seconds         = round(wall_seconds, 2),
            completed_at              = datetime.utcnow().isoformat(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Exporters
# ─────────────────────────────────────────────────────────────────────────────

class ReportExporter:

    @staticmethod
    def to_json(report: SimulationReport, path: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(report)
        with open(p, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return str(p)

    @staticmethod
    def to_csv(report: SimulationReport, path: str) -> str:
        """Write tick-level time series as CSV."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        snaps = report.tick_snapshots
        if not snaps:
            return str(p)
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=snaps[0].keys())
            writer.writeheader()
            writer.writerows(snaps)
        return str(p)

    @staticmethod
    def to_summary(report: SimulationReport) -> str:
        """Human-readable plain-text summary."""
        r = report
        sep = "─" * 60
        lines = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            f"║   AAIP Simulation Lab — {r.scenario_name:<32}║",
            f"║   Mode: {r.mode:<49}║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            f"  Completed at : {r.completed_at}",
            f"  Wall time    : {r.wall_time_seconds:.1f}s",
            "",
            sep,
            "  NETWORK CONFIGURATION",
            sep,
            f"  Agents            : {r.config_summary.get('agents')}",
            f"  Validators        : {r.config_summary.get('validators')}",
            f"  Watchers          : {r.config_summary.get('watchers')}",
            f"  Malicious ratio   : {r.config_summary.get('malicious_ratio'):.1%}",
            f"  Tasks / day       : {r.config_summary.get('tasks_per_day')}",
            f"  Sim days          : {r.config_summary.get('sim_days')}",
            f"  Stress multiplier : {r.config_summary.get('stress_multiplier')}×",
            "",
            sep,
            "  TASK OUTCOMES",
            sep,
            f"  Total tasks       : {r.total_tasks:,}",
            f"  Completed         : {r.completed_tasks:,}  ({r.task_success_rate:.1%})",
            f"  Fraud detected    : {r.fraud_detected_tasks:,}",
            f"  False negatives   : {r.fraud_false_negatives:,}",
            f"  Fraud detect rate : {r.fraud_detection_rate:.1%}",
            f"  Disputes raised   : {r.disputed_tasks:,}",
            f"  Throughput / day  : {r.system_throughput_tpd:.0f}",
            "",
            sep,
            "  PERFORMANCE",
            sep,
            f"  Avg latency       : {r.avg_validation_latency_ms:.1f} ms",
            f"  P95 latency       : {r.p95_validation_latency_ms:.1f} ms",
            f"  Peak latency      : {r.stress_peak_latency_ms:.1f} ms",
            f"  Peak throughput   : {r.peak_throughput_tpt:.0f} tasks/tick",
            *(
                [f"  ⚠  Bottleneck      : {r.stress_bottleneck}"]
                if r.stress_bottleneck else []
            ),
            "",
            sep,
            "  REPUTATION SYSTEM",
            sep,
            f"  Mean reputation   : {r.final_mean_reputation:.1f}",
            f"  Honest agents     : {r.final_honest_mean_rep:.1f}",
            f"  Malicious agents  : {r.final_malicious_mean_rep:.1f}",
            f"  Separation        : {r.reputation_separation:.1f} pts",
            f"  Gini coefficient  : {r.reputation_gini:.4f}",
            f"  Grade distribution: {_fmt_grades(r.grade_distribution)}",
            "",
            sep,
            "  ECONOMICS",
            sep,
            f"  Total settled     : {r.total_value_settled:.4f} USDC",
            f"  Protocol revenue  : {r.protocol_revenue:.6f} USDC  ({r.protocol_revenue_rate:.2%})",
            f"  Validator rewards : {r.total_validator_rewards:.6f} USDC",
            f"  Fraud penalties   : {r.total_fraud_penalties:.6f} USDC",
            "",
            sep,
            "  CAV AUDIT SYSTEM",
            sep,
            f"  Total CAV runs    : {r.cav_total_runs:,}",
            f"  CAV failure rate  : {r.cav_failure_rate:.1%}",
            f"  Adjustment rate   : {r.cav_adjustment_rate:.1%}",
            "",
            sep,
            "  SECURITY",
            sep,
            f"  PoE verified      : {r.poe_verdict_distribution.get('verified', 0):,}",
            f"  PoE suspicious    : {r.poe_verdict_distribution.get('suspicious', 0):,}",
            f"  PoE invalid       : {r.poe_verdict_distribution.get('invalid', 0):,}",
            f"  Fraud proofs      : {r.validator_fraud_proofs:,}",
            "",
        ]
        return "\n".join(lines)


def _fmt_grades(dist: dict) -> str:
    return "  ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)
