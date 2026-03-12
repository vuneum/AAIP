# OpenClaw — Minimal AAIP Agent Example

OpenClaw is a zero-dependency example showing how to integrate AAIP into a **custom agent built from scratch** — no LangChain, no CrewAI, no framework required.

## Why OpenClaw?

If you're building your own agent loop, OpenClaw shows you exactly where to add AAIP hooks:

1. Generate identity once at startup
2. Wrap your tool calls with `poe.record_tool()`
3. Record the model with `poe.record_model()`
4. Call `poe.finish()` after task completion
5. Submit to validators

## Run

```bash
pip install aaip
python examples/openclaw/agent.py
```

No API key or network connection required. All execution is local.

## Expected Output

```
  1. Agent Identity
  ✓ Agent ID:   8f21d3a4b7c91e2f
  ✓ Public key: 1b6f8973f56032ef...

  2. Custom Tools
  ✓ web_search()
  ✓ summarise()
  ✓ fact_check()

  3. Task Execution
  → Task: Research current AI agent trust models...
  → web_search('AI agent trust models 2025')
  ✓ Found 3 results
  → summarise(results)
  ✓ Summary: AAIP Protocol Overview Agent Trust Models...
  → fact_check('No major framework...')
  ✓ Verdict: SUPPORTED (confidence 87%)
  ✓ PoE hash:  e461cfc7a318fbc9...
  ✓ Signature: 3b664f1beb4b3dcd...

  4. Validator Consensus  (3 validators, threshold ≥ 2/3)
    ✔  validator_1  stake=100  hash_ok=True
    ✔  validator_2  stake=125  hash_ok=True
    ✔  validator_3  stake=150  hash_ok=True

  Consensus: 3/3 approve (threshold ≥ 67%)

  5. AAIP Explorer
  ┌──────────────────────────────────────────────────────┐
  │  Task ID   e461cfc7a318...
  │  Agent     8f21d3a4b7c91e2f
  │  ...
  │  Status  VERIFIED ✔
  │  Escrow  Released
  └──────────────────────────────────────────────────────┘

  Consensus reached. Task verified.
```

## Key Integration Points

```python
from aaip.identity import AgentIdentity
from aaip.poe.deterministic import DeterministicPoE
from aaip.validators import ValidatorPanel

# Startup: load or create identity
identity = AgentIdentity.load_or_create()

# Per task: build PoE
poe = DeterministicPoE(identity)
poe.begin("Your task description")

# During execution: record steps
result1 = my_tool_1(args)
poe.record_tool("my_tool_1")

result2 = call_llm(prompt)
poe.record_model("your-model-name")

# After execution: finalise + verify
poe.set_output(final_output)
poe.finish()

panel = ValidatorPanel(n=3)
consensus = panel.vote(poe.to_dict())
print(consensus.consensus)  # "APPROVED" or "REJECTED"
```
