"""
aaip/cli/explorer.py
Commands: explorer, explore (alias)
"""
from __future__ import annotations

import click

from ._shared import b, banner, bold, c, dim, g, r


def _build_demo_poe(fraud: bool) -> tuple:
    """Build a demo PoE and run validator consensus. Returns (poe_dict, result)."""
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE
    from aaip.validators import ValidatorPanel

    identity = AgentIdentity.load_or_create()
    task     = "Review pull request #312 for security vulnerabilities"
    output   = "Found 1 critical SQL injection in line 84. Recommend parameterised queries."

    poe = DeterministicPoE(identity)
    poe.begin(task)
    poe.record_tool("github_api")
    poe.record_tool("static_analyser")
    poe.record_model("claude-sonnet-4")
    poe.record_step()
    poe.set_output(output)
    poe.finish()
    poe_dict = poe.to_dict()

    if fraud:
        poe_dict["poe_hash"] = "0" * 64

    result = ValidatorPanel(n=3).vote(poe_dict)
    return poe_dict, result


@click.command()
@click.option("--fraud",       is_flag=True, default=False, help="Show a fraudulent PoE for comparison")
@click.option("--json-output", is_flag=True, default=False, help="Print raw JSON")
@click.option("--pretty",      is_flag=True, default=False, help="Pretty-print the full trace")
def explorer(fraud: bool, json_output: bool, pretty: bool) -> None:
    """
    AAIP Explorer — inspect, verify, and pretty-print a PoE object.

    Shows the full signed PoE, validator votes, and final status.
    Use --pretty for a colour-formatted trace view.
    Use --json-output for machine-readable output.
    """
    banner()
    click.echo(bold("  aaip explorer\n"))
    _render_explorer(fraud, json_output, pretty)


@click.command()
@click.option("--fraud",       is_flag=True, default=False, help="Show a fraudulent PoE for comparison")
@click.option("--json-output", is_flag=True, default=False, help="Print raw JSON")
def explore(fraud: bool, json_output: bool) -> None:
    """AAIP Explorer — inspect a signed PoE and validator votes (alias for explorer)."""
    banner()
    click.echo(bold("  ░░░ AAIP Explorer ░░░\n"))
    _render_explorer(fraud, json_output, pretty=False)


def _render_explorer(fraud: bool, json_output: bool, pretty: bool) -> None:
    """Shared rendering logic for both explorer and explore commands."""
    import json as _json

    poe_dict, result = _build_demo_poe(fraud)

    if json_output:
        click.echo(_json.dumps({
            "poe":       poe_dict,
            "consensus": result.consensus,
            "votes": [
                {
                    "validator_id": v.validator_id,
                    "approved":     v.approved,
                    "verdict":      v.verdict,
                    "signals":      v.signals,
                    "vote_hash":    v.vote_hash,
                }
                for v in result.votes
            ],
        }, indent=2))
        return

    if pretty:
        click.echo(f"  {bold('PoE Trace')}\n")
        fields = [
            ("aaip_version", poe_dict["aaip_version"]),
            ("agent_id",     c(poe_dict["agent_id"])),
            ("task",         dim(poe_dict["task"][:60] + ("..." if len(poe_dict["task"]) > 60 else ""))),
            ("tools_used",   g(", ".join(poe_dict["tools_used"]))),
            ("model_used",   b(str(poe_dict["model_used"]))),
            ("step_count",   str(poe_dict["step_count"])),
            ("output_hash",  dim(poe_dict["output_hash"][:20]) + "..."),
            ("timestamp",    str(poe_dict["timestamp"])),
            ("poe_hash",     c(poe_dict["poe_hash"][:20]) + "..."),
            ("signature",    dim(poe_dict["signature"][:20]) + "..."),
            ("public_key",   dim(poe_dict["public_key"][:20]) + "..."),
        ]
        max_key = max(len(k) for k, _ in fields)
        for key, val in fields:
            click.echo(f"    {bold(key.ljust(max_key))}  {val}")
        click.echo()
    else:
        click.echo(f"  {bold('Task')}       {dim(poe_dict['task'])}")
        click.echo(f"  {bold('Agent')}      {c(poe_dict['agent_id'])}")
        click.echo(f"  {bold('PoE Hash')}   {c(poe_dict['poe_hash'][:20])}...")
        click.echo(f"  {bold('Signature')}  {dim(poe_dict['signature'][:20])}...")
        click.echo()

    click.echo(f"  {bold('Validators')}")
    for vote in result.votes:
        sym = g("✔") if vote.approved else r("✘")
        click.echo(
            f"    {sym}  {bold(vote.validator_id):<16} "
            f"stake={vote.stake:.0f}  hash_ok={vote.hash_verified}"
        )
        if vote.signals:
            click.echo(f"         {r('signals: ' + ', '.join(vote.signals))}")
    click.echo()

    if result.passed:
        click.echo(f"  {g(bold('  ✔  VERIFIED  '))}  Escrow released\n")
    else:
        click.echo(f"  {r(bold('  ✘  REJECTED  '))}  Escrow refunded\n")

    click.echo(dim("  Flags: --pretty  --json-output  --fraud\n"))
