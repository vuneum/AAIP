# LangChain + AAIP Integration

Wrap any LangChain agent with AAIP verification in 3 lines.

## Install

```bash
pip install aaip langchain langchain-openai
export OPENAI_API_KEY=sk-...
```

## Run

```bash
# Full example with PoE + local validator consensus
python agent.py

# Works without an API key (mock execution)
python agent.py
```

## What it demonstrates

1. Agent identity auto-generated on first run
2. LangChain tool calls recorded in PoE trace
3. 3 local validators verify the signed PoE
4. Explorer-style output: task · agent · hash · verdict
