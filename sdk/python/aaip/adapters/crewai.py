"""
AAIP Adapter — CrewAI
Plug your CrewAI agents and crews into the AAIP network.

Usage:
    from aaip.adapters.crewai import AAIPCrewAdapter

    adapter = AAIPCrewAdapter(
        crew=my_crew,
        aaip_client=client,
        agent_id="yourco/crew/abc123",
    )
    result = adapter.kickoff(inputs={"topic": "AI trends"})
    # PoE trace and reputation auto-submitted
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..client import AAIPClient, AsyncAAIPClient
from ..models import AgentManifest, PoETraceStep
from ..poe import ProofOfExecution


class AAIPCrewAdapter:
    """
    Wraps a CrewAI Crew with AAIP PoE tracing and reputation submission.
    Works with any Crew that has a .kickoff() method.
    """

    def __init__(
        self,
        crew: Any,
        aaip_client: AAIPClient | AsyncAAIPClient,
        agent_id: str,
        auto_evaluate: bool = True,
        auto_submit_trace: bool = True,
        domain: str = "general",
    ):
        self.crew = crew
        self.client = aaip_client
        self.agent_id = agent_id
        self.auto_evaluate = auto_evaluate
        self.auto_submit_trace = auto_submit_trace
        self.domain = domain

    def kickoff(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the CrewAI crew with AAIP PoE tracing."""
        task_id = f"crew-{uuid.uuid4().hex[:12]}"
        task_desc = str(inputs) if inputs else "CrewAI task execution"

        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task_desc)

        with poe:
            poe.reason(f"CrewAI kickoff with inputs: {str(inputs)[:200]}")

            # Record each agent in the crew as a tool call
            if hasattr(self.crew, "agents"):
                for agent in self.crew.agents:
                    agent_role = getattr(agent, "role", "agent")
                    poe.tool(f"crew_agent:{agent_role}", inputs={"role": agent_role})

            # Record tasks
            if hasattr(self.crew, "tasks"):
                for task in self.crew.tasks:
                    task_desc_short = getattr(task, "description", "")[:100]
                    poe.reason(f"Task queued: {task_desc_short}")

            start = int(time.time() * 1000)
            try:
                raw_result = self.crew.kickoff(inputs=inputs or {})
                latency = int(time.time() * 1000) - start
                output = str(raw_result)
                poe.tool("crewai_execution", inputs={"inputs": str(inputs)[:200]}, output={"result": output[:200]}, latency_ms=latency)
                poe.reason("Crew completed all tasks successfully")
            except Exception as e:
                poe.trace.add_step(PoETraceStep(
                    step_type="tool_call",
                    name="crewai_execution",
                    timestamp_ms=int(time.time() * 1000),
                    status="error",
                    metadata={"error": str(e)},
                ))
                raise

        if self.auto_submit_trace and isinstance(self.client, AAIPClient):
            try:
                self.client.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        eval_result = None
        if self.auto_evaluate and isinstance(self.client, AAIPClient):
            try:
                eval_result = self.client.evaluate(
                    agent_id=self.agent_id,
                    task_description=task_desc,
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
            "poe_steps": poe.trace.step_count,
            "agents_used": len(getattr(self.crew, "agents", [])),
            "tasks_executed": len(getattr(self.crew, "tasks", [])),
            "evaluation": eval_result,
        }

    async def akickoff(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Async kickoff for CrewAI async crews."""
        task_id = f"crew-{uuid.uuid4().hex[:12]}"
        task_desc = str(inputs) if inputs else "CrewAI async task"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task_desc)

        async with poe:
            start = int(time.time() * 1000)
            if hasattr(self.crew, "akickoff"):
                raw_result = await self.crew.akickoff(inputs=inputs or {})
            else:
                raw_result = self.crew.kickoff(inputs=inputs or {})
            latency = int(time.time() * 1000) - start
            output = str(raw_result)
            poe.tool("crewai_execution", inputs={"inputs": str(inputs)[:200]}, output={"result": output[:200]}, latency_ms=latency)

        if self.auto_submit_trace and isinstance(self.client, AsyncAAIPClient):
            try:
                await self.client.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        return {"output": output, "task_id": task_id, "poe_hash": poe.hash}


def register_crew(
    client: AAIPClient,
    crew: Any,
    agent_name: str,
    owner: str,
    endpoint: str,
    capabilities: list[str] | None = None,
    domain: str = "general",
) -> dict:
    """
    Register a CrewAI crew with AAIP.
    Automatically extracts capabilities from crew agents' roles.
    """
    # Auto-extract capabilities from agent roles
    auto_caps = []
    if hasattr(crew, "agents"):
        for agent in crew.agents:
            role = getattr(agent, "role", "")
            if role:
                auto_caps.append(role.lower().replace(" ", "_"))

    manifest = AgentManifest(
        agent_name=agent_name,
        owner=owner,
        endpoint=endpoint,
        capabilities=capabilities or auto_caps,
        domains=[domain],
        framework="crewai",
        tags=["crewai", "multi-agent"],
        metadata={"agent_count": len(getattr(crew, "agents", []))},
    )
    return client.register(manifest)
