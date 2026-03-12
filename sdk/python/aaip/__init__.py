"""
AAIP Python SDK — Autonomous Agent Infrastructure Protocol
https://aaip.dev

Quick start:
    pip install aaip

    from aaip import AAIPClient, AgentManifest, ProofOfExecution

    client = AAIPClient(api_key="your-key")

    # Register your agent (AAIP doesn't build it — you do)
    manifest = AgentManifest(
        agent_name="MyAgent",
        owner="YourCo",
        endpoint="https://api.yourco.com/agent",
        capabilities=["code_analysis", "translation"],
        framework="langchain",
    )
    result = client.register(manifest)
    agent_id = result["aaip_agent_id"]

    # Evaluate output with multi-model jury + PoE
    from aaip import ProofOfExecution
    with ProofOfExecution(task_id="t-001", agent_id=agent_id) as poe:
        poe.tool("search", inputs={"q": "AI trends"}, output={"results": [...]})
        poe.reason("Found 5 relevant articles")

    eval_result = client.evaluate(
        agent_id=agent_id,
        task_description="Research AI trends",
        agent_output="Here are the top AI trends in 2025...",
        trace=poe.trace,
    )
    print(f"Score: {eval_result.final_score} | Grade: {eval_result.grade}")
"""

__version__ = "1.0.0"

# ── Quick integration (10-minute onboarding) ──────────────────────────────
from .quick import AAIPResult, aaip_agent, aaip_task, verify


# ── Network client (lazy — only loaded if httpx is installed) ─────────────
def __getattr__(name):
    _lazy = {
        "AAIPClient",
        "AsyncAAIPClient",
        "AgentManifest",
        "ProofOfExecution",
        "PoETrace",
        "PoETraceStep",
        "track_tool",
    }
    if name in _lazy:
        try:
            from . import client as _c
            from . import models as _m
            from . import poe as _p

            _map = {
                "AAIPClient": _c.AAIPClient,
                "AsyncAAIPClient": _c.AsyncAAIPClient,
                "AgentManifest": _m.AgentManifest,
                "ProofOfExecution": _p.ProofOfExecution,
                "PoETrace": _m.PoETrace,
                "PoETraceStep": _m.PoETraceStep,
                "track_tool": _p.track_tool,
            }
            if name in _map:
                return _map[name]
        except ImportError:
            pass
    raise AttributeError(f"module 'aaip' has no attribute {name!r}")


__author__ = "AAIP"
__license__ = "MIT"

# Network client available when httpx is installed: from aaip.client import AAIPClient

__all__ = [
    # Clients
    "AAIPClient",
    "AsyncAAIPClient",
    # Manifest & Identity
    "AgentManifest",
    # PoE
    "PoETrace",
    "PoETraceStep",
    "ProofOfExecution",
    "track_tool",
    # Quick integration
    "AAIPResult",
    "aaip_agent",
    "aaip_task",
    "verify",
    # Evaluation
    "EvaluationRequest",
    "EvaluationResponse",
    # Discovery
    "DiscoveryResult",
    # Reputation
    "ReputationTimeline",
    # Payments
    "PaymentQuote",
    # Leaderboard
    "LeaderboardEntry",
    # Errors
    "AAIPError",
    "AuthError",
    "ValidationError",
    "NotFoundError",
    "PaymentError",
]
