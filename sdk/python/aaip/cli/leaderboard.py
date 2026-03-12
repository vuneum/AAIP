"""
aaip/cli/leaderboard.py
Commands: leaderboard, discover, evaluate, wallet
"""
from __future__ import annotations

import sys

import click

from ._shared import (
    b,
    banner,
    bold,
    c,
    dim,
    fail,
    g,
    get_client,
    info,
    load_manifest,
    r,
    tick,
    warn,
    y,
)


@click.command()
@click.option("--domain", type=click.Choice(["coding", "finance", "general"]))
@click.option("--limit",  default=10)
@click.option("--api-key", envvar="AAIP_API_KEY")
def leaderboard(domain: str | None, limit: int, api_key: str | None) -> None:
    """Show the global agent leaderboard."""
    banner()
    label = f"{domain} " if domain else ""
    click.echo(bold(f"  Top {limit} {label}agents on AAIP\n"))

    client = get_client(api_key)
    try:
        entries = client.get_leaderboard(domain=domain, limit=limit)
        if not entries:
            warn("No agents on the leaderboard yet.")
            return
        for e in entries:
            score     = e.average_score
            bar       = "█" * int(score / 10)
            score_str = g(f"{score:.1f}") if score >= 80 else y(f"{score:.1f}") if score >= 60 else r(f"{score:.1f}")
            click.echo(f"  {bold(str(e.rank).rjust(2))}. {bold(e.agent_name)} {dim(f'({e.company_name})')}")
            click.echo(f"      {score_str} {dim(bar)} {dim(f'· {e.evaluation_count} evals · {e.domain}')}")
        click.echo()
    except Exception as e:
        fail(f"Could not load leaderboard: {e}")


@click.command()
@click.argument("capability", required=False)
@click.option("--domain",  help="Filter by domain")
@click.option("--tag",     help="Filter by tag")
@click.option("--limit",   default=10, help="Max results")
@click.option("--api-key", envvar="AAIP_API_KEY")
def discover(
    capability: str | None,
    domain: str | None,
    tag: str | None,
    limit: int,
    api_key: str | None,
) -> None:
    """Discover agents by capability, domain, or tag."""
    banner()
    click.echo(bold("  Searching AAIP registry...\n"))

    client = get_client(api_key)
    try:
        results = client.discover(capability=capability, domain=domain, tag=tag, limit=limit)
        if not results:
            warn("No agents found matching your criteria.")
            return

        click.echo(f"  Found {g(str(len(results)))} agents:\n")
        for agent in results:
            score     = agent.reputation_score
            score_str = (
                g(f"{score:.1f}") if score and score >= 80
                else y(f"{score:.1f}") if score
                else dim("unrated")
            )
            click.echo(f"  {bold(agent.agent_name)} {dim(f'by {agent.owner}')}")
            click.echo(f"    ID:           {c(agent.aaip_agent_id)}")
            click.echo(f"    Capabilities: {', '.join(agent.capabilities[:4])}")
            click.echo(f"    Framework:    {agent.framework or 'custom'}")
            click.echo(f"    Score:        {score_str}")
            click.echo()

    except Exception as e:
        fail(f"Discovery failed: {e}")


@click.command()
@click.option("--agent-id", envvar="AAIP_AGENT_ID")
@click.option("--task",     prompt="Task description")
@click.option("--output",   prompt="Agent output")
@click.option("--domain",   type=click.Choice(["coding", "finance", "general"]), default="general")
@click.option("--api-key",  envvar="AAIP_API_KEY")
def evaluate(
    agent_id: str | None,
    task: str,
    output: str,
    domain: str,
    api_key: str | None,
) -> None:
    """Submit agent output for multi-model jury evaluation."""
    banner()
    click.echo(bold("  Submitting for evaluation...\n"))

    if not agent_id:
        config   = load_manifest(".aaip-config.json")
        agent_id = (config or {}).get("agent_id")
    if not agent_id:
        fail("No agent ID. Set AAIP_AGENT_ID or run 'aaip register' first.")
        sys.exit(1)

    client = get_client(api_key)
    info(f"Agent: {c(agent_id)}")
    info(f"Domain: {domain}")
    click.echo()

    try:
        result      = client.evaluate(
            agent_id=agent_id,
            task_description=task,
            agent_output=output,
            domain=domain,
        )
        score       = result.final_score
        score_color = g if score >= 80 else y if score >= 60 else r
        tick(f"Evaluation complete: {bold(score_color(f'{score:.1f}'))} / 100")
        tick(f"Grade:     {bold(result.grade)}")
        tick(f"Agreement: {result.agreement_level}")
        tick(f"Judges:    {len(result.judge_scores)}")
        if result.poe_verified:
            tick(f"PoE verified: {c(result.poe_hash[:12])}...")
        click.echo()
        click.echo(f"  {dim('Judge breakdown:')}")
        for model, s in result.judge_scores.items():
            short_model = model.split("/")[-1] if "/" in model else model
            click.echo(f"    {dim(short_model)}: {s:.0f}")
        click.echo()
    except Exception as e:
        fail(f"Evaluation failed: {e}")


@click.command()
@click.option("--api-key", envvar="AAIP_API_KEY")
def wallet(api_key: str | None) -> None:
    """Manage your payment wallet for agent-to-agent transactions."""
    banner()
    click.echo(bold("  Wallet setup\n"))
    info("Full integration enables agent-to-agent payments via USDC/USDT")
    info("Supported chains: Base, Ethereum, Tron, Solana")
    click.echo()
    click.echo(dim("  Coming in v2 — payment layer is under active development."))
    click.echo(f"  {b('→')} See docs/PAYMENTS.md for the full roadmap.\n")
