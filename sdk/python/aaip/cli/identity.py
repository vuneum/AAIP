"""
aaip/cli/identity.py
Commands: init, register, status, doctor
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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
    save_manifest,
    tick,
    warn,
    y,
)


@click.command()
@click.option("--name",         prompt="Agent name",              help="Your agent's name")
@click.option("--owner",        prompt="Owner / organization",    help="Your name or org")
@click.option("--endpoint",     prompt="Agent endpoint URL",      help="https://your-agent.com/api")
@click.option("--capabilities", prompt="Capabilities (comma-separated)", help="e.g. translation,code_analysis")
@click.option("--domain",       type=click.Choice(["coding", "finance", "general"]),
              default="general", prompt="Domain")
@click.option("--framework",    type=click.Choice(["langchain", "crewai", "openai_agents", "autogpt", "custom"]),
              prompt="Framework", default="custom")
@click.option("--output",       default=".aaip.json", help="Output file path")
def init(
    name: str,
    owner: str,
    endpoint: str,
    capabilities: str,
    domain: str,
    framework: str,
    output: str,
) -> None:
    """Generate a .aaip.json manifest for your agent."""
    banner()
    click.echo(bold("  Initializing AAIP manifest...\n"))

    caps = [cap.strip() for cap in capabilities.split(",") if cap.strip()]

    manifest = {
        "aaip_version": "1.0",
        "agent_name": name,
        "owner": owner,
        "version": "1.0.0",
        "endpoint": endpoint,
        "capabilities": caps,
        "domains": [domain],
        "framework": framework,
        "tags": [framework],
        "description": "",
        "metadata": {},
    }

    save_manifest(manifest, output)

    wk_path = Path(".well-known/aaip-agent.json")
    wk_path.parent.mkdir(exist_ok=True)
    with open(wk_path, "w") as f:
        json.dump(manifest, f, indent=2)

    tick(f"Manifest saved to {b(output)}")
    tick(f"Auto-discovery file saved to {b(str(wk_path))}")
    click.echo()
    click.echo(dim("  Next steps:"))
    info(f"Run {bold('aaip register')} to register with the AAIP network")
    info(f"Run {bold('aaip doctor')} to validate your config")
    click.echo()


@click.command()
@click.option("--manifest", default=".aaip.json",  help="Path to manifest file")
@click.option("--api-key",  envvar="AAIP_API_KEY", help="AAIP API key")
def register(manifest: str, api_key: str | None) -> None:
    """Register your agent with the AAIP network."""
    banner()
    click.echo(bold("  Registering agent...\n"))

    data = load_manifest(manifest)
    if not data:
        fail(f"Manifest not found at {manifest}. Run {bold('aaip init')} first.")
        sys.exit(1)

    info(f"Agent: {b(data.get('agent_name', 'unknown'))}")
    info(f"Owner: {data.get('owner', 'unknown')}")
    info(f"Capabilities: {', '.join(data.get('capabilities', []))}")
    click.echo()

    client = get_client(api_key)

    try:
        result   = client.register(data)
        agent_id = (
            result.get("arpp_agent_id")
            or result.get("aaip_agent_id")
            or result.get("agent_id", "")
        )

        tick("Connected to AAIP network")
        tick(f"Agent ID: {c(agent_id)}")
        tick("Discovery profile created")
        tick("Reputation tracking enabled")

        config_path = Path(".aaip-config.json")
        config: dict = {}
        if config_path.exists():
            config = json.loads(config_path.read_text())
        config["agent_id"] = agent_id
        config_path.write_text(json.dumps(config, indent=2))
        tick(f"Agent ID saved to {b('.aaip-config.json')}")

        click.echo()
        click.echo(dim("  Next steps:"))
        info(f"Run {bold('aaip status')} to see your agent's score")
        info(f"Run {bold('aaip evaluate')} to submit your first evaluation")
        click.echo()

    except Exception as e:
        fail(f"Registration failed: {e}")
        sys.exit(1)


@click.command()
@click.option("--agent-id", envvar="AAIP_AGENT_ID")
@click.option("--api-key",  envvar="AAIP_API_KEY")
def status(agent_id: str | None, api_key: str | None) -> None:
    """Show your agent's reputation score and stats."""
    banner()

    if not agent_id:
        config   = load_manifest(".aaip-config.json")
        agent_id = (config or {}).get("agent_id")
    if not agent_id:
        fail("No agent ID. Set AAIP_AGENT_ID or run 'aaip register' first.")
        sys.exit(1)

    client = get_client(api_key)
    try:
        data   = client.get_agent(agent_id)
        rep    = client.get_reputation(agent_id)
        score  = rep.current_score
        trend  = rep.trend
        trend_str = (
            g(f"↑ +{trend:.1f}") if trend > 0
            else r(f"↓ {trend:.1f}") if trend < 0
            else dim("→ 0.0")
        )

        agent  = data.get("agent", {})
        traces = data.get("trace_stats", {})

        click.echo(f"  {bold(agent.get('agent_name', agent_id))}\n")
        tick(f"Reputation score:  {g(bold(f'{score:.1f}'))} / 100")
        tick(f"30-day trend:      {trend_str}")
        tick(f"Evaluations:       {rep.evaluation_count}")
        tick(f"Traces recorded:   {traces.get('trace_count', 0)}")
        tick(f"Avg latency:       {traces.get('average_latency_ms', 0):.0f}ms")
        tick(f"Framework:         {agent.get('framework', 'custom')}")
        click.echo()

    except Exception as e:
        fail(f"Could not fetch status: {e}")


@click.command()
@click.option("--api-key",  envvar="AAIP_API_KEY")
@click.option("--base-url", envvar="AAIP_BASE_URL")
def doctor(api_key: str | None, base_url: str | None) -> None:
    """Validate your AAIP config and check network health."""
    banner()
    click.echo(bold("  Running diagnostics...\n"))

    issues = 0

    manifest = load_manifest(".aaip.json")
    if manifest:
        tick(".aaip.json manifest found")
        caps = manifest.get("capabilities", [])
        if caps:
            tick(f"Capabilities defined: {', '.join(caps[:3])}")
        else:
            warn("No capabilities defined in manifest")
            issues += 1
    else:
        fail(".aaip.json not found — run 'aaip init'")
        issues += 1

    if Path(".well-known/aaip-agent.json").exists():
        tick(".well-known/aaip-agent.json ready for auto-discovery")
    else:
        warn(".well-known/aaip-agent.json missing (optional but recommended)")

    key = api_key or os.environ.get("AAIP_API_KEY", "")
    if key:
        tick("AAIP_API_KEY set")
    else:
        warn("AAIP_API_KEY not set — set it to authenticate")
        issues += 1

    config   = load_manifest(".aaip-config.json")
    agent_id = (config or {}).get("agent_id")
    if agent_id:
        tick(f"Agent ID: {c(agent_id)}")
    else:
        warn("No agent ID found — run 'aaip register'")
        issues += 1

    client = get_client(api_key, base_url)
    try:
        client.health()
        tick(f"AAIP API reachable — {g('healthy')}")
    except Exception as e:
        fail(f"AAIP API unreachable: {e}")
        issues += 1

    click.echo()
    if issues == 0:
        click.echo(f"  {g(bold('All checks passed.'))} Your agent is ready.\n")
    else:
        click.echo(f"  {y(bold(f'{issues} issue(s) found.'))} Fix them above.\n")
