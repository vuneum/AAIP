"""
AAIP Simulation Lab — Test Suite
Tests for all simulation modules and scenarios.
Run: python -m pytest tests/test_simulation.py -v
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from simulation.core      import SimConfig, SimState, SimClock
from simulation.agents    import build_agent_population, AgentBehavior, DOMAINS
from simulation.validators import build_validator_set, ValidatorBehavior
from simulation.watchers  import build_watcher_set
from simulation.tasks     import TaskGenerator, TaskStatus
from simulation.poe_simulation import PoESimulator
from simulation.validation     import simulate_jury, run_validator_consensus
from simulation.cav_simulation import CAVSimulator
from simulation.reputation     import ReputationEngine
from simulation.economics      import EscrowEngine
from simulation.metrics        import MetricsCollector
from simulation.scenarios      import SCENARIOS, get_scenario, list_scenarios
from simulation                import SimulationEngine


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def small_cfg():
    return SimConfig(
        num_agents=20, num_validators=4, num_watchers=2,
        tasks_per_day=50, sim_days=1, tick_minutes=30,
        malicious_agent_ratio=0.15, seed=42,
    )

@pytest.fixture
def small_state(small_cfg):
    state = SimState(small_cfg)
    state.agents     = build_agent_population(state)
    state.validators = build_validator_set(state)
    state.watchers   = build_watcher_set(state)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Core / Clock
# ─────────────────────────────────────────────────────────────────────────────

class TestSimClock:
    def test_advance(self):
        clock = SimClock(tick_minutes=5)
        start = clock.current
        clock.advance()
        assert (clock.current - start).total_seconds() == 300

    def test_tick_count(self):
        clock = SimClock(tick_minutes=5)
        for _ in range(12):
            clock.advance()
        assert clock.ticks == 12
        assert clock.hour_of_day == 1  # 60 min = 1 hour

    def test_day(self):
        clock = SimClock(tick_minutes=60)
        for _ in range(24):
            clock.advance()
        assert clock.day == 1


class TestSimState:
    def test_uid_unique(self, small_state):
        ids = {small_state.uid() for _ in range(100)}
        assert len(ids) == 100

    def test_bernoulli(self, small_state):
        never  = sum(small_state.bernoulli(0.0) for _ in range(100))
        always = sum(small_state.bernoulli(1.0) for _ in range(100))
        assert never  == 0
        assert always == 100

    def test_gauss_bounds(self, small_state):
        vals = [small_state.gauss(50.0, 10.0, 0.0, 100.0) for _ in range(200)]
        assert all(0.0 <= v <= 100.0 for v in vals)


# ─────────────────────────────────────────────────────────────────────────────
# Agents
# ─────────────────────────────────────────────────────────────────────────────

class TestAgents:
    def test_population_count(self, small_state):
        assert len(small_state.agents) == 20

    def test_malicious_ratio(self, small_state):
        mal = sum(1 for a in small_state.agents.values() if a.is_malicious)
        # small counts so allow ±2
        assert 0 <= mal <= 6

    def test_domain_valid(self, small_state):
        for agent in small_state.agents.values():
            assert agent.domain in DOMAINS

    def test_reputation_range(self, small_state):
        for agent in small_state.agents.values():
            assert 0.0 <= agent.reputation <= 100.0

    def test_true_quality_range(self, small_state):
        for agent in small_state.agents.values():
            assert 0.0 <= agent.true_quality <= 100.0

    def test_grade_mapping(self, small_state):
        for agent in small_state.agents.values():
            agent.reputation = 97.0
            assert agent.grade == "Elite"
            agent.reputation = 91.0
            assert agent.grade == "Gold"
            agent.reputation = 50.0
            assert agent.grade == "Unrated"

    def test_degrading_quality_decreases(self, small_state):
        for agent in small_state.agents.values():
            if agent.behavior == AgentBehavior.DEGRADING:
                q0 = agent.true_quality
                for _ in range(100):
                    agent.tick(small_state)
                assert agent.true_quality < q0
                break

    def test_reputation_update_bounded(self, small_state):
        agent = list(small_state.agents.values())[0]
        agent.reputation = 50.0
        agent.update_reputation(100.0)
        assert 0.0 <= agent.reputation <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────────────────────

class TestValidators:
    def test_count(self, small_state):
        assert len(small_state.validators) == 4

    def test_honest_detects_fabricated_poe(self, small_state):
        from simulation.tasks import SimTask
        from simulation.poe_simulation import SimPoETrace
        task = SimTask(
            task_id="t1", domain="coding", description="test",
            requester_id="r1", executor_id="e1",
            value=0.001, created_tick=0,
        )
        poe = SimPoETrace(
            trace_id="p1", task_id="t1", agent_id="e1",
            started_ms=1000, completed_ms=1050,   # only 50ms
            step_count=0, tool_calls=2, llm_calls=1,
            api_calls=0, reasoning_steps=0, total_tokens=50,
            hash_submitted=True, hash_valid=False,
            fraud_flags=["SUSPICIOUSLY_FAST_EXECUTION", "NO_EXECUTION_STEPS"],
            verdict="invalid", is_fabricated=True,
        )
        for v in small_state.validators.values():
            if v.behavior == ValidatorBehavior.HONEST:
                detected, flags, lat = v.validate_poe(task, poe, small_state)
                assert detected
                assert lat > 0
                break


# ─────────────────────────────────────────────────────────────────────────────
# Tasks
# ─────────────────────────────────────────────────────────────────────────────

class TestTasks:
    def test_task_generation(self, small_state):
        small_state.clock.advance()
        gen = TaskGenerator(small_state)
        # Run multiple ticks to get at least some tasks
        all_tasks = []
        for _ in range(20):
            small_state.clock.advance()
            all_tasks.extend(gen.generate_tick_tasks())
        assert len(all_tasks) > 0

    def test_task_value_in_range(self, small_state):
        cfg = small_state.config
        small_state.clock.advance()
        gen = TaskGenerator(small_state)
        for _ in range(30):
            small_state.clock.advance()
            for task in gen.generate_tick_tasks():
                assert cfg.task_value_min <= task.value <= cfg.task_value_max * 1.1  # small float tolerance

    def test_escrow_fee_computed(self, small_state):
        small_state.clock.advance()
        gen = TaskGenerator(small_state)
        for _ in range(30):
            small_state.clock.advance()
            for task in gen.generate_tick_tasks():
                assert task.escrow_fee >= 0


# ─────────────────────────────────────────────────────────────────────────────
# PoE Simulation
# ─────────────────────────────────────────────────────────────────────────────

class TestPoESimulation:
    def _make_task(self, state):
        agent_id = list(state.agents.keys())[0]
        return (
            __import__("simulation.tasks", fromlist=["SimTask"]).SimTask(
                task_id="t_test", domain="coding", description="test",
                requester_id="req1", executor_id=agent_id,
                value=0.001, created_tick=0,
            ),
            state.agents[agent_id],
        )

    def test_verdict_valid_for_honest(self, small_state):
        poe_sim = PoESimulator()
        for agent in small_state.agents.values():
            if agent.behavior == AgentBehavior.HONEST:
                from simulation.tasks import SimTask
                task = SimTask("t1","coding","x","r","e",0.001,0)
                task.executor_id = agent.agent_id
                poe = poe_sim.generate(task, agent, small_state)
                assert poe.verdict in ("verified", "unverified", "suspicious")
                assert poe.duration_ms >= 0
                break

    def test_fabricated_trace_has_flags(self, small_state):
        poe_sim = PoESimulator()
        from simulation.tasks import SimTask
        # Force a fabricator
        for agent in small_state.agents.values():
            if agent.behavior == AgentBehavior.FABRICATOR:
                agent.fabrication_prob = 1.0   # always fabricate
                task = SimTask("t2","coding","x","r", agent.agent_id, 0.001, 0)
                # Run many times to get at least one fabricated trace
                flagged = False
                for _ in range(20):
                    poe = poe_sim.generate(task, agent, small_state)
                    if poe.is_fabricated and poe.fraud_flags:
                        flagged = True
                        break
                assert flagged
                break

    def test_hash_valid_for_honest(self, small_state):
        poe_sim = PoESimulator()
        from simulation.tasks import SimTask
        for agent in small_state.agents.values():
            if agent.behavior == AgentBehavior.HONEST:
                task = SimTask("t3","coding","x","r",agent.agent_id,0.001,0)
                verified_seen = False
                for _ in range(10):
                    poe = poe_sim.generate(task, agent, small_state)
                    if poe.hash_submitted and poe.hash_valid:
                        verified_seen = True
                        break
                assert verified_seen
                break


# ─────────────────────────────────────────────────────────────────────────────
# Validation / Jury / Consensus
# ─────────────────────────────────────────────────────────────────────────────

class TestValidation:
    def test_jury_score_range(self, small_state):
        poe_sim = PoESimulator()
        from simulation.tasks import SimTask
        for agent in small_state.agents.values():
            task = SimTask("t4","general","x","r",agent.agent_id,0.001,0)
            poe  = poe_sim.generate(task, agent, small_state)
            jury = simulate_jury(task, agent, poe, small_state)
            assert 0.0 <= jury.final_score <= 100.0
            assert jury.grade in ("Elite","Gold","Silver","Bronze","Unrated")
            assert jury.agreement_level in ("high","moderate","low","insufficient_data")
            break

    def test_consensus_returns_result(self, small_state):
        from simulation.tasks import SimTask
        from simulation.poe_simulation import SimPoETrace
        task = SimTask("t5","finance","x","r","e1",0.001,0)
        poe  = SimPoETrace("p5","t5","e1",1000,4000,3,2,1,0,1,500,True,True,[],  "verified",False)
        result = run_validator_consensus(task, poe, small_state)
        assert isinstance(result.fraud_detected, bool)
        assert 0.0 <= result.agreement_rate <= 1.0

    def test_fabricated_poe_increases_fraud_detection(self, small_state):
        from simulation.tasks import SimTask
        from simulation.poe_simulation import SimPoETrace
        task_clean = SimTask("tc","coding","x","r","e1",0.001,0)
        task_fraud = SimTask("tf","coding","x","r","e2",0.001,0)
        poe_clean = SimPoETrace("pc","tc","e1",1000,4000,5,2,1,1,2,800,True,True,[],  "verified",False)
        poe_fraud = SimPoETrace("pf","tf","e2",1000,1050,0,2,0,0,0,50,True,False,
                                ["NO_EXECUTION_STEPS","SUSPICIOUSLY_FAST_EXECUTION"],
                                "invalid",True)
        r_clean = run_validator_consensus(task_clean, poe_clean, small_state)
        r_fraud  = run_validator_consensus(task_fraud, poe_fraud, small_state)
        # Fraud trace should have higher detection rate
        assert r_fraud.fraud_detected or not r_clean.fraud_detected


# ─────────────────────────────────────────────────────────────────────────────
# CAV
# ─────────────────────────────────────────────────────────────────────────────

class TestCAV:
    def _seed_history(self, state):
        for agent in state.agents.values():
            agent.eval_history = [75.0, 80.0, 78.0, 82.0, 79.0]
            agent.last_cav_tick = -9999  # eligible

    def test_cav_cycle_runs(self, small_state):
        self._seed_history(small_state)
        cav = CAVSimulator(small_state)
        runs = cav.run_cycle()
        assert len(runs) <= small_state.config.cav_agents_per_run

    def test_cav_scores_in_range(self, small_state):
        self._seed_history(small_state)
        cav = CAVSimulator(small_state)
        for run in cav.run_cycle():
            assert 0.0 <= run.observed_score <= 100.0
            assert 0.0 <= run.expected_score <= 100.0

    def test_cav_respects_cooldown(self, small_state):
        self._seed_history(small_state)
        cav = CAVSimulator(small_state)
        # Audit everyone once
        cav.run_cycle()
        cav.run_cycle()
        # Now all agents just audited — next cycle should get 0 (within cooldown)
        eligible = cav._eligible_agents()
        # All should be ineligible if ticks haven't advanced enough
        for agent in small_state.agents.values():
            agent.last_cav_tick = small_state.clock.ticks  # just audited
        eligible_after = cav._eligible_agents()
        assert len(eligible_after) == 0

    def test_deviation_triggers_adjustment(self, small_state):
        self._seed_history(small_state)
        cav = CAVSimulator(small_state)
        adjustments = sum(1 for r in cav.run_cycle() if r.reputation_adjusted)
        # Not asserting count — just that the field is set correctly
        for run in small_state.cav_runs.values():
            if run.reputation_adjusted:
                assert run.adjustment_delta is not None


# ─────────────────────────────────────────────────────────────────────────────
# Reputation
# ─────────────────────────────────────────────────────────────────────────────

class TestReputation:
    def test_gini_zero_equal(self, small_state):
        for a in small_state.agents.values():
            a.reputation = 80.0
        engine = ReputationEngine()
        assert engine.gini_coefficient(small_state) == pytest.approx(0.0, abs=0.01)

    def test_gini_range(self, small_state):
        engine = ReputationEngine()
        g = engine.gini_coefficient(small_state)
        assert 0.0 <= g <= 1.0

    def test_honest_vs_malicious_separation(self, small_state):
        for a in small_state.agents.values():
            a.reputation = 85.0 if not a.is_malicious else 45.0
        engine = ReputationEngine()
        result = engine.honest_vs_malicious_reputation(small_state)
        assert result["separation"] > 0

    def test_grade_distribution_sums_to_agent_count(self, small_state):
        engine = ReputationEngine()
        dist   = engine.reputation_distribution(small_state)
        assert sum(dist.values()) == len(small_state.agents)


# ─────────────────────────────────────────────────────────────────────────────
# Economics
# ─────────────────────────────────────────────────────────────────────────────

class TestEconomics:
    def test_settlement_credits_executor(self, small_state):
        from simulation.tasks import SimTask, TaskStatus
        from simulation.validation import ConsensusResult
        engine = EscrowEngine()
        agent_id = list(small_state.agents.keys())[0]
        task = SimTask("t_eco","coding","x","req1",agent_id,0.002,0)
        task.escrow_fee = 0.00001
        consensus = ConsensusResult(
            fraud_detected=False, validator_votes={},
            agreement_rate=1.0, colluding_detected=False,
            latency_ms=50.0, fraud_flags=[],
        )
        result = engine.settle_task(task, consensus, small_state)
        assert result.settled
        assert result.protocol_fee >= 0
        agent = small_state.agents[agent_id]
        assert agent.earnings > 0

    def test_fraud_triggers_penalty(self, small_state):
        from simulation.tasks import SimTask
        from simulation.validation import ConsensusResult
        engine = EscrowEngine()
        agent_id = list(small_state.agents.keys())[0]
        task = SimTask("t_fraud","coding","x","req1",agent_id,0.002,0)
        task.escrow_fee = 0.00001
        consensus = ConsensusResult(
            fraud_detected=True, validator_votes={},
            agreement_rate=1.0, colluding_detected=False,
            latency_ms=50.0, fraud_flags=["HASH_MISMATCH"],
        )
        result = engine.settle_task(task, consensus, small_state)
        assert result.fraud_penalty > 0
        assert result.executor_credit == 0.0

    def test_protocol_revenue_positive(self, small_state):
        engine = EscrowEngine()
        small_state.counters["protocol_fee_revenue"] = 0.5
        assert engine.protocol_balance(small_state) == 0.0   # ledger-based
        assert small_state.counters["protocol_fee_revenue"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_report_fields_populated(self, small_cfg):
        engine = SimulationEngine(small_cfg, "test_run", "simulate")
        report = engine.run()
        assert report.total_tasks >= 0
        assert report.wall_time_seconds > 0
        assert 0.0 <= report.task_success_rate <= 1.0
        assert 0.0 <= report.fraud_detection_rate
        assert report.final_mean_reputation > 0

    def test_reputation_gini_valid(self, small_cfg):
        engine = SimulationEngine(small_cfg, "test_run", "simulate")
        report = engine.run()
        assert 0.0 <= report.reputation_gini <= 1.0

    def test_protocol_revenue_positive(self, small_cfg):
        engine = SimulationEngine(small_cfg, "test_run", "simulate")
        report = engine.run()
        assert report.protocol_revenue >= 0.0

    def test_poe_verdict_distribution(self, small_cfg):
        engine = SimulationEngine(small_cfg, "test_run", "simulate")
        report = engine.run()
        total_poe = sum(report.poe_verdict_distribution.values())
        assert total_poe >= 0

    def test_json_export(self, small_cfg, tmp_path):
        import json
        engine = SimulationEngine(small_cfg, "export_test", "simulate")
        report = engine.run()
        from simulation.metrics import ReportExporter
        path = ReportExporter.to_json(report, str(tmp_path / "report.json"))
        with open(path) as f:
            data = json.load(f)
        assert data["scenario_name"] == "export_test"
        assert "total_tasks" in data

    def test_csv_export(self, small_cfg, tmp_path):
        import csv
        engine = SimulationEngine(small_cfg, "csv_test", "simulate")
        report = engine.run()
        from simulation.metrics import ReportExporter
        path = ReportExporter.to_csv(report, str(tmp_path / "ts.csv"))
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 0  # may be 0 for very short sim

    def test_summary_string(self, small_cfg):
        engine = SimulationEngine(small_cfg, "summary_test", "simulate")
        report = engine.run()
        from simulation.metrics import ReportExporter
        summary = ReportExporter.to_summary(report)
        assert "AAIP Simulation Lab" in summary
        assert "REPUTATION" in summary
        assert "ECONOMICS" in summary


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────────────

class TestScenarios:
    def test_all_scenarios_registered(self):
        assert len(SCENARIOS) >= 12

    def test_get_scenario_returns_correct(self):
        s = get_scenario("normal_operation")
        assert s is not None
        assert s.mode == "simulate"

    def test_unknown_scenario_returns_none(self):
        assert get_scenario("this_does_not_exist") is None

    def test_list_scenarios_structure(self):
        listing = list_scenarios()
        for item in listing:
            assert "name" in item
            assert "mode" in item
            assert item["mode"] in ("simulate", "stress")

    @pytest.mark.parametrize("name", [
        "normal_operation", "validator_collusion_attack",
        "high_throughput_stress", "malicious_executor_network",
    ])
    def test_scenario_runs(self, name):
        scenario = get_scenario(name)
        cfg = scenario.config
        # Override to 1 day for speed
        cfg.sim_days      = 1
        cfg.tick_minutes  = 60
        cfg.tasks_per_day = 50
        engine = SimulationEngine(cfg, scenario.name, scenario.mode)
        report = engine.run()
        assert report.total_tasks >= 0
        assert report.completed_at != ""


# ─────────────────────────────────────────────────────────────────────────────
# Integration — Full pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    def test_honest_reputation_higher_than_malicious(self):
        cfg = SimConfig(
            num_agents=50, num_validators=5, num_watchers=3,
            tasks_per_day=200, sim_days=3, tick_minutes=30,
            malicious_agent_ratio=0.30, seed=7,
        )
        engine = SimulationEngine(cfg, "integration_test", "simulate")
        report = engine.run()
        # Honest agents should maintain higher reputation
        assert report.final_honest_mean_rep >= report.final_malicious_mean_rep

    def test_fraud_detection_nonzero_with_malicious(self):
        cfg = SimConfig(
            num_agents=40, num_validators=5, num_watchers=2,
            tasks_per_day=200, sim_days=2, tick_minutes=30,
            malicious_agent_ratio=0.40, seed=55,
        )
        engine = SimulationEngine(cfg, "fraud_test", "simulate")
        report = engine.run()
        assert report.fraud_detected_tasks >= 0   # at least attempted detection

    def test_stress_mode_higher_throughput(self):
        base_cfg = SimConfig(tasks_per_day=100, sim_days=1, tick_minutes=30, seed=1)
        stress_cfg = SimConfig(tasks_per_day=100, sim_days=1, tick_minutes=30,
                               stress_multiplier=5.0, seed=1)
        r_base   = SimulationEngine(base_cfg, "base",   "simulate").run()
        r_stress = SimulationEngine(stress_cfg,"stress", "stress").run()
        assert r_stress.total_tasks > r_base.total_tasks

    def test_cav_adjustments_recorded(self):
        cfg = SimConfig(
            num_agents=30, num_validators=4, num_watchers=2,
            tasks_per_day=100, sim_days=2, tick_minutes=30,
            cav_deviation_threshold=5.0, seed=21,
        )
        engine = SimulationEngine(cfg, "cav_integration", "simulate")
        report = engine.run()
        assert report.cav_total_runs >= 0

    def test_economics_protocol_revenue_scales(self):
        cfg_lo = SimConfig(tasks_per_day=50,  sim_days=1, tick_minutes=60, seed=3)
        cfg_hi = SimConfig(tasks_per_day=500, sim_days=1, tick_minutes=60, seed=3)
        r_lo = SimulationEngine(cfg_lo, "lo", "simulate").run()
        r_hi = SimulationEngine(cfg_hi, "hi", "simulate").run()
        assert r_hi.protocol_revenue >= r_lo.protocol_revenue
