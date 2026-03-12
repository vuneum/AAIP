"""
aaip/cli/run.py
Commands: run, verify, demo
"""
from __future__ import annotations

import time

import click

from ._shared import (
    b,
    banner,
    bold,
    c,
    dim,
    g,
    info,
    r,
    tick,
)


@click.command()
@click.argument("task")
@click.option("--tools",  default="web_search,read_url", show_default=True, help="Comma-separated tools used")
@click.option("--model",  default="gpt-4o",              show_default=True, help="Model used")
@click.option("--output", default=None,                  help="Output text (prompted if omitted)")
def run(task: str, tools: str, model: str, output: str | None) -> None:
    """
    Execute a task, record a PoE, and display the signed trace.

    Example:
        aaip run "Summarise the AAIP protocol" --tools web_search,read_url
    """
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE

    banner()
    click.echo(bold("  aaip run\n"))

    identity = AgentIdentity.load_or_create()
    tick(f"Agent: {c(identity.agent_id)}")
    info(f"Task: {dim(task[:70])}")
    click.echo()

    if output is None:
        output = click.prompt("  Agent output")

    tool_list = [t.strip() for t in tools.split(",") if t.strip()]

    poe = DeterministicPoE(identity)
    poe.begin(task)
    for tool in tool_list:
        poe.record_tool(tool)
    poe.record_model(model)
    poe.record_step()
    poe.set_output(output)
    poe.finish()

    poe_dict = poe.to_dict()
    click.echo()
    tick("PoE recorded")
    tick(f"Tools:     {', '.join(tool_list)}")
    tick(f"Model:     {model}")
    tick(f"Steps:     {poe_dict['step_count']}")
    tick(f"PoE hash:  {c(poe.poe_hash[:20])}...")
    tick(f"Signature: {dim(poe.signature[:20])}...")
    click.echo()
    click.echo(dim("  Run 'aaip verify' to verify this trace with local validators."))
    click.echo(dim("  Run 'aaip explorer --json-output' to see full signed object.\n"))


@click.command()
@click.option("--task",       default="Analyse the AAIP protocol and summarise key components", show_default=True)
@click.option("--output",     default="AAIP has 8 layers: identity, registry, execution, PoE, jury, CAV, validators, escrow.", show_default=True)
@click.option("--validators", default=3,     show_default=True, help="Number of validators in panel")
@click.option("--json-output", is_flag=True, default=False,     help="Print raw JSON result")
def verify(task: str, output: str, validators: int, json_output: bool) -> None:
    """
    Build a PoE for a task+output and run it through a local validator panel.

    Example:
        aaip verify --task "Translate this text" --output "Bonjour le monde"
    """
    import json as _json

    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE
    from aaip.validators import ValidatorPanel

    banner()
    click.echo(bold("  aaip verify\n"))

    identity = AgentIdentity.load_or_create()
    tick(f"Agent: {c(identity.agent_id)}")
    click.echo()

    poe = DeterministicPoE(identity)
    poe.begin(task)
    poe.record_tool("web_search")
    poe.record_model("gpt-4o")
    poe.record_step()
    poe.set_output(output)
    poe.finish()
    poe_dict = poe.to_dict()

    tick(f"PoE built — hash: {c(poe.poe_hash[:16])}...")
    click.echo()

    click.echo(bold(f"  Validator panel  ({validators} validators, threshold ≥ 2/3)"))
    panel  = ValidatorPanel(n=validators)
    result = panel.vote(poe_dict)

    for vote in result.votes:
        sym  = g("✔") if vote.approved else r("✘")
        note = f"  {dim('→ ' + ', '.join(vote.signals))}" if vote.signals else ""
        click.echo(f"    {sym}  {bold(vote.validator_id)}{note}")
        time.sleep(0.15)

    click.echo()
    if result.passed:
        click.echo(f"  {g(bold('VERIFIED'))}  ({result.approve_count}/{result.total_validators} validators approved)\n")
    else:
        click.echo(f"  {r(bold('REJECTED'))}  ({result.reject_count}/{result.total_validators} rejected)\n")

    if json_output:
        click.echo(_json.dumps({
            "poe": poe_dict,
            "consensus": result.consensus,
            "votes": [
                {"validator_id": v.validator_id, "approved": v.approved, "signals": v.signals}
                for v in result.votes
            ],
        }, indent=2))


@click.command()
@click.option("--fraud",      is_flag=True, default=False, help="Demo with a fraudulent PoE (shows rejection)")
@click.option("--validators", default=3,    show_default=True, help="Number of validators in panel")
def demo(fraud: bool, validators: int) -> None:
    """
    Run the full AAIP protocol demo — no network required.

    Flow:
      1. Generate agent keypair
      2. Execute task + build PoE
      3. Simulate validator panel voting
      4. Display explorer-style result

    Try --fraud to see a rejected trace.
    """
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE
    from aaip.validators import ValidatorPanel

    banner()
    click.echo(bold("  ░░░ AAIP Protocol Demo ░░░\n"))
    if fraud:
        click.echo(f"  Mode: {b('Fraudulent execution')} (PoE will be REJECTED)\n")
    else:
        click.echo(f"  Mode: {g('Honest execution')}\n")
    time.sleep(0.3)

    # Step 1: Identity
    click.echo(bold("  [1/4] Agent Identity"))
    identity = AgentIdentity.generate()
    time.sleep(0.3)
    tick("Keypair generated (ed25519)")
    tick(f"Agent ID:   {c(identity.agent_id)}")
    tick(f"Public key: {dim(identity.public_key_hex[:24])}...")
    click.echo()
    time.sleep(0.3)

    # Step 2: PoE
    click.echo(bold("  [2/4] Task Execution & PoE"))
    task   = "Analyse the top 5 AI agent frameworks and summarise their trust models"
    output = (
        "LangChain, CrewAI, AutoGPT, OpenAI Agents, and MetaGPT were analysed. "
        "None implement cryptographic execution proofs natively. AAIP fills this gap."
    )
    info(f"Task: {dim(task[:60])}...")
    time.sleep(0.5)

    poe = DeterministicPoE(identity)
    poe.begin(task)
    poe.record_tool("web_search")
    poe.record_tool("read_url")
    poe.record_model("gpt-4o")
    poe.record_step()
    poe.set_output(output)
    poe.finish()
    poe_dict = poe.to_dict()

    if fraud:
        poe_dict["output_hash"] = "deadbeef" * 8
        poe_dict["step_count"]  = -1

    time.sleep(0.4)
    tick(f"Tools recorded: {', '.join(poe_dict.get('tools_used', []))}")
    tick(f"Model used:     {poe_dict.get('model_used')}")
    tick(f"Output hash:    {dim(poe_dict['output_hash'][:16])}...")
    tick(f"PoE hash:       {c(poe_dict['poe_hash'][:16])}...")
    tick(f"Signature:      {dim(poe_dict['signature'][:16])}...")
    click.echo()
    time.sleep(0.3)

    # Step 3: Validators
    click.echo(bold(f"  [3/4] Validator Consensus  ({validators} validators, threshold ≥ 2/3)"))
    time.sleep(0.3)

    panel  = ValidatorPanel(n=validators)
    result = panel.vote(poe_dict)

    for vote in result.votes:
        sym  = g("✔") if vote.approved else r("✘")
        note = f"  {dim('signals: ' + ', '.join(vote.signals))}" if vote.signals else ""
        click.echo(
            f"    {sym}  {bold(vote.validator_id)}  "
            f"{dim(f'stake={vote.stake:.0f} · vote_hash={vote.vote_hash}')}{note}"
        )
        time.sleep(0.25)

    click.echo()
    ratio_pct = f"{result.approve_ratio * 100:.0f}%"
    click.echo(f"  Votes:     {g(str(result.approve_count))} approve  /  {r(str(result.reject_count))} reject  ({ratio_pct})")
    click.echo(f"  Threshold: {result.approve_count}/{result.total_validators} ≥ {result.threshold:.0%} required")
    click.echo()
    time.sleep(0.3)

    # Step 4: Explorer
    click.echo(bold("  [4/4] AAIP Explorer"))
    time.sleep(0.3)
    click.echo(f"""
  ┌─────────────────────────────────────────────────────┐
  │  Task ID   {dim(poe_dict['poe_hash'][:10])}...
  │  Agent     {c(poe_dict['agent_id'])}
  │  PoE Hash  {dim(poe_dict['poe_hash'][:16])}...
  │
  │  Validators""")
    for vote in result.votes:
        sym = g("✔") if vote.approved else r("✘")
        click.echo(f"  │    {sym}  {vote.validator_id}")
    click.echo("  │")

    if result.passed:
        click.echo(f"  │  Status  {g(bold('VERIFIED ✔'))}")
        click.echo(f"  │  Escrow  {g('Released')}")
    else:
        click.echo(f"  │  Status  {r(bold('REJECTED ✘'))}")
        click.echo(f"  │  Escrow  {r('Refunded to requester')}")
    click.echo("  └─────────────────────────────────────────────────────┘\n")

    if result.passed:
        click.echo(f"  {g(bold('Consensus reached.'))} Task verified by {result.approve_count}/{result.total_validators} validators.\n")
    else:
        click.echo(f"  {r(bold('Consensus failed.'))} PoE rejected — fraudulent trace detected.\n")
        sigs = set(s for v in result.votes for s in v.signals)
        if sigs:
            click.echo(f"  {r('Signals:')} {', '.join(sigs)}\n")

    click.echo(dim("  Run without --fraud to see a successful verification."))
    click.echo(dim("  Run aaip explorer to view the full signed PoE object.\n"))
