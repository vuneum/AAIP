# OpenAI Agents SDK + AAIP Integration

Attach AAIP verification to any OpenAI Agents SDK agent.

## Install

```bash
pip install aaip openai-agents
export OPENAI_API_KEY=sk-...
```

## Run

```bash
python agent.py
```

## What it demonstrates

1. OpenAI Agents SDK agent with two tools: `web_search` and `code_runner`
2. Each tool call is recorded in the AAIP PoE trace
3. The final output is hashed and signed by the agent's ed25519 key
4. A local validator panel verifies the trace
5. Full explorer output shows the signed PoE object and validator votes
