# Contributing to AAIP

Thank you for your interest in contributing to the Autonomous Agent Infrastructure Protocol. AAIP is an open protocol and all contributions — code, docs, examples, research — are welcome.

---

## Table of Contents

1. [Ways to Contribute](#ways-to-contribute)
2. [Development Setup](#development-setup)
3. [Project Structure](#project-structure)
4. [Submitting Changes](#submitting-changes)
5. [Code Style](#code-style)
6. [Adding Examples](#adding-examples)
7. [SDK Contributions](#sdk-contributions)
8. [Reporting Bugs](#reporting-bugs)
9. [Security Vulnerabilities](#security-vulnerabilities)

---

## Ways to Contribute

- **Bug fixes** — open an issue first for larger bugs
- **New examples** — show AAIP working with your framework
- **SDK improvements** — better error messages, new adapters, performance
- **Documentation** — typos, clarifications, new guides
- **Protocol discussion** — open a GitHub Discussion for spec-level questions
- **Attack simulations** — add new attack scenarios to `simulation_lab/`
- **Research** — analysis of economic security, ZK PoE, TEE integration

---

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend development)
- pnpm (for frontend)
- PostgreSQL (optional — only for backend development)

### Python SDK

```bash
git clone https://github.com/vuneum/aaip
cd aaip/sdk/python
pip install -e ".[dev]"   # installs with test and dev deps

# Run tests
pytest tests/ -v

# Run the demo locally
PYTHONPATH=. python -m aaip.cli demo
```



### Backend (optional)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn main:app --reload
```

---

## Project Structure

```
aaip/
├── sdk/python/aaip/
│   ├── identity/       Keypair generation, agent_id derivation
│   ├── poe/            PoE construction and verification
│   │   ├── __init__.py       Context manager API (ProofOfExecution)
│   │   └── deterministic.py  DeterministicPoE + PoEVerifier
│   ├── validators/     Local validator simulation
│   ├── cli/            Click CLI commands
│   ├── adapters/       Framework integrations
│   │   ├── langchain.py
│   │   ├── crewai.py
│   │   ├── autogpt.py
│   │   └── openai_agents.py
│   ├── client.py       API client
│   └── models.py       Pydantic models
├── backend/            FastAPI — registry, evaluation, CAV, payments
├── examples/           Runnable integration examples
├── simulation_lab/     Attack and economic simulations
└── docs/               Protocol documentation
```

---

## Submitting Changes

1. **Fork** the repository
2. **Create a branch**: `git checkout -b feature/your-feature-name`
3. **Write tests** for new functionality
4. **Run tests**: `pytest tests/ -v`
5. **Update docs** if your change affects behaviour or API
6. **Open a PR** with a clear description

### PR Checklist

- [ ] Tests pass locally
- [ ] New code has docstrings
- [ ] Docs updated if behaviour changed
- [ ] `CHANGELOG.md` updated (add entry under `[Unreleased]`)
- [ ] No secrets or API keys in code

### Commit Message Format

```
type(scope): short description

Longer explanation if needed.
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

Examples:
```
feat(cli): add aaip simulate --scenario collusion
fix(poe): sort tools_used before hashing to ensure determinism
docs(security): add validator collusion attack analysis
```

---

## Code Style

### Python

- Follow PEP 8
- Type hints on all public functions
- Docstrings on all public classes and methods
- Max line length: 100 characters
- Use `f-strings`, not `.format()` or `%`

```python
def verify(self, poe_dict: dict) -> VerificationResult:
    """
    Verify a signed PoE object.

    Parameters
    ----------
    poe_dict : dict
        The full PoE object including poe_hash, signature, and public_key.

    Returns
    -------
    VerificationResult
        Contains verdict, signals, and per-check booleans.
    """
```

### TypeScript / React

- Use functional components with hooks
- Explicit types — no `any`
- Tailwind for styling, no inline styles
- Named exports preferred over default for non-pages

---

## Adding Examples

Examples live in `examples/<framework>/`. Each example directory needs:

```
examples/your_framework/
├── README.md     # Setup, run instructions, expected output
└── agent.py      # Runnable example (or index.ts for TS)
```

**Requirements for a good example:**
- Works without an API key (mock/fallback mode)
- Shows the full AAIP flow: identity → PoE → validators → result
- Prints explorer-style output at the end
- Has clear comments explaining each AAIP step

Copy `examples/langchain/agent.py` as a starting template.

---

## SDK Contributions

### Adding a new framework adapter

Create `sdk/python/aaip/adapters/your_framework.py`:

```python
"""
AAIP adapter for YourFramework.

Automatically records tool calls and model usage in the PoE trace.
"""
from aaip.poe.deterministic import DeterministicPoE

class AAIPYourFrameworkCallback:
    """Callback/hook that records execution into a PoE trace."""

    def __init__(self, poe: DeterministicPoE):
        self.poe = poe

    def on_tool_start(self, tool_name: str, **kwargs):
        self.poe.record_tool(tool_name)

    def on_llm_start(self, model_name: str, **kwargs):
        self.poe.record_model(model_name)
```

Then add it to `sdk/python/aaip/adapters/__init__.py`.

### Adding a new language SDK

New SDKs go in `sdk/<language>/`. At minimum implement:

1. **Identity** — keypair generation + agent_id derivation
2. **PoE** — canonical JSON construction + sha256 hash
3. **Signature** — ed25519 sign + verify
4. **Validator** — local simulation with 3 validators + 2/3 consensus

Reference: `sdk/python/aaip/` for the canonical implementation.

---

## Reporting Bugs

Open a [GitHub Issue](https://github.com/vuneum/aaip/issues/new) with:

- **Title**: Short description of the bug
- **Environment**: OS, Python version, aaip version (`aaip --version`)
- **Steps to reproduce**: Minimal code to trigger the bug
- **Expected behaviour**
- **Actual behaviour**
- **Logs / traceback** if applicable

---

## Security Vulnerabilities

**Do not open public GitHub issues for security vulnerabilities.**

Email: **walid@vuneum.com**

Include:
- Vulnerability description
- Steps to reproduce
- Estimated severity
- Suggested fix (if any)

We respond within 48 hours and credit researchers in release notes.

---

## Code of Conduct

Be respectful. Contributions are reviewed on technical merit. Harassment, personal attacks, or discriminatory language will not be tolerated and may result in a ban.

---

*AAIP — MIT License — vuneum.com*
