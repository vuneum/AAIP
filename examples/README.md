# AAIP Integration Examples

All examples run without an API key (mock execution). Install `aaip` and run directly.

```bash
pip install aaip
```

---

## langchain/

LangChain agent with AAIP PoE verification.

```bash
pip install langchain langchain-openai   # optional
python examples/langchain/agent.py
```

Demonstrates: tool recording · PoE signing · validator consensus

---

## crewai/

CrewAI crew (researcher + analyst) with AAIP verification.

```bash
pip install crewai                        # optional
python examples/crewai/crew.py
```

Demonstrates: multi-agent PoE · crew kickoff wrapping · explorer output

---

## openai_agents/

OpenAI Agents SDK agent with AAIP PoE verification.

```bash
pip install openai-agents                 # optional
python examples/openai_agents/agent.py
```

Demonstrates: function tools · PoE tracing · validator panel

---

## fraud_detection.py

Four fraud scenarios — all caught by the validator panel.

```bash
python examples/fraud_detection.py
```

Demonstrates: tampered hash · future timestamp · empty trace · invalid steps

---

## langchain_task.py

Minimal single-file LangChain + AAIP example.

```bash
python examples/langchain_task.py
```

---

## Running all examples

```bash
for f in examples/langchain/agent.py examples/crewai/crew.py examples/openai_agents/agent.py; do
    echo "=== $f ==="
    python $f
    echo
done
```
