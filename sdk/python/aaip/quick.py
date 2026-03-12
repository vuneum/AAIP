"""
aaip.quick — Zero-friction AAIP integration.

The entire integration in 3 lines:

    from aaip.quick import aaip_agent, verify

    @aaip_agent
    def run(task: str) -> str:
        ...your agent logic...

    result = run("Analyse AI frameworks")
    print(result.verified)   # True
    print(result.agent_id)   # "8f21d3a4..."

Framework-specific (one line each):

    # LangChain
    chain = aaip_langchain(your_chain)
    result = chain.invoke({"input": "your task"})

    # CrewAI
    crew = aaip_crewai(your_crew)
    result = crew.kickoff(inputs={"topic": "AI"})

    # Any callable
    @aaip_agent
    def my_agent(task): ...
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable
from .identity import AgentIdentity

# ---------------------------------------------------------------------------
# Result object returned from every aaip-wrapped call
# ---------------------------------------------------------------------------


@dataclass
class AAIPResult:
    """Returned from every aaip-wrapped agent call."""

    output: Any
    agent_id: str
    poe_hash: str
    signature: str
    verified: bool
    consensus: str  # "APPROVED" or "REJECTED"
    approve_count: int
    total_validators: int
    signals: list[str] = field(default_factory=list)
    shadow: bool = False  # True = observation only, never blocks

    def __str__(self):
        mode = " [shadow]" if self.shadow else ""
        status = "✔ VERIFIED" if self.verified else "✘ REJECTED"
        return (
            f"[AAIP {status}{mode}] agent={self.agent_id} "
            f"validators={self.approve_count}/{self.total_validators} "
            f"hash={self.poe_hash[:12]}..."
        )

    def __repr__(self):
        return self.__str__()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_identity() -> AgentIdentity:  # noqa: F821
    """Load or create agent identity (cached per process)."""
    from .identity import AgentIdentity

    return AgentIdentity.load_or_create()


def _build_and_verify(
    identity: AgentIdentity,
    task: str,
    output: Any,  # noqa: F821
    tools: list[str],
    model: str | None,
    n_validators: int = 3,
) -> AAIPResult:
    """Build PoE, run validators, return AAIPResult."""
    from .poe.deterministic import DeterministicPoE
    from .validators import ValidatorPanel

    output_str = str(output)
    poe = DeterministicPoE(identity)
    poe.begin(task)
    for tool in tools:
        poe.record_tool(tool)
    if model:
        poe.record_model(model)
    poe.set_output(output_str)
    poe.finish()

    poe_dict = poe.to_dict()
    result = ValidatorPanel(n=n_validators).vote(poe_dict)

    all_signals = []
    for vote in result.votes:
        all_signals.extend(vote.signals)

    return AAIPResult(
        output=output,
        agent_id=identity.agent_id,
        poe_hash=poe_dict["poe_hash"],
        signature=poe_dict["signature"],
        verified=result.passed,
        consensus=result.consensus,
        approve_count=result.approve_count,
        total_validators=result.total_validators,
        signals=list(set(all_signals)),
    )


# ---------------------------------------------------------------------------
# @aaip_agent decorator — wraps any callable
# ---------------------------------------------------------------------------


def aaip_agent(
    func: Callable | None = None,
    *,
    tools: list[str] | None = None,
    model: str | None = None,
    validators: int = 3,
    task_arg: str = "task",
    shadow: bool = False,
):
    """
    Decorator that wraps any agent function with AAIP verification.

    Usage:
        @aaip_agent
        def run(task: str) -> str:
            return "result"

        result = run("my task")
        print(result.verified)   # True
        print(result.output)     # "result"

    With options:
        @aaip_agent(tools=["web_search"], model="gpt-4o", validators=5)
        def run(task: str) -> str:
            ...

    Shadow mode — verify without blocking:
        @aaip_agent(shadow=True)
        def run(task: str) -> str:
            ...

        result = run("my task")
        print(result.output)     # original output — always returned
        print(result.verified)   # True/False — for auditing only
        print(result.signals)    # fraud signals detected, if any
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            identity = _get_identity()
            _tools = tools or []
            _model = model

            # Extract task string from first positional arg or task_arg kwarg
            if args:
                task_str = str(args[0])
            elif task_arg in kwargs:
                task_str = str(kwargs[task_arg])
            else:
                task_str = fn.__name__

            output = fn(*args, **kwargs)
            # Auto-record function name as tool if nothing was specified
            effective_tools = _tools if _tools else [fn.__name__]

            if shadow:
                # Shadow mode: run verification but never raise or block.
                # Always return the original output wrapped in AAIPResult.
                try:
                    result = _build_and_verify(
                        identity, task_str, output, effective_tools, _model, validators
                    )
                    result.shadow = True
                    return result
                except Exception:
                    # Verification failure must never affect the agent's output
                    return AAIPResult(
                        output=output,
                        agent_id=identity.agent_id,
                        poe_hash="",
                        signature="",
                        verified=False,
                        consensus="SHADOW_ERROR",
                        approve_count=0,
                        total_validators=validators,
                        signals=["SHADOW_VERIFICATION_ERROR"],
                        shadow=True,
                    )

            return _build_and_verify(
                identity, task_str, output, effective_tools, _model, validators
            )

        wrapper.aaip = True
        wrapper.shadow = shadow
        return wrapper

    if func is not None:
        # Called as @aaip_agent (no parens)
        return decorator(func)
    # Called as @aaip_agent(...) with options
    return decorator


# ---------------------------------------------------------------------------
# aaip_task context manager — manual tool recording
# ---------------------------------------------------------------------------


class aaip_task:
    """
    Context manager for manual tool recording.

    Usage:
        with aaip_task("Research AI trends") as t:
            results = web_search("AI trends 2025")
            t.tool("web_search")
            t.model("gpt-4o")
            output = summarise(results)

        print(t.result.verified)
    """

    def __init__(self, task: str, validators: int = 3, shadow: bool = False):
        self._task = task
        self._validators = validators
        self._shadow = shadow
        self._tools: list[str] = []
        self._model: str | None = None
        self._output: Any = None
        self.result: AAIPResult | None = None

    def tool(self, name: str) -> aaip_task:
        self._tools.append(name)
        return self

    def model(self, name: str) -> aaip_task:
        self._model = name
        return self

    def output(self, value: Any) -> aaip_task:
        self._output = value
        return self

    def __enter__(self) -> aaip_task:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            return False
        identity = _get_identity()
        if self._shadow:
            try:
                self.result = _build_and_verify(
                    identity,
                    self._task,
                    self._output or "",
                    self._tools,
                    self._model,
                    self._validators,
                )
                self.result.shadow = True
            except Exception:
                self.result = AAIPResult(
                    output=self._output,
                    agent_id=identity.agent_id,
                    poe_hash="",
                    signature="",
                    verified=False,
                    consensus="SHADOW_ERROR",
                    approve_count=0,
                    total_validators=self._validators,
                    signals=["SHADOW_VERIFICATION_ERROR"],
                    shadow=True,
                )
        else:
            self.result = _build_and_verify(
                identity, self._task, self._output or "", self._tools, self._model, self._validators
            )
        return False


# ---------------------------------------------------------------------------
# verify() — verify any poe_dict directly
# ---------------------------------------------------------------------------


def verify(poe_dict: dict, validators: int = 3) -> AAIPResult:
    """
    Verify an existing PoE dict.

    Usage:
        result = verify(poe.to_dict())
        print(result.verified)
    """
    from .validators import ValidatorPanel

    panel = ValidatorPanel(n=validators)
    result = panel.vote(poe_dict)

    all_signals = []
    for vote in result.votes:
        all_signals.extend(vote.signals)

    identity = _get_identity()

    return AAIPResult(
        output=poe_dict.get("output_hash", ""),
        agent_id=poe_dict.get("agent_id", identity.agent_id),
        poe_hash=poe_dict.get("poe_hash", ""),
        signature=poe_dict.get("signature", ""),
        verified=result.passed,
        consensus=result.consensus,
        approve_count=result.approve_count,
        total_validators=result.total_validators,
        signals=list(set(all_signals)),
    )


# ---------------------------------------------------------------------------
# Framework one-liners
# ---------------------------------------------------------------------------


def aaip_langchain(chain: Any, validators: int = 3) -> Any:
    """
    Wrap any LangChain chain/agent with AAIP verification.

    Usage:
        chain = aaip_langchain(your_chain)
        result = chain.invoke({"input": "your task"})
        # result is an AAIPResult — result.output has the original response
    """
    identity = _get_identity()

    class _WrappedChain:
        def __init__(self, inner):
            self._inner = inner
            self.agent_id = identity.agent_id

        def invoke(self, inputs: Any, **kwargs) -> AAIPResult:
            task = inputs.get("input", str(inputs)) if isinstance(inputs, dict) else str(inputs)
            raw = self._inner.invoke(inputs, **kwargs)
            out = raw.get("output", str(raw)) if isinstance(raw, dict) else str(raw)
            return _build_and_verify(identity, task, out, ["langchain_invoke"], None, validators)

        def run(self, task: str, **kwargs) -> AAIPResult:
            raw = self._inner.run(task, **kwargs) if hasattr(self._inner, "run") else str(task)
            return _build_and_verify(identity, task, raw, ["langchain_run"], None, validators)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    return _WrappedChain(chain)


def aaip_crewai(crew: Any, validators: int = 3) -> Any:
    """
    Wrap a CrewAI crew with AAIP verification.

    Usage:
        crew = aaip_crewai(your_crew)
        result = crew.kickoff(inputs={"topic": "AI"})
        print(result.verified)
    """
    identity = _get_identity()

    class _WrappedCrew:
        def __init__(self, inner):
            self._inner = inner
            self.agent_id = identity.agent_id

        def kickoff(self, inputs: dict | None = None, **kwargs) -> AAIPResult:
            task = str(inputs) if inputs else "crew task"
            raw = self._inner.kickoff(inputs=inputs, **kwargs)
            out = getattr(raw, "raw", str(raw))
            agent_roles = [a.role for a in getattr(self._inner, "agents", [])]
            tools = [f"crew_agent:{r.lower().replace(' ', '_')}" for r in agent_roles] or [
                "crewai_kickoff"
            ]
            return _build_and_verify(identity, task, out, tools, None, validators)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    return _WrappedCrew(crew)
