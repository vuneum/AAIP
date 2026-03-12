"""
AAIP Adapter — OpenAI Agents SDK
Plug OpenAI Agents (Swarm / Agents SDK) into the AAIP network.

Usage:
    from aaip.adapters.openai_agents import AAIPOpenAIAgent

    agent = AAIPOpenAIAgent(
        openai_agent=my_agent,
        aaip_client=client,
        agent_id="yourco/agent/abc123",
    )
    result = agent.run("Summarise this document")
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..client import AAIPClient, AsyncAAIPClient
from ..models import AgentManifest, PoETraceStep
from ..poe import ProofOfExecution


class AAIPOpenAIAgent:
    """
    Wraps an OpenAI Agents SDK agent with AAIP PoE tracing.
    Compatible with openai-agents (Swarm successor) and function-calling agents.
    """

    def __init__(
        self,
        openai_agent: Any,
        aaip_client: AAIPClient | AsyncAAIPClient,
        agent_id: str,
        client: Any = None,          # openai.OpenAI client
        auto_evaluate: bool = True,
        auto_submit_trace: bool = True,
        domain: str = "general",
    ):
        self.agent = openai_agent
        self.aaip = aaip_client
        self.openai_client = client
        self.agent_id = agent_id
        self.auto_evaluate = auto_evaluate
        self.auto_submit_trace = auto_submit_trace
        self.domain = domain

    def run(self, task: str, context_variables: dict | None = None, **kwargs) -> dict[str, Any]:
        """Run the OpenAI agent with AAIP PoE tracing."""
        task_id = f"oai-{uuid.uuid4().hex[:12]}"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)
        output = ""

        with poe:
            poe.reason(f"Starting OpenAI agent: {task[:100]}")

            start = int(time.time() * 1000)
            try:
                # Try openai-agents SDK (new)
                if hasattr(self.agent, "run"):
                    from openai import OpenAI
                    openai_client = self.openai_client or OpenAI()
                    result = openai_client.beta.threads.create_and_run(
                        assistant_id=getattr(self.agent, "id", ""),
                        thread={"messages": [{"role": "user", "content": task}]},
                    ) if hasattr(openai_client, "beta") else self.agent.run(task)
                    output = str(result)

                # Try Swarm-style run
                elif hasattr(self.agent, "__call__"):
                    result = self.agent(task, **(context_variables or {}))
                    output = str(result)
                else:
                    output = str(self.agent)

                latency = int(time.time() * 1000) - start
                poe.tool("openai_agent", inputs={"task": task[:200]}, output={"result": output[:200]}, latency_ms=latency)

                # Capture tool calls if available
                if hasattr(result, "messages"):
                    for msg in result.messages:
                        if getattr(msg, "role", "") == "tool":
                            poe.tool(
                                getattr(msg, "name", "tool"),
                                inputs={},
                                output={"content": str(getattr(msg, "content", ""))[:100]},
                            )

                poe.reason("OpenAI agent completed successfully")

            except Exception as e:
                poe.trace.add_step(PoETraceStep(
                    step_type="tool_call",
                    name="openai_agent",
                    timestamp_ms=int(time.time() * 1000),
                    status="error",
                    metadata={"error": str(e)},
                ))
                raise

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
            "evaluation": eval_result,
        }

    async def arun(self, task: str, **kwargs) -> dict[str, Any]:
        """Async version."""
        task_id = f"oai-{uuid.uuid4().hex[:12]}"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)

        async with poe:
            start = int(time.time() * 1000)
            if hasattr(self.agent, "arun"):
                result = await self.agent.arun(task, **kwargs)
            else:
                result = self.agent.run(task, **kwargs) if hasattr(self.agent, "run") else str(self.agent)
            output = str(result)
            latency = int(time.time() * 1000) - start
            poe.tool("openai_agent", inputs={"task": task[:200]}, output={"result": output[:200]}, latency_ms=latency)

        if isinstance(self.aaip, AsyncAAIPClient):
            try:
                await self.aaip.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        return {"output": output, "task_id": task_id, "poe_hash": poe.hash}


def register_openai_agent(
    client: AAIPClient,
    agent_name: str,
    owner: str,
    endpoint: str,
    capabilities: list[str],
    tools: list[str] | None = None,
    domain: str = "general",
    model: str = "gpt-4o",
) -> dict:
    """Register an OpenAI Agents SDK agent with AAIP."""
    manifest = AgentManifest(
        agent_name=agent_name,
        owner=owner,
        endpoint=endpoint,
        capabilities=capabilities,
        tools=tools or [],
        domains=[domain],
        framework="openai_agents",
        tags=["openai", "gpt"],
        metadata={"model": model},
    )
    return client.register(manifest)
