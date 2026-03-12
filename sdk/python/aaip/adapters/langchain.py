"""
AAIP Adapter — LangChain
Plug your LangChain agents into the AAIP network.

Usage:
    from aaip.adapters.langchain import AAIPLangChainAgent

    agent = AAIPLangChainAgent(
        langchain_agent=your_agent,
        aaip_client=client,
        agent_id="yourco/youragent/abc123",
    )
    result = agent.run("Analyse this dataset")
    # PoE trace auto-submitted, reputation updated
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

from ..client import AAIPClient, AsyncAAIPClient
from ..models import AgentManifest, PoETrace, PoETraceStep
from ..poe import ProofOfExecution


class AAIPLangChainAgent:
    """
    Wraps any LangChain agent (AgentExecutor, Chain, Runnable)
    and adds AAIP identity, PoE tracing, and reputation submission.
    """

    def __init__(
        self,
        langchain_agent: Any,
        aaip_client: Union[AAIPClient, AsyncAAIPClient],
        agent_id: str,
        auto_evaluate: bool = True,
        auto_submit_trace: bool = True,
        domain: str = "general",
    ):
        self.agent = langchain_agent
        self.client = aaip_client
        self.agent_id = agent_id
        self.auto_evaluate = auto_evaluate
        self.auto_submit_trace = auto_submit_trace
        self.domain = domain

    def run(self, task: str, **kwargs) -> Dict[str, Any]:
        """Run the LangChain agent with AAIP PoE tracing."""
        import uuid

        task_id = f"lc-{uuid.uuid4().hex[:12]}"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)

        with poe:
            poe.reason(f"Starting LangChain agent for task: {task[:100]}")

            # Run the agent
            start = int(time.time() * 1000)
            try:
                # Support AgentExecutor, Chain, and Runnable
                if hasattr(self.agent, "invoke"):
                    result = self.agent.invoke({"input": task, **kwargs})
                    output = result.get("output", str(result))
                elif hasattr(self.agent, "run"):
                    output = self.agent.run(task, **kwargs)
                    result = {"output": output}
                else:
                    output = str(self.agent(task))
                    result = {"output": output}

                latency = int(time.time() * 1000) - start
                poe.tool("langchain_agent", inputs={"task": task[:200]}, output={"output": str(output)[:200]}, latency_ms=latency)

                # Capture intermediate steps if available
                if hasattr(result, "get") and result.get("intermediate_steps"):
                    for step in result["intermediate_steps"]:
                        action, obs = step if isinstance(step, tuple) else (step, "")
                        tool_name = getattr(action, "tool", "unknown_tool")
                        poe.tool(tool_name, inputs={"input": str(getattr(action, "tool_input", ""))[:100]}, output={"obs": str(obs)[:100]})

                poe.reason("Task completed successfully")

            except Exception as e:
                poe.trace.add_step(PoETraceStep(
                    step_type="tool_call",
                    name="langchain_agent",
                    timestamp_ms=int(time.time() * 1000),
                    status="error",
                    metadata={"error": str(e)},
                ))
                raise

        # Submit trace
        if self.auto_submit_trace and isinstance(self.client, AAIPClient):
            try:
                self.client.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass  # Non-blocking

        # Submit evaluation
        eval_result = None
        if self.auto_evaluate and isinstance(self.client, AAIPClient):
            try:
                eval_result = self.client.evaluate(
                    agent_id=self.agent_id,
                    task_description=task,
                    agent_output=str(output),
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
            "evaluation": eval_result,
        }

    async def arun(self, task: str, **kwargs) -> Dict[str, Any]:
        """Async version of run."""
        import uuid

        task_id = f"lc-{uuid.uuid4().hex[:12]}"
        poe = ProofOfExecution(task_id=task_id, agent_id=self.agent_id, task_description=task)

        async with poe:
            poe.reason(f"Starting LangChain agent: {task[:100]}")
            start = int(time.time() * 1000)

            if hasattr(self.agent, "ainvoke"):
                result = await self.agent.ainvoke({"input": task, **kwargs})
                output = result.get("output", str(result))
            elif hasattr(self.agent, "arun"):
                output = await self.agent.arun(task, **kwargs)
            else:
                output = str(self.agent(task))

            latency = int(time.time() * 1000) - start
            poe.tool("langchain_agent", inputs={"task": task[:200]}, output={"output": str(output)[:200]}, latency_ms=latency)

        if self.auto_submit_trace and isinstance(self.client, AsyncAAIPClient):
            try:
                await self.client.submit_trace(self.agent_id, poe.trace)
            except Exception:
                pass

        eval_result = None
        if self.auto_evaluate and isinstance(self.client, AsyncAAIPClient):
            try:
                eval_result = await self.client.evaluate(
                    agent_id=self.agent_id,
                    task_description=task,
                    agent_output=str(output),
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


def register_langchain_agent(
    client: AAIPClient,
    agent_name: str,
    owner: str,
    endpoint: str,
    capabilities: List[str],
    tools: Optional[List[str]] = None,
    description: str = "",
    domain: str = "general",
) -> dict:
    """
    Register a LangChain agent with AAIP.
    Automatically sets framework="langchain" in the manifest.
    """
    manifest = AgentManifest(
        agent_name=agent_name,
        owner=owner,
        endpoint=endpoint,
        description=description,
        capabilities=capabilities,
        tools=tools or [],
        domains=[domain],
        framework="langchain",
        tags=["langchain"],
    )
    return client.register(manifest)
