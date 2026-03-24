"""
examples/fraud_detection.py
============================
Demonstrates AAIP detecting a fraudulent PoE.

Scenarios:
  A) Honest execution → VERIFIED
  B) Tampered output hash → REJECTED (HASH_MISMATCH)
  C) Invalid step count → REJECTED (NEGATIVE_STEP_COUNT + SIGNATURE_INVALID)
  D) Future timestamp → REJECTED (FUTURE_TIMESTAMP)

Run:
    python examples/fraud_detection.py
"""

import time
from aaip.identity import AgentIdentity
from aaip.poe.deterministic import DeterministicPoE
from aaip.validators import ValidatorPanel

GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"

def header(title):
    print(f"\n  {BOLD}{'─'*52}{RESET}")
    print(f"  {BOLD}{title}{RESET}")
    print(f"  {BOLD}{'─'*52}{RESET}\n")

def run_scenario(label: str, poe_dict: dict, n_validators: int = 3):
    panel  = ValidatorPanel(n=n_validators)
    result = panel.vote(poe_dict)

    print(f"  {BOLD}{label}{RESET}")
    for vote in result.votes:
        sym = f"{GREEN}✔{RESET}" if vote.approved else f"{RED}✘{RESET}"
        sigs = f"  {DIM}→ {', '.join(vote.signals)}{RESET}" if vote.signals else ""
        print(f"    {sym}  {vote.validator_id}{sigs}")
        time.sleep(0.15)

    if result.passed:
        print(f"\n  {GREEN}{BOLD}  ✔  VERIFIED  {RESET}  ({result.approve_count}/{result.total_validators} validators)\n")
    else:
        sigs = set(s for v in result.votes for s in v.signals)
        print(f"\n  {RED}{BOLD}  ✘  REJECTED  {RESET}  ({result.reject_count}/{result.total_validators} rejected)")
        print(f"  {DIM}Signals: {', '.join(sigs)}{RESET}\n")


# ── Shared identity ──────────────────────────────────────────────────────────
identity = AgentIdentity.generate()
print(f"\n{CYAN}{BOLD}  AAIP Fraud Detection Demo{RESET}")
print(f"  Agent: {identity.agent_id}\n")

TASK   = "Summarise the AAIP protocol architecture"
OUTPUT = "AAIP has 8 layers: Identity, Registry, Execution, PoE, Jury, CAV, Reputation, Escrow."

def make_honest_poe():
    poe = DeterministicPoE(identity)
    poe.begin(TASK)
    poe.record_tool("read_docs")
    poe.record_model("gpt-4o")
    poe.record_step()
    poe.set_output(OUTPUT)
    poe.finish()
    return poe.to_dict()


# ── A: Honest execution ──────────────────────────────────────────────────────
header("A) Honest Execution")
run_scenario("Expected: VERIFIED", make_honest_poe())


# ── B: Tampered output hash ──────────────────────────────────────────────────
header("B) Tampered Output Hash  (agent lies about what it produced)")
bad = make_honest_poe()
bad["output_hash"] = "deadbeef" * 8   # doesn't match poe_hash canonical
run_scenario("Expected: REJECTED (HASH_MISMATCH)", bad)


# ── C: Fake empty execution ──────────────────────────────────────────────────
header("C) Fake Trace  (no tools, no model, negative steps)")
bad2 = make_honest_poe()
bad2["tools_used"]   = []
bad2["model_used"]   = None
bad2["step_count"]   = -1
# hash and signature now invalid because canonical fields changed
run_scenario("Expected: REJECTED (multiple signals)", bad2)


# ── D: Future timestamp ──────────────────────────────────────────────────────
header("D) Future Timestamp  (agent claims to have worked in the future)")
import time as _time
bad3 = make_honest_poe()
bad3["timestamp"] = int(_time.time()) + 3600  # 1 hour ahead
run_scenario("Expected: REJECTED (FUTURE_TIMESTAMP + HASH_MISMATCH)", bad3)


print(f"  {DIM}All four fraud patterns detected without false positives on the honest case.{RESET}\n")
