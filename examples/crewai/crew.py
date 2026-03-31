"""
examples/crewai/crew.py
========================
CrewAI + AAIP — one-line integration.

Two approaches:
  1. aaip_crewai(your_crew) — wrap existing crew
  2. @aaip_agent             — wrap any function

Run:
    pip install aaip crewai
    python crew.py

Run without crewai installed (mock mode):
    python crew.py
"""

import time

GREEN = "\033[92m"; CYAN = "\033[96m"; BOLD = "\033[1m"
DIM = "\033[2m"; RESET = "\033[0m"

def header(msg): print(f"\n  {BOLD}{msg}{RESET}")
def ok(msg):     print(f"  {GREEN}✓{RESET} {msg}")
def info(msg):   print(f"  {CYAN}→{RESET} {msg}")


# ── Approach 1: aaip_crewai() wrapper ────────────────────────────────────────

header("Approach 1 — aaip_crewai() one-liner")

from aaip.quick import aaip_crewai

try:
    from crewai import Agent, Task, Crew, Process
    from langchain_openai import ChatOpenAI

    researcher = Agent(
        role="AI Researcher",
        goal="Research and summarise AI agent frameworks",
        llm=ChatOpenAI(model="gpt-4o-mini"),
        verbose=False,
    )
    writer = Agent(
        role="Technical Writer",
        goal="Write clear summaries of technical research",
        llm=ChatOpenAI(model="gpt-4o-mini"),
        verbose=False,
    )
    task = Task(
        description="Research the top AI agent frameworks and compare their PoE support",
        agent=researcher,
        expected_output="A comparison of LangChain, CrewAI, AutoGPT on PoE capabilities",
    )
    crew = Crew(agents=[researcher, writer], tasks=[task], process=Process.sequential)

    info("Running real CrewAI crew...")
    aaip_crew = aaip_crewai(crew)
    result = aaip_crew.kickoff(inputs={"topic": "AI agent PoE comparison"})

except ImportError:
    info("crewai not installed — using mock crew")

    class _MockCrew:
        agents = [type("A", (), {"role": "AI Researcher"})(),
                  type("A", (), {"role": "Technical Writer"})()]
        def kickoff(self, inputs=None, **kw):
            time.sleep(0.1)
            return type("R", (), {"raw": (
                "Comparison: LangChain has 0 PoE support. CrewAI has 0. "
                "AutoGPT has 0. AAIP adds cryptographic PoE to all three."
            )})()

    aaip_crew = aaip_crewai(_MockCrew())
    result = aaip_crew.kickoff(inputs={"topic": "AI agent PoE comparison"})

ok(f"Verified:   {result.verified}")
ok(f"Consensus:  {result.consensus}  ({result.approve_count}/{result.total_validators} validators)")
ok(f"Agent ID:   {CYAN}{result.agent_id}{RESET}")
ok(f"Output:     {DIM}{str(result.output)[:80]}...{RESET}")


# ── Approach 2: @aaip_agent on a crew wrapper function ───────────────────────

header("Approach 2 — @aaip_agent decorator")

from aaip import aaip_agent

@aaip_agent(tools=["crewai_research", "crewai_write"], model="gpt-4o-mini")
def run_research_crew(task: str) -> str:
    time.sleep(0.05)
    return (f"CrewAI analysis of '{task}': "
            f"Found that no major framework implements native cryptographic PoE. "
            f"AAIP is the only protocol providing ed25519-signed execution traces.")

result2 = run_research_crew("AI agent trust and verification landscape")
ok(f"Verified:  {result2.verified}")
ok(f"Consensus: {result2.consensus}")
ok(f"Hash:      {DIM}{result2.poe_hash[:24]}...{RESET}")


header("AAIP Explorer")
print(f"""
  ┌──────────────────────────────────────────────────────┐
  │  Agent ID   {CYAN}{result2.agent_id}{RESET}
  │  PoE hash   {DIM}{result2.poe_hash[:24]}...{RESET}
  │  Validators {GREEN}{result2.approve_count}/{result2.total_validators} approved{RESET}
  │  Status     {GREEN if result2.verified else "\033[91m"}{result2.consensus}{RESET}
  └──────────────────────────────────────────────────────┘
""")
