#!/usr/bin/env python3
"""
AAIP Simulation Lab — CLI
aaip-sim run --scenario <name> [options]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from simulation_lab.engine.simulation_engine import SimulationConfig, SimulationEngine


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_DESCRIPTIONS = {
    "baseline":    "Healthy ecosystem — establishes performance baseline",
    "collusion":   "Coordinated validator ring approves fraudulent outputs",
    "sybil":       "Attacker floods network with fake validator identities",
    "bribery":     "Executor bribes validators with off-protocol incentives",
    "adversarial": "Crafted outputs designed to fool AI judges (prompt injection, etc.)",
    "spam":        "Task flood attack overwhelms validator capacity",
    "mixed":       "Multi-vector attack: collusion + bribery + adversarial techniques",
}


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aaip-sim",
        description="AAIP Research Simulator — Adversarial protocol testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  aaip-sim run --scenario collusion
  aaip-sim run --scenario sybil --sybil-validators 200 --selection stake_weighted
  aaip-sim run --scenario bribery --bribe-ratio 3.0 --validators 60
  aaip-sim run --scenario spam --tasks 2000 --ticks 300
  aaip-sim run --scenario mixed --malicious-ratio 0.35 --out results/
  aaip-sim run --scenario adversarial --technique prompt_injection
  aaip-sim list
  aaip-sim benchmark
        """,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── run ──────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Run a simulation scenario")
    p_run.add_argument("--scenario", "-s", default="baseline",
                       choices=list(SCENARIO_DESCRIPTIONS),
                       help="Attack scenario to simulate")

    # Network
    g_net = p_run.add_argument_group("network")
    g_net.add_argument("--validators",      type=int,   default=50)
    g_net.add_argument("--agents",          type=int,   default=20)
    g_net.add_argument("--malicious-ratio", type=float, default=0.20)
    g_net.add_argument("--ticks",           type=int,   default=500)
    g_net.add_argument("--tasks",           type=int,   default=5000)

    # Attack params
    g_atk = p_run.add_argument_group("attack parameters")
    g_atk.add_argument("--collusion-rate",   type=float, default=0.30)
    g_atk.add_argument("--sybil-validators", type=int,   default=100)
    g_atk.add_argument("--selection",        default="random",
                        choices=["random", "stake_weighted", "reputation_weighted"])
    g_atk.add_argument("--bribe-ratio",      type=float, default=2.0)
    g_atk.add_argument("--technique",        default="prompt_injection",
                        choices=["prompt_injection","adversarial_format",
                                 "semantic_ambiguity","structured_hallucination",
                                 "misleading_reasoning","confidence_inflation"])
    g_atk.add_argument("--spam-count",       type=int,   default=10000)

    # Output
    g_out = p_run.add_argument_group("output")
    g_out.add_argument("--out",     default="./sim_results", help="Output directory")
    g_out.add_argument("--csv",     action="store_true",     help="Export CSV time series")
    g_out.add_argument("--seed",    type=int, default=42)
    g_out.add_argument("--verbose", action="store_true")
    p_run.set_defaults(func=cmd_run)

    # ── list ─────────────────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List available scenarios")
    p_list.set_defaults(func=cmd_list)

    # ── benchmark ────────────────────────────────────────────────────────────
    p_bench = sub.add_parser("benchmark", help="Run all scenarios and compare results")
    p_bench.add_argument("--out",  default="./benchmark_results")
    p_bench.add_argument("--ticks",type=int, default=200)
    p_bench.add_argument("--tasks",type=int, default=2000)
    p_bench.set_defaults(func=cmd_benchmark)

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    attack_params = {
        "collusion_rate":          args.collusion_rate,
        "sybil_validators":        args.sybil_validators,
        "validator_selection_method": args.selection,
        "bribe_ratio":             args.bribe_ratio,
        "technique":               args.technique,
        "spam_task_count":         args.spam_count,
    }

    cfg = SimulationConfig(
        scenario         = args.scenario,
        validators       = args.validators,
        agents           = args.agents,
        malicious_ratio  = args.malicious_ratio,
        ticks            = args.ticks,
        tasks            = args.tasks,
        tasks_per_tick   = max(1, args.tasks // args.ticks),
        seed             = args.seed,
        verbose          = args.verbose,
        attack_params    = attack_params,
    )

    print(f"\n  ▶  AAIP Simulation  ·  scenario={args.scenario}")
    print(f"     validators={args.validators}  agents={args.agents}  "
          f"malicious={args.malicious_ratio:.0%}  ticks={args.ticks}\n")

    t0     = time.perf_counter()
    engine = SimulationEngine(cfg)
    result = engine.run()
    elapsed = time.perf_counter() - t0

    _print_result(result)

    # Write output
    out_dir = Path(args.out) / args.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result.json"
    json_path.write_text(result.to_json())
    print(f"\n  📄  JSON report  → {json_path}")

    if args.csv:
        csv_path = out_dir / "metrics.csv"
        csv_path.write_text(result.to_csv_summary())
        print(f"  📊  CSV summary  → {csv_path}")


def cmd_list(_args) -> None:
    print("\n  AAIP Simulation Lab — Available Scenarios\n")
    print(f"  {'SCENARIO':<15} {'DESCRIPTION'}")
    print("  " + "─" * 70)
    for name, desc in SCENARIO_DESCRIPTIONS.items():
        print(f"  {name:<15} {desc}")
    print()


def cmd_benchmark(args: argparse.Namespace) -> None:
    print("\n  ▶  AAIP Benchmark — running all scenarios\n")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario in SCENARIO_DESCRIPTIONS:
        print(f"     Running: {scenario}...")
        cfg = SimulationConfig(
            scenario=scenario, ticks=args.ticks,
            tasks=args.tasks, tasks_per_tick=max(1, args.tasks // args.ticks),
        )
        r = SimulationEngine(cfg).run()
        results.append({
            "scenario":            r.scenario,
            "validation_accuracy": r.validation_accuracy,
            "attack_success_rate": r.attack_success_rate,
            "economic_loss":       r.economic_loss,
            "task_latency_mean":   r.task_latency_mean,
            "system_throughput":   r.system_throughput,
        })

    # Print comparison table
    print(f"\n  {'SCENARIO':<15} {'VAL.ACC':>8} {'ATK.SUCC':>9} {'ECO.LOSS':>9} {'LAT(ms)':>8} {'THPT':>6}")
    print("  " + "─" * 62)
    for r in results:
        print(f"  {r['scenario']:<15} "
              f"{r['validation_accuracy']:>8.2%} "
              f"{r['attack_success_rate']:>9.2%} "
              f"{r['economic_loss']:>9.4f} "
              f"{r['task_latency_mean']:>8.1f} "
              f"{r['system_throughput']:>6.1f}")

    summary_path = out_dir / "benchmark_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))
    print(f"\n  📄  Benchmark summary → {summary_path}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Pretty output
# ─────────────────────────────────────────────────────────────────────────────

def _print_result(result) -> None:
    sep = "─" * 56
    lines = [
        "",
        "╔════════════════════════════════════════════════════════╗",
        f"║  AAIP Simulation  ·  {result.scenario:<34}║",
        "╚════════════════════════════════════════════════════════╝",
        "",
        f"  Completed   {result.completed_at}",
        f"  Wall time   {result.wall_time_seconds:.2f}s",
        "",
        sep,
        "  CORE METRICS",
        sep,
        f"  Tasks processed        {result.total_tasks:>10,}",
        f"  Validation accuracy    {result.validation_accuracy:>10.1%}",
        f"  Attack success rate    {result.attack_success_rate:>10.1%}",
        f"  False approval rate    {result.false_approval_rate:>10.1%}",
        f"  Consensus disagreement {result.consensus_disagreement:>10.1%}",
        "",
        sep,
        "  PERFORMANCE",
        sep,
        f"  Avg latency (ms)       {result.task_latency_mean:>10.1f}",
        f"  P95 latency (ms)       {result.task_latency_p95:>10.1f}",
        f"  System throughput      {result.system_throughput:>10.1f} tasks/tick",
        f"  Rep drift (std)        {result.validator_reputation_drift:>10.2f}",
        "",
        sep,
        "  ECONOMICS",
        sep,
        f"  Economic loss          {result.economic_loss:>10.6f} USDC",
        f"  Protocol revenue       {result.protocol_revenue:>10.6f} USDC",
        f"  Slashed stake          {result.slashed_stake:>10.4f} USDC",
        f"  Reward Gini coeff.     {result.validator_reward_gini:>10.4f}",
        "",
        sep,
        "  ATTACK-SPECIFIC",
        sep,
    ]
    if result.collusion_success_rate > 0:
        lines.append(f"  Collusion success      {result.collusion_success_rate:>10.1%}")
    if result.sybil_capture_probability > 0:
        lines.append(f"  Sybil capture prob.    {result.sybil_capture_probability:>10.1%}")
    if result.bribery_success_rate > 0:
        lines.append(f"  Bribery success rate   {result.bribery_success_rate:>10.1%}")
    if result.judge_failure_rate > 0:
        lines.append(f"  Judge failure rate     {result.judge_failure_rate:>10.1%}")
    if result.spam_overload_rate > 0:
        lines.append(f"  Spam overload rate     {result.spam_overload_rate:>10.1%}")
    lines.append("")
    print("\n".join(lines))


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
