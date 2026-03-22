"""
examples/openclaw/agent.py
===========================
OpenClaw — minimal custom agent with AAIP.

The simplest possible integration: one import, one decorator.

Run:
    pip install aaip
    python agent.py
"""

import time

GREEN = "\033[92m"; CYAN = "\033[96m"; BOLD = "\033[1m"
DIM = "\033[2m"; RESET = "\033[0m"

def header(msg): print(f"\n  {BOLD}{msg}{RESET}")
def ok(msg):     print(f"  {GREEN}✓{RESET} {msg}")
def info(msg):   print(f"  {CYAN}→{RESET} {msg}")


# ── The entire integration ────────────────────────────────────────────────────

from aaip import aaip_agent, aaip_task

# --- Option A: decorator (simplest) ---

header("Option A — @aaip_agent decorator")

@aaip_agent(tools=["web_search", "fact_check"], model="custom-model-v1")
def my_agent(task: str) -> str:
    """Your custom agent — add your logic here."""
    time.sleep(0.05)

    # Simulate tool calls
    search_results = [
        "AAIP Protocol Overview — vuneum.com",
        "Agent Trust Models 2025 — arxiv.org",
        "Zero-Trust AI Infrastructure — blog.vuneum.com",
    ]
    fact = {"verdict": "SUPPORTED", "confidence": 0.87}

    return (
        f"Research complete for: '{task}'. "
        f"Found {len(search_results)} sources. "
        f"Key finding: no major framework implements cryptographic PoE natively. "
        f"Fact check confidence: {fact['confidence']:.0%}."
    )

result = my_agent("Research AI agent trust models and verify key claims")

ok(f"Verified:   {result.verified}")
ok(f"Consensus:  {result.consensus}  ({result.approve_count}/{result.total_validators})")
ok(f"Agent ID:   {CYAN}{result.agent_id}{RESET}")
ok(f"Output:     {DIM}{result.output[:80]}...{RESET}")


# --- Option B: context manager (more control) ---

header("Option B — aaip_task context manager")

with aaip_task("Summarise quarterly performance report", validators=3) as t:
    # Step 1
    info("→ read_pdf(q3.pdf)")
    time.sleep(0.03)
    t.tool("read_pdf")

    # Step 2
    info("→ extract_tables()")
    time.sleep(0.02)
    t.tool("extract_tables")

    # Step 3
    info("→ llm.summarise()")
    time.sleep(0.05)
    t.tool("llm_summarise").model("gpt-4o")

    t.output("Revenue up 12% YoY. Enterprise subscriptions drove growth. "
             "Churn decreased to 3.2%. Recommended: expand enterprise sales team.")

ok(f"Verified:   {t.result.verified}")
ok(f"Consensus:  {t.result.consensus}")
ok(f"PoE hash:   {DIM}{t.result.poe_hash[:32]}...{RESET}")


# ── Explorer ──────────────────────────────────────────────────────────────────

header("AAIP Explorer")
r = t.result
print(f"""
  ┌──────────────────────────────────────────────────────┐
  │  Agent ID   {CYAN}{r.agent_id}{RESET}
  │  PoE hash   {DIM}{r.poe_hash[:24]}...{RESET}
  │  Signature  {DIM}{r.signature[:24]}...{RESET}
  │  Validators {GREEN}{r.approve_count}/{r.total_validators} approved{RESET}
  │  Status     {GREEN if r.verified else "\033[91m"}{r.consensus}{RESET}
  └──────────────────────────────────────────────────────┘
""")
