# CrewAI + AAIP Integration

Add AAIP verification to any CrewAI crew in minutes.

## Install

```bash
pip install aaip crewai
export OPENAI_API_KEY=sk-...
```

## Run

```bash
python crew.py
```

## What it demonstrates

1. A CrewAI crew with two agents: `researcher` and `analyst`
2. AAIP wraps the crew's `kickoff()` — recording the full task as a PoE
3. Tools used by each agent are tracked automatically
4. Validators verify the signed execution trace
5. The result is displayed with full explorer output
