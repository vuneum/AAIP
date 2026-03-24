"""
aaip/engine/execution_engine.py — Execution Engine

Simulates (or wraps real) agent tool execution.
Produces a deterministic execution trace used to generate the PoE hash.

In production: replace _run_tool() with real agent SDK calls.
The interface is stable — orchestrator.py and the API layer
call run_task() and get back a trace dict + poe_hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

log = logging.getLogger("aaip.engine.execution_engine")

# ── Tool definitions ──────────────────────────────────────────────────────────
# Each tool has a name, a description, and simulated cost in tokens.
# Replace with real tool implementations for production.

_TOOLS: list[dict[str, Any]] = [
    {"name": "retriever",  "description": "Fetching relevant documents",   "tokens": 256},
    {"name": "summariser", "description": "Extracting key information",     "tokens": 512},
    {"name": "reasoner",   "description": "Applying chain-of-thought",      "tokens": 1024},
    {"name": "formatter",  "description": "Structuring final output",       "tokens": 128},
]


def _run_tool(tool: dict[str, Any], task_input: str, fast: bool) -> dict[str, Any]:
    """
    Execute a single tool step.
    In demo mode: simulates latency. In production: call real tool.
    """
    t0 = time.monotonic()
    if not fast:
        time.sleep(0.55)
    else:
        time.sleep(0.12)

    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    log.debug("Tool %s completed in %sms", tool["name"], latency_ms)

    return {
        "tool":          tool["name"],
        "input":         task_input[:80],
        "output_tokens": tool["tokens"] + len(tool["name"]) * 3,
        # latency_ms is a runtime measurement — recorded in trace but excluded from hash
        "latency_ms":    latency_ms,
        "status":        "ok",
    }


def run_task(
    task_description: str,
    agent_id: str,
    model: str = "claude-sonnet-4-6",
    fast: bool = False,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Execute a task through the tool chain and return a signed trace.

    Args:
        task_description: Human-readable task.
        agent_id:         Executing agent identifier.
        model:            Model name recorded in the trace.
        fast:             Reduce artificial delays.
        tools:            Override default tool chain (for testing).

    Returns:
        {
          "trace":    dict — full execution trace (input to PoE hash),
          "poe_hash": str  — SHA-256 of the canonical JSON trace,
          "steps":    list — individual tool results,
        }
    """
    tool_chain  = tools or _TOOLS
    steps: list[dict] = []

    for tool in tool_chain:
        step = _run_tool(tool, task_description, fast)
        steps.append(step)

    # Deterministic fields — same logical inputs produce the same hash.
    #
    # Excluded from hash (runtime measurements, not logical inputs):
    #   - latency_ms   per-step wall-clock measurement
    #   - timestamp    wall clock at execution time
    #   - execution_id UUID unique per run
    #
    # This means: run the same task with the same agent/model/steps on any
    # machine and you get the same poe_hash — "same-input reproducibility."
    hashable_steps = [
        {k: v for k, v in step.items() if k != "latency_ms"}
        for step in steps
    ]
    deterministic_fields: dict[str, Any] = {
        "agent_id":     agent_id,
        "task":         task_description,
        "model":        model,
        "steps":        hashable_steps,
        "step_count":   len(steps),
        "total_tokens": sum(s["output_tokens"] for s in steps),
    }

    canonical = json.dumps(deterministic_fields, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    poe_hash  = "0x" + hashlib.sha256(canonical.encode()).hexdigest()

    # Full trace (for storage/audit) includes non-deterministic fields
    trace: dict[str, Any] = {
        **deterministic_fields,
        "execution_id": str(uuid.uuid4()),   # unique per run, NOT in hash
        "timestamp":    time.time(),          # wall clock, NOT in hash
    }

    log.info("Execution complete: poe_hash=%s steps=%d", poe_hash[:18], len(steps))

    return {
        "trace":    trace,
        "poe_hash": poe_hash,
        "steps":    steps,
    }


def validate_trace(trace: dict[str, Any]) -> bool:
    """
    Basic integrity check on a trace dict.
    Returns True if the trace has all required fields.
    """
    required = {"agent_id", "task", "timestamp", "steps"}
    return required.issubset(trace.keys()) and len(trace["steps"]) > 0
