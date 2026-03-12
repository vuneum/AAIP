"""
aaip/cli/simulate.py
Command: simulate
"""
from __future__ import annotations

import random

import click

from ._shared import banner, bold, dim, g, r, tick, y


@click.command()
@click.option("--agents",           default=10,     show_default=True, help="Number of agents to simulate")  # noqa: E501
@click.option("--validators",       default=5,      show_default=True, help="Validators per panel")
@click.option("--malicious-ratio",  default=0.20,   show_default=True, help="Fraction of malicious agents (0-1)")  # noqa: E501
@click.option("--scenario",         default="mixed", show_default=True,
              type=click.Choice(["honest", "fraud", "mixed", "sybil", "collusion"]),
              help="Simulation scenario")
@click.option("--tasks",            default=100,    show_default=True, help="Number of tasks to simulate")  # noqa: E501
def simulate(
    agents: int,
    validators: int,
    malicious_ratio: float,
    scenario: str,
    tasks: int,
) -> None:
    """
    Simulate a network of agents submitting tasks through the AAIP protocol.

    Tracks validation accuracy, fraud detection rate, and economic outcomes.

    Examples:
        aaip simulate --agents 100 --scenario collusion
        aaip simulate --agents 1000 --malicious-ratio 0.30
    """
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE
    from aaip.validators import ValidatorPanel

    banner()
    click.echo(bold("  aaip simulate\n"))
    click.echo(f"  Agents:     {bold(str(agents))}  ({int(agents * malicious_ratio)} malicious)")
    click.echo(f"  Validators: {bold(str(validators))} per panel  (threshold ≥ 2/3)")
    click.echo(f"  Tasks:      {bold(str(tasks))}")
    click.echo(f"  Scenario:   {bold(scenario)}")
    click.echo()

    rng              = random.Random(42)
    agent_identities = [AgentIdentity.generate() for _ in range(agents)]
    n_malicious      = int(agents * malicious_ratio)
    malicious_ids    = {a.agent_id for a in agent_identities[:n_malicious]}
    panel            = ValidatorPanel(n=validators)

    approved_count  = 0
    rejected_count  = 0
    fraud_caught    = 0
    false_positive  = 0
    escrow_released = 0.0
    escrow_refunded = 0.0
    task_value      = 0.002   # USDC

    tasks_to_run = min(tasks, 500)
    bar_width    = 40

    click.echo(f"  Running {tasks_to_run} tasks...")
    click.echo()

    for i in range(tasks_to_run):
        agent      = rng.choice(agent_identities)
        is_mal     = agent.agent_id in malicious_ids
        should_fraud = _should_commit_fraud(scenario, is_mal, rng)

        task_desc  = f"Task {i}: process dataset and return summary"
        output_str = f"Processed dataset {i}. Summary: {rng.randint(1000, 9999)} records."

        poe = DeterministicPoE(agent)
        poe.begin(task_desc)
        poe.record_tool("data_processor")
        poe.record_model("gpt-4o")
        poe.set_output(output_str)
        poe.finish()
        poe_dict = poe.to_dict()

        if should_fraud:
            poe_dict["output_hash"] = "00" * 32
            poe_dict["step_count"]  = -1

        result = panel.vote(poe_dict)

        if result.passed:
            approved_count  += 1
            escrow_released += task_value * 0.993
        else:
            rejected_count  += 1
            escrow_refunded += task_value
            if should_fraud:
                fraud_caught += 1
            else:
                false_positive += 1

        # Progress bar
        if (i + 1) % max(1, tasks_to_run // 20) == 0 or i == tasks_to_run - 1:
            done = int((i + 1) / tasks_to_run * bar_width)
            bar  = "█" * done + "░" * (bar_width - done)
            pct  = int((i + 1) / tasks_to_run * 100)
            click.echo(f"  [{bar}] {pct:3d}%  ({i + 1}/{tasks_to_run})", nl=(i == tasks_to_run - 1))

    click.echo()
    click.echo()

    fraud_detection = fraud_caught / max(1, rejected_count + fraud_caught) * 100
    validation_acc  = approved_count / tasks_to_run * 100

    click.echo(f"  {'─' * 48}")
    click.echo(f"  {bold('Results')}\n")
    tick(f"Tasks run:        {bold(str(tasks_to_run))}")
    tick(f"Approved:         {g(bold(str(approved_count)))}  ({validation_acc:.1f}%)")
    tick(f"Rejected:         {r(bold(str(rejected_count)))}")
    tick(f"Fraud caught:     {g(bold(str(fraud_caught)))}")
    tick(f"False positives:  {bold(str(false_positive))}")
    tick(f"Escrow released:  {y(bold(f'{escrow_released:.4f} USDC'))}")
    tick(f"Escrow refunded:  {bold(f'{escrow_refunded:.4f} USDC')}")
    tick(f"Fraud detection:  {g(bold(f'{fraud_detection:.1f}%'))}")
    click.echo()
    click.echo(dim(
        "  For full simulation (7 scenarios, 2000 tasks): "
        "python simulation_lab/aaip_sim.py benchmark\n"
    ))


def _should_commit_fraud(scenario: str, is_malicious: bool, rng: random.Random) -> bool:
    """Determine whether the current agent should submit a fraudulent PoE."""
    if scenario == "honest":
        return False
    if scenario == "fraud":
        return True
    if scenario == "mixed":
        return is_malicious and rng.random() < 0.7
    if scenario == "sybil":
        return is_malicious
    if scenario == "collusion":
        return is_malicious and rng.random() < 0.5
    return False
