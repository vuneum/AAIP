"""
examples/openai_agents/agent.py
================================
OpenAI Agents SDK agent with AAIP Proof of Execution verification.

Flow:
  1. Auto-generate agent keypair on first run
  2. Define tools — each call records to PoE trace
  3. Run the OpenAI Agents SDK runner
  4. Finalise PoE: hash + ed25519 signature
  5. Local validator panel votes
  6. Explorer output

Install:
    pip install aaip openai-agents
    export OPENAI_API_KEY=sk-...

Run without API key:
    python agent.py    # mock execution
"""

import os
import time

from aaip.identity import AgentIdentity
from aaip.poe.deterministic import DeterministicPoE
from aaip.validators import ValidatorPanel

G = "\033[92m"; B = "\033[94m"; C = "\033[96m"
DIM = "\033[2m"; BOLD = "\033[1m"; R = "\033[0m"

def header(msg): print(f"\n{BOLD}  {msg}{R}\n")
def ok(msg):     print(f"  {G}✔{R}  {msg}")
def info(msg):   print(f"  {B}→{R}  {msg}")


# ── 1. Identity ──────────────────────────────────────────────────────────────
header("Agent Identity")
identity = AgentIdentity.load_or_create(".aaip-identity.json")
ok(f"Agent ID:   {C}{identity.agent_id}{R}")

TASK = (
    "Search for recent GitHub repositories implementing AI agent verification, "
    "then run a code analysis on the most promising one and summarise the findings."
)

poe = DeterministicPoE(identity)
poe.begin(TASK)


# ── 2. Execution ─────────────────────────────────────────────────────────────
header("OpenAI Agents SDK Execution")

HAS_AGENTS_SDK = False
try:
    import agents as openai_agents
    HAS_AGENTS_SDK = bool(os.getenv("OPENAI_API_KEY"))
except ImportError:
    pass

if HAS_AGENTS_SDK:
    import asyncio
    import agents as sdk

    @sdk.function_tool
    def github_search(query: str) -> str:
        """Search GitHub for repositories matching a query."""
        poe.record_tool("github_search")
        return f"Found 5 repos for '{query}'. Top: aaip-protocol/aaip (⭐ 847), agentkit/verify (⭐ 412)."

    @sdk.function_tool
    def code_analysis(repo_url: str) -> str:
        """Analyse the code quality and architecture of a GitHub repository."""
        poe.record_tool("code_analysis")
        return (
            f"Analysis of {repo_url}: "
            "Well-structured Python package. "
            "Implements SHA-256 hash chains and ed25519 signing for execution traces. "
            "Test coverage: 84%. No critical issues found."
        )

    agent = sdk.Agent(
        name="ResearchAgent",
        instructions=(
            "You are a technical research agent. Use the provided tools "
            "to gather information and produce a concise, factual summary."
        ),
        tools=[github_search, code_analysis],
        model="gpt-4o",
    )

    print(f"  {DIM}Running OpenAI Agents SDK...{R}\n")
    result = asyncio.run(sdk.Runner.run(agent, TASK))
    output = result.final_output
    poe.record_model("gpt-4o")
    poe.record_step()

else:
    print(f"  {DIM}(No OPENAI_API_KEY or openai-agents not installed — mock){R}\n")
    time.sleep(0.3)

    info("Tool: github_search('AI agent verification')")
    poe.record_tool("github_search")
    time.sleep(0.2)

    info("Tool: code_analysis('github.com/aaip-protocol/aaip')")
    poe.record_tool("code_analysis")
    time.sleep(0.2)

    poe.record_model("gpt-4o")
    poe.record_step()

    output = (
        "Found 5 relevant repositories implementing AI agent verification. "
        "Top result: aaip-protocol/aaip — implements SHA-256 PoE hash chains, "
        "ed25519 signing, multi-model jury scoring, and validator consensus. "
        "Code quality: strong (84% test coverage, no critical issues). "
        "Recommended for production evaluation."
    )

print()
ok(f"Output: {DIM}{output[:80]}...{R}")


# ── 3. PoE + Validation ──────────────────────────────────────────────────────
header("Proof of Execution")

poe.set_output(output)
poe.finish()
poe_dict = poe.to_dict()

ok(f"Tools:    {', '.join(poe_dict['tools_used'])}")
ok(f"Model:    {poe_dict['model_used']}")
ok(f"Steps:    {poe_dict['step_count']}")
ok(f"PoE hash: {C}{poe_dict['poe_hash'][:20]}{R}...")

header("Validator Consensus  (3 validators, ≥ 2/3 threshold)")

panel  = ValidatorPanel(n=3)
result = panel.vote(poe_dict)

for vote in result.votes:
    sym = f"{G}✔{R}" if vote.approved else f"\033[91m✘{R}"
    print(f"    {sym}  {BOLD}{vote.validator_id}{R}")
    time.sleep(0.2)

print(f"\n  {result.approve_count}/{result.total_validators} approved\n")


# ── 4. Explorer ──────────────────────────────────────────────────────────────
header("AAIP Explorer")
print(f"  {'─'*52}")
rows = [
    ("Agent ID",    f"{C}{poe_dict['agent_id']}{R}"),
    ("Task ID",     f"{DIM}{poe_dict['poe_hash'][:10]}{R}..."),
    ("PoE Hash",    f"{C}{poe_dict['poe_hash'][:20]}{R}..."),
    ("Signature",   f"{DIM}{poe_dict['signature'][:20]}{R}..."),
    ("Tools",       ", ".join(poe_dict["tools_used"])),
    ("Model",       poe_dict["model_used"]),
]
for k, v in rows:
    print(f"  {BOLD}{k:<12}{R}  {v}")
print()
print(f"  {'Validators':<12}")
for v in result.votes:
    sym = f"{G}✔{R}" if v.approved else f"\033[91m✘{R}"
    print(f"    {sym}  {v.validator_id}")
print()
if result.passed:
    print(f"  {G}{BOLD}  ✔  VERIFIED  {R}  Escrow released\n")
else:
    print(f"  \033[91m{BOLD}  ✘  REJECTED  {R}  Escrow refunded\n")
