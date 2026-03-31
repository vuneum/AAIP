#!/usr/bin/env python3
"""
AAIP Simulation Lab — CLI
Usage:
  aaip-lab simulate   [options]
  aaip-lab stress     [options]
  aaip-lab scenario   <name> [options]
  aaip-lab scenarios
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Allow running as script without install
sys.path.insert(0, str(Path(__file__).parent))

from simulation import SimConfig, SimulationEngine, get_scenario, list_scenarios
from simulation.metrics import ReportExporter


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level  = level,
        format = "%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
        datefmt= "%H:%M:%S",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shared simulation options
# ─────────────────────────────────────────────────────────────────────────────

def _add_sim_args(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("network")
    g.add_argument("--agents",           type=int,   default=None, metavar="N",   help="Number of agents")
    g.add_argument("--validators",       type=int,   default=None, metavar="N",   help="Number of validators")
    g.add_argument("--watchers",         type=int,   default=None, metavar="N",   help="Number of watchers")
    g.add_argument("--malicious-ratio",  type=float, default=None, metavar="0.1", help="Fraction of malicious agents (0–1)")
    g.add_argument("--mal-validator-ratio", type=float, default=None, metavar="0.0",
                   help="Fraction of malicious validators (0–1)")

    g2 = parser.add_argument_group("workload")
    g2.add_argument("--tasks",           type=int,   default=None, metavar="N",   help="Tasks per day")
    g2.add_argument("--days",            type=int,   default=None, metavar="N",   help="Simulated days")
    g2.add_argument("--stress-mult",     type=float, default=None, metavar="1.0", help="Task volume multiplier (stress mode)")
    g2.add_argument("--tick-minutes",    type=int,   default=None, metavar="5",   help="Simulated minutes per tick")

    g3 = parser.add_argument_group("protocol")
    g3.add_argument("--cav-threshold",   type=float, default=None, metavar="10.0",help="CAV deviation threshold")
    g3.add_argument("--cav-weight",      type=float, default=None, metavar="0.3", help="CAV adjustment weight")
    g3.add_argument("--dispute-prob",    type=float, default=None, metavar="0.01",help="Base dispute probability")
    g3.add_argument("--val-failure-rate",type=float, default=None, metavar="0.0", help="Validator failure probability per tick")

    g4 = parser.add_argument_group("output")
    g4.add_argument("--out",             type=str,   default="./lab_output",      help="Output directory")
    g4.add_argument("--json",            action="store_true", help="Write full JSON report")
    g4.add_argument("--csv",             action="store_true", help="Write tick-level CSV")
    g4.add_argument("--no-summary",      action="store_true", help="Suppress terminal summary")
    g4.add_argument("--seed",            type=int,   default=42,                  help="Random seed")
    g4.add_argument("--verbose",         action="store_true", help="Debug logging")


def _apply_overrides(cfg: SimConfig, args: argparse.Namespace) -> SimConfig:
    """Overlay CLI args on top of a SimConfig (from scenario or defaults)."""
    if args.agents:            cfg.num_agents              = args.agents
    if args.validators:        cfg.num_validators          = args.validators
    if args.watchers:          cfg.num_watchers            = args.watchers
    if args.malicious_ratio  is not None: cfg.malicious_agent_ratio   = args.malicious_ratio
    if args.mal_validator_ratio is not None: cfg.malicious_validator_ratio = args.mal_validator_ratio
    if args.tasks:             cfg.tasks_per_day           = args.tasks
    if args.days:              cfg.sim_days                = args.days
    if args.stress_mult  is not None: cfg.stress_multiplier = args.stress_mult
    if args.tick_minutes is not None: cfg.tick_minutes      = args.tick_minutes
    if args.cav_threshold is not None: cfg.cav_deviation_threshold = args.cav_threshold
    if args.cav_weight    is not None: cfg.cav_adjustment_weight   = args.cav_weight
    if args.dispute_prob  is not None: cfg.dispute_probability_base = args.dispute_prob
    if args.val_failure_rate is not None: cfg.validator_failure_rate = args.val_failure_rate
    cfg.seed    = args.seed
    cfg.verbose = args.verbose
    return cfg


def _run_and_output(engine: SimulationEngine, args: argparse.Namespace, label: str) -> None:
    report  = engine.run()
    out_dir = Path(args.out) / label
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_summary:
        print(ReportExporter.to_summary(report))

    if args.json or True:   # always write JSON
        p = ReportExporter.to_json(report, str(out_dir / "report.json"))
        print(f"  📄  JSON report  → {p}")

    if args.csv:
        p = ReportExporter.to_csv(report, str(out_dir / "timeseries.csv"))
        print(f"  📊  CSV timeline → {p}")


# ─────────────────────────────────────────────────────────────────────────────
# Sub-commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_simulate(args: argparse.Namespace) -> None:
    """aaip-lab simulate — run with default config, optionally overridden."""
    _setup_logging(args.verbose)
    cfg = SimConfig()
    cfg = _apply_overrides(cfg, args)
    engine = SimulationEngine(cfg, scenario_name="simulate_custom", mode="simulate")
    _run_and_output(engine, args, "simulate_custom")


def cmd_stress(args: argparse.Namespace) -> None:
    """aaip-lab stress — high-throughput run with stress defaults."""
    _setup_logging(args.verbose)
    cfg = SimConfig(
        stress_multiplier      = 5.0,
        validator_failure_rate = 0.1,
        dispute_probability_base=0.05,
        sim_days               = 3,
    )
    cfg = _apply_overrides(cfg, args)
    if args.stress_mult is None:
        cfg.stress_multiplier = max(cfg.stress_multiplier, 5.0)
    engine = SimulationEngine(cfg, scenario_name="stress_custom", mode="stress")
    _run_and_output(engine, args, "stress_custom")


def cmd_scenario(args: argparse.Namespace) -> None:
    """aaip-lab scenario <name> — run a named predefined scenario."""
    _setup_logging(args.verbose)
    scenario = get_scenario(args.name)
    if scenario is None:
        print(f"\n  ✗  Unknown scenario: '{args.name}'")
        print(f"\n  Available scenarios:")
        for s in list_scenarios():
            print(f"    {s['name']:<35}  [{s['mode']}]  {s['description'][:60]}")
        sys.exit(1)

    cfg = scenario.config
    cfg = _apply_overrides(cfg, args)
    print(f"\n  ▶  Running scenario: {scenario.name}")
    print(f"     {scenario.description}")
    print(f"     Mode: {scenario.mode}  |  Tags: {', '.join(scenario.tags)}\n")

    engine = SimulationEngine(cfg, scenario_name=scenario.name, mode=scenario.mode)
    _run_and_output(engine, args, scenario.name)


def cmd_scenarios(_args: argparse.Namespace) -> None:
    """aaip-lab scenarios — list all predefined scenarios."""
    print("\n  AAIP Simulation Lab — Available Scenarios\n")
    print(f"  {'NAME':<35} {'MODE':<10} {'TAGS':<35} DESCRIPTION")
    print("  " + "─" * 100)
    for s in list_scenarios():
        tags = ", ".join(s["tags"])
        print(f"  {s['name']:<35} {s['mode']:<10} {tags:<35} {s['description'][:50]}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Argument Parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "aaip-lab",
        description = "AAIP Simulation Lab — Protocol simulation and stress testing framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog      = """
examples:
  aaip-lab simulate --agents 200 --days 7 --malicious-ratio 0.15
  aaip-lab stress   --agents 500 --stress-mult 10 --days 3
  aaip-lab scenario normal_operation
  aaip-lab scenario validator_collusion_attack --days 14 --csv
  aaip-lab scenarios
        """,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # simulate
    p_sim = sub.add_parser("simulate", help="Run a custom simulation")
    _add_sim_args(p_sim)
    p_sim.set_defaults(func=cmd_simulate)

    # stress
    p_stress = sub.add_parser("stress", help="Run a stress test")
    _add_sim_args(p_stress)
    p_stress.set_defaults(func=cmd_stress)

    # scenario <name>
    p_scen = sub.add_parser("scenario", help="Run a named predefined scenario")
    p_scen.add_argument("name", help="Scenario name (use 'aaip-lab scenarios' to list)")
    _add_sim_args(p_scen)
    p_scen.set_defaults(func=cmd_scenario)

    # scenarios
    p_list = sub.add_parser("scenarios", help="List all available scenarios")
    p_list.add_argument("--verbose", action="store_true")
    p_list.set_defaults(func=cmd_scenarios)

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
