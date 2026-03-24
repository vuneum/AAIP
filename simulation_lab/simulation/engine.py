"""
AAIP Simulation Lab — Main Simulation Engine
Orchestrates the discrete-event tick loop, wiring all modules together.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .core import SimConfig, SimState
from .agents import build_agent_population
from .validators import build_validator_set
from .validators import SimValidator
from .watchers import build_watcher_set
from .tasks import TaskGenerator, SimTask
from .poe_simulation import PoESimulator
from .validation import simulate_jury, run_validator_consensus
from .cav_simulation import CAVSimulator
from .reputation import ReputationEngine
from .economics import EscrowEngine
from .metrics import MetricsCollector, SimulationReport, ReportExporter
from .tasks import TaskStatus

logger = logging.getLogger("aaip.sim.engine")


class SimulationEngine:
    """
    Main orchestrator. One call to run() executes the full simulation
    and returns a populated SimulationReport.

    Architecture:
        For each tick:
          1. Generate arriving tasks (Poisson)
          2. For each task:
             a. Agent executes → PoE trace generated
             b. Validator consensus on PoE
             c. AI jury scores output
             d. Escrow settled
             e. Reputation updated
          3. CAV cycle (every N ticks)
          4. Validators tick (failures / recovery)
          5. Capture metrics snapshot
    """

    def __init__(self, config: SimConfig, scenario_name: str = "custom", mode: str = "simulate"):
        self.config        = config
        self.scenario_name = scenario_name
        self.mode          = mode
        self.state         = SimState(config)

    def _setup(self) -> None:
        """Initialise all subsystems."""
        state = self.state
        cfg   = state.config

        logger.info("Setting up simulation: %s agents, %s validators, %s watchers",
                    cfg.num_agents, cfg.num_validators, cfg.num_watchers)

        state.agents     = build_agent_population(state)
        state.validators = build_validator_set(state)
        state.watchers   = build_watcher_set(state)

        self.task_gen   = TaskGenerator(state)
        self.poe_sim    = PoESimulator()
        self.cav_sim    = CAVSimulator(state)
        self.rep_engine = ReputationEngine()
        self.escrow     = EscrowEngine()
        self.metrics    = MetricsCollector(state)

        logger.info("Population: %d honest, %d malicious agents",
                    sum(1 for a in state.agents.values() if not a.is_malicious),
                    sum(1 for a in state.agents.values() if a.is_malicious))

    def run(self) -> SimulationReport:
        self._setup()
        state      = self.state
        cfg        = state.config
        total_ticks = cfg.total_ticks()
        wall_start  = time.perf_counter()

        logger.info("Starting simulation: %d ticks (%d days × %d ticks/day)",
                    total_ticks, cfg.sim_days,
                    int((24 * 60) / cfg.tick_minutes))

        try:
            for tick_num in range(total_ticks):
                self._tick()

                if cfg.verbose and tick_num % 100 == 0:
                    self._log_progress(tick_num, total_ticks)

        except KeyboardInterrupt:
            logger.info("Simulation interrupted at tick %d", state.clock.ticks)

        wall_elapsed = time.perf_counter() - wall_start
        report = self.metrics.build_report(
            scenario_name = self.scenario_name,
            mode          = self.mode,
            rep_engine    = self.rep_engine,
            escrow_engine = self.escrow,
            wall_seconds  = wall_elapsed,
        )
        logger.info("Simulation complete. %.1fs wall time, %d tasks processed.",
                    wall_elapsed, report.total_tasks)
        return report

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        state  = self.state
        clock  = state.clock
        clock.advance()

        # Tick all agents (degradation etc.)
        for agent in state.agents.values():
            agent.tick(state)

        # Tick all validators (failures/recovery)
        for validator in state.validators.values():
            validator.tick(state)

        # 1. Generate tasks
        tasks = self.task_gen.generate_tick_tasks()
        state.inc("tasks_created", len(tasks))

        # 2. Process each task through the full pipeline
        tick_fraud = 0
        tick_completed = 0
        tick_disputed  = 0
        poe_counts: dict[str, int] = {"verified": 0, "suspicious": 0,
                                       "invalid": 0, "unverified": 0}
        tick_latencies: list[float] = []
        tick_fee = 0.0

        for task in tasks:
            state.tasks[task.task_id] = task
            result = self._process_task(task)
            if result is None:
                continue
            poe_verdict, latency_ms, fraud, fee, disputed = result
            poe_counts[poe_verdict] = poe_counts.get(poe_verdict, 0) + 1
            tick_latencies.append(latency_ms)
            tick_fee += fee
            if fraud:
                tick_fraud += 1
            tick_completed += 1
            if disputed:
                tick_disputed += 1

        state.inc("tasks_completed", tick_completed)
        state.inc("fraud_detected",  tick_fraud)

        # 3. CAV cycle
        cav_runs = 0
        cav_fails = 0
        if self.cav_sim.should_run_this_tick() or self.mode == "stress":
            runs = self.cav_sim.run_cycle()
            cav_runs = len(runs)
            cav_fails = sum(1 for r in runs if r.result == "failed")

        avg_latency = (sum(tick_latencies) / len(tick_latencies)) if tick_latencies else 0.0
        for lat in tick_latencies:
            self.metrics.record_validation_latency(lat)

        # 4. Snapshot (every 6 ticks = 30 sim-minutes to keep output manageable)
        if clock.ticks % 6 == 0:
            self.metrics.capture_tick(
                tasks_created   = len(tasks),
                tasks_completed = tick_completed,
                fraud_detected  = tick_fraud,
                disputed        = tick_disputed,
                poe_counts      = poe_counts,
                cav_runs        = cav_runs,
                cav_failures    = cav_fails,
                rep_engine      = self.rep_engine,
                tick_fee        = tick_fee,
                avg_latency     = avg_latency,
            )

    def _process_task(self, task: SimTask) -> Optional[tuple]:
        """
        Full pipeline for one task.
        Returns (poe_verdict, latency_ms, fraud_detected, fee, disputed) or None.
        """
        state     = self.state
        executor  = state.agents.get(task.executor_id)
        if not executor or not executor.is_active:
            task.status = TaskStatus.FAILED
            return None

        task.status = TaskStatus.EXECUTING
        task.execution_start_tick = state.clock.ticks

        # a. PoE trace generation
        poe = self.poe_sim.generate(task, executor, state)
        state.poe_records[poe.trace_id] = poe
        task.poe_verdict = poe.verdict
        task.fraud_flags = poe.fraud_flags

        # Track true fraud for detection-rate calculation
        if poe.is_fabricated:
            state.inc("total_actual_fraud")

        task.status = TaskStatus.VALIDATING

        # b. Validator consensus
        consensus = run_validator_consensus(task, poe, state)
        task.validator_votes   = consensus.validator_votes
        task.consensus_fraud   = consensus.fraud_detected

        # Accumulate consensus agreement for metrics
        state.inc("consensus_rate_sum", consensus.agreement_rate)

        # c. AI jury scoring
        task.status = TaskStatus.JURY_SCORING
        jury = simulate_jury(task, executor, poe, state)
        task.jury_score = jury.final_score

        # Combined latency: validator + jury (jury simulated as fast)
        jury_latency = state.gauss(80.0, 20.0, 20.0, 300.0)
        total_latency = consensus.latency_ms + jury_latency

        task.validation_end_tick = state.clock.ticks

        # d. Escrow settlement
        self.escrow.charge_escrow(task, executor, state)
        settlement = self.escrow.settle_task(task, consensus, state)
        task.settlement_tick = state.clock.ticks

        # e. Reputation update
        rep_update = self.rep_engine.apply_jury_result(executor, task, jury, consensus, state)
        task.reputation_delta = rep_update.delta

        fraud_detected = consensus.fraud_detected or (poe.verdict in ("suspicious", "invalid"))
        return (poe.verdict, total_latency, fraud_detected, settlement.protocol_fee, settlement.disputed)

    def _log_progress(self, tick: int, total: int) -> None:
        pct = tick / total * 100
        state = self.state
        c = state.counters
        logger.info(
            "[%5.1f%%] tick=%d  tasks=%d  fraud_det=%d  mean_rep=%.1f",
            pct, tick,
            int(c.get("tasks_created", 0)),
            int(c.get("fraud_detected", 0)),
            self.rep_engine.mean_reputation(state),
        )
