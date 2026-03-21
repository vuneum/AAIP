"""
examples/langchain/agent.py
============================
LangChain + AAIP — full integration example.

Two approaches shown:
  1. One-liner wrapper:  aaip_langchain(your_chain)
  2. Decorator:          @aaip_agent(tools=[...], model="...")

Run:
    pip install aaip langchain langchain-openai
    export OPENAI_API_KEY=sk-...
    python agent.py

Run without API key (mock mode):
    python agent.py
"""

import os
import time

GREEN = "\033[92m"; CYAN = "\033[96m"; BOLD = "\033[1m"
DIM = "\033[2m"; RESET = "\033[0m"

def header(msg): print(f"\n  {BOLD}{msg}{RESET}")
def ok(msg):     print(f"  {GREEN}✓{RESET} {msg}")
def info(msg):   print(f"  {CYAN}→{RESET} {msg}")


# ── Approach 1: @aaip_agent decorator ────────────────────────────────────────

header("Approach 1 — @aaip_agent decorator")

from aaip import aaip_agent

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if OPENAI_KEY:
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_react_agent, AgentExecutor
    from langchain.tools import tool as lc_tool
    from langchain import hub

    @lc_tool
    def web_search(query: str) -> str:
        """Search the web for information."""
        return f"Results for '{query}': [AAIP protocol overview, agent trust models, ...]"

    @lc_tool
    def read_url(url: str) -> str:
        """Read and extract text from a URL."""
        return f"Content from {url}: AAIP provides cryptographic PoE for AI agents."

    llm    = ChatOpenAI(model="gpt-4o-mini")
    prompt = hub.pull("hwchase17/react")
    agent  = create_react_agent(llm, [web_search, read_url], prompt)
    executor = AgentExecutor(agent=agent, tools=[web_search, read_url], verbose=False)

    @aaip_agent(tools=["web_search", "read_url"], model="gpt-4o-mini")
    def research_agent(task: str) -> str:
        result = executor.invoke({"input": task})
        return result.get("output", "")

else:
    info("No OPENAI_API_KEY — using mock agent")

    @aaip_agent(tools=["web_search", "read_url"], model="gpt-4o-mini")
    def research_agent(task: str) -> str:
        time.sleep(0.1)   # simulate work
        return (f"Researched '{task}'. Found: LangChain, CrewAI, AutoGPT are the "
                f"top frameworks. None implement native cryptographic PoE. "
                f"AAIP fills this gap with ed25519-signed execution traces.")

result = research_agent("Compare top AI agent frameworks for PoE support")
ok(f"Verified:   {result.verified}")
ok(f"Consensus:  {result.consensus}  ({result.approve_count}/{result.total_validators} validators)")
ok(f"Agent ID:   {CYAN}{result.agent_id}{RESET}")
ok(f"PoE hash:   {DIM}{result.poe_hash[:32]}...{RESET}")
ok(f"Output:     {DIM}{str(result.output)[:80]}...{RESET}")


# ── Approach 2: aaip_langchain() wrapper ─────────────────────────────────────

header("Approach 2 — aaip_langchain() one-liner")

from aaip.quick import aaip_langchain

class _MockChain:
    """Minimal mock — replace with your real LangChain chain."""
    def invoke(self, inputs):
        time.sleep(0.05)
        return {"output": f"Mock chain processed: {inputs.get('input', '')}"}

chain  = aaip_langchain(_MockChain())
result = chain.invoke({"input": "Summarise the AAIP protocol"})

ok(f"Verified:  {result.verified}")
ok(f"Consensus: {result.consensus}")
ok(f"Output:    {DIM}{result.output[:60]}...{RESET}")


# ── Explorer output ───────────────────────────────────────────────────────────

header("AAIP Explorer")
print(f"""
  ┌──────────────────────────────────────────────────────┐
  │  Agent ID   {CYAN}{result.agent_id}{RESET}
  │  PoE hash   {DIM}{result.poe_hash[:24]}...{RESET}
  │  Validators {GREEN}{result.approve_count}/{result.total_validators} approved{RESET}
  │  Consensus  {GREEN if result.verified else "\033[91m"}{result.consensus}{RESET}
  └──────────────────────────────────────────────────────┘
""")
