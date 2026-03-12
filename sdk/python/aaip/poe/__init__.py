"""
AAIP SDK — Proof of Execution (PoE)
Utilities for generating verifiable execution traces.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable

from ..models import PoETrace, PoETraceStep


class ProofOfExecution:
    """
    Context manager for building PoE traces automatically.

    Usage:
        with ProofOfExecution(task_id="task-123", agent_id="myagent/v1") as poe:
            poe.tool("search", inputs={"q": "query"}, output=results)
            poe.reason("I found 3 relevant results")
            result = do_work()

        trace = poe.trace
        await client.submit_trace(agent_id, trace)
    """

    def __init__(self, task_id: str, agent_id: str, task_description: str = ""):
        self.trace = PoETrace(
            task_id=task_id,
            agent_id=agent_id,
            task_description=task_description,
            started_at_ms=int(time.time() * 1000),
            completed_at_ms=0,
        )
        self._active = False

    def __enter__(self):
        self._active = True
        self.trace.started_at_ms = int(time.time() * 1000)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.trace.completed_at_ms = int(time.time() * 1000)
        self._active = False
        return False  # don't suppress exceptions

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *args):
        return self.__exit__(*args)

    def tool(self, name: str, inputs: Any = None, output: Any = None, latency_ms: int = 0) -> None:
        """Record a tool call."""
        self.trace.add_tool_call(name, inputs or {}, output or {}, latency_ms)

    def reason(self, thought: str) -> None:
        """Record a reasoning step (stored as hash)."""
        self.trace.add_reasoning(thought)

    def api_call(self, endpoint: str, status: str = "success", latency_ms: int = 0) -> None:
        """Record an external API call."""
        step = PoETraceStep(
            step_type="api_call",
            name=endpoint,
            timestamp_ms=int(time.time() * 1000),
            latency_ms=latency_ms,
            status=status,
        )
        self.trace.add_step(step)

    def llm_call(self, model: str, tokens_in: int = 0, tokens_out: int = 0, latency_ms: int = 0) -> None:  # noqa: E501
        """Record an LLM inference call."""
        step = PoETraceStep(
            step_type="llm_call",
            name=model,
            timestamp_ms=int(time.time() * 1000),
            latency_ms=latency_ms,
            metadata={"tokens_in": tokens_in, "tokens_out": tokens_out},
        )
        self.trace.add_step(step)
        if "total_tokens" not in self.trace.token_usage:
            self.trace.token_usage["total_tokens"] = 0
        self.trace.token_usage["total_tokens"] = (
            self.trace.token_usage.get("total_tokens", 0) + tokens_in + tokens_out
        )

    def retrieval(self, source: str, items_found: int = 0, latency_ms: int = 0) -> None:
        """Record a retrieval/search step."""
        step = PoETraceStep(
            step_type="retrieval",
            name=source,
            timestamp_ms=int(time.time() * 1000),
            latency_ms=latency_ms,
            metadata={"items_found": items_found},
        )
        self.trace.add_step(step)

    @property
    def hash(self) -> str:
        return self.trace.compute_hash()

    @property
    def summary(self) -> dict:
        return {
            "task_id": self.trace.task_id,
            "steps": self.trace.step_count,
            "tool_calls": self.trace.total_tool_calls,
            "llm_calls": self.trace.total_llm_calls,
            "duration_ms": self.trace.duration_ms,
            "poe_hash": self.hash,
        }


def track_tool(poe: ProofOfExecution, tool_name: str | None = None):
    """
    Decorator to automatically track tool calls in a PoE trace.

    Usage:
        @track_tool(poe, "web_search")
        def search(query: str) -> list:
            ...
    """
    def decorator(func: Callable) -> Callable:
        name = tool_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = int(time.time() * 1000)
            try:
                result = func(*args, **kwargs)
                latency = int(time.time() * 1000) - start
                poe.tool(name, inputs={"args": str(args)[:100]}, output=str(result)[:100], latency_ms=latency)  # noqa: E501
                return result
            except Exception as e:
                poe.trace.add_step(PoETraceStep(
                    step_type="tool_call",
                    name=name,
                    timestamp_ms=int(time.time() * 1000),
                    status="error",
                    metadata={"error": str(e)},
                ))
                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = int(time.time() * 1000)
            try:
                result = await func(*args, **kwargs)
                latency = int(time.time() * 1000) - start
                poe.tool(name, inputs={"args": str(args)[:100]}, output=str(result)[:100], latency_ms=latency)  # noqa: E501
                return result
            except Exception as e:
                poe.trace.add_step(PoETraceStep(
                    step_type="tool_call",
                    name=name,
                    timestamp_ms=int(time.time() * 1000),
                    status="error",
                    metadata={"error": str(e)},
                ))
                raise

        import asyncio
        return async_wrapper if asyncio.iscoroutinefunction(func) else wrapper
    return decorator
