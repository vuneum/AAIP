"""
AAIP Adapter — AutoGPT
Plug AutoGPT agents into the AAIP network.

Usage:
    from aaip.adapters.autogpt import AAIPAutoGPTAdapter

    adapter = AAIPAutoGPTAdapter(
        aaip_client=client,
        agent_id="yourco/autogpt/abc123",
    )
    # Wrap any AutoGPT task execution
    result = adapter.run_task(task="Research AI trends", output="...")
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..client import AAIPClient, AsyncAAIPClient
from ..models import AgentManifest
from ..poe import ProofOfExecution


class AAIPAutoGPTAdapter:
    """
    AAIP adapter for AutoGPT-style agents.
    AutoGPT has various versions — this adapter works at the task level
    by wrapping execution and recording PoE traces.
    """

    def __init__(
        self,
        aaip_client: AAIPClient | AsyncAAIPClient,
        agent_id: str,
        auto_evaluate: bool = True,
        auto_submit_trace: bool = True,
        domain: str = "general",
    ):
        self.aaip = aaip_client
        self.agent_id = agent_id
        self.auto_evaluate = auto_evaluate
        self.auto_submit_trace = auto_submit_trace
        self.domain = domain

    def record_task(
        self,
        task: str,
        output: str,
        commands_used: list[str] | None = None,
        thoughts: list[str] | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Record a completed AutoGPT task with PoE trace.
        Call this after your AutoGPT task finishes to register execution proof.
        """
        task_id = f"agpt-{uuid.uuid4().hex[:12]}"
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (duration_ms or 0)

        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)
        poe.trace.started_at_ms = start_ms

        with poe:
            # Record commands as tool calls
            for cmd in commands_used or []:
                poe.tool(cmd, inputs={"command": cmd}, output={})

            # Record thoughts as reasoning steps
            for thought in thoughts or []:
                poe.reason(thought)

            poe.tool(
                "autogpt_task",
                inputs={"task": task[:200]},
                output={"result": output[:200]},
                latency_ms=duration_ms or 0,
            )

        if self.auto_submit_trace and isinstance(self.aaip, AAIPClient):
            try:
                self.aaip.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        eval_result = None
        if self.auto_evaluate and isinstance(self.aaip, AAIPClient):
            try:
                eval_result = self.aaip.evaluate(
                    agent_id=self.agent_id,
                    task_description=task,
                    agent_output=output,
                    domain=self.domain,
                    trace=poe.trace,
                )
            except Exception:
                pass

        return {
            "output": output,
            "task_id": task_id,
            "poe_hash": poe.hash,
            "commands_recorded": len(commands_used or []),
            "evaluation": eval_result,
        }

    def wrap_run(self, autogpt_run_fn, task: str, **kwargs) -> dict[str, Any]:
        """
        Wrap an AutoGPT run function with automatic PoE tracking.
        Pass the function and task, get back result + trace.
        """
        task_id = f"agpt-{uuid.uuid4().hex[:12]}"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)

        with poe:
            poe.reason(f"AutoGPT starting: {task[:100]}")
            start = int(time.time() * 1000)
            output = autogpt_run_fn(task, **kwargs)
            latency = int(time.time() * 1000) - start
            poe.tool(
                "autogpt_run",
                inputs={"task": task[:200]},
                output={"result": str(output)[:200]},
                latency_ms=latency,
            )

        if self.auto_submit_trace and isinstance(self.aaip, AAIPClient):
            try:
                self.aaip.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        return {"output": output, "task_id": task_id, "poe_hash": poe.hash}


def register_autogpt_agent(
    client: AAIPClient,
    agent_name: str,
    owner: str,
    endpoint: str,
    capabilities: list[str] | None = None,
    domain: str = "general",
) -> dict:
    """Register an AutoGPT agent with AAIP."""
    manifest = AgentManifest(
        agent_name=agent_name,
        owner=owner,
        endpoint=endpoint,
        capabilities=capabilities or ["autonomous_task_execution", "web_search", "file_operations"],
        domains=[domain],
        framework="autogpt",
        tags=["autogpt", "autonomous"],
    )
    return client.register(manifest)
