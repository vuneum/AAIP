"""
AAIP SDK — Typed Models
All request/response data structures
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ─────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────

class AAIPError(Exception):
    """Base AAIP SDK error."""
    pass

class AuthError(AAIPError):
    """Invalid or missing API key."""
    pass

class ValidationError(AAIPError):
    """Request validation failed."""
    pass

class NotFoundError(AAIPError):
    """Resource not found."""
    pass

class PaymentError(AAIPError):
    """Payment verification failed."""
    pass


# ─────────────────────────────────────────────
# Agent Manifest
# ─────────────────────────────────────────────

@dataclass
class AgentManifest:
    """
    Machine-readable description of your agent.
    Publish this as /.well-known/aaip-agent.json on your agent's server.

    AAIP does not create your agent — you build it.
    The manifest is how AAIP discovers and indexes it.
    """
    agent_name: str
    owner: str
    endpoint: str
    description: str = ""
    version: str = "1.0.0"

    # What this agent can do
    capabilities: list[str] = field(default_factory=list)   # ["translation", "code_analysis"]
    domains: list[str] = field(default_factory=list)         # ["coding", "finance", "general"]
    tools: list[str] = field(default_factory=list)           # ["python", "search", "sql"]
    tags: list[str] = field(default_factory=list)            # ["retrieval", "rag", "assistant"]

    # Framework this agent was built with
    framework: str | None = None  # "langchain" | "crewai" | "openai_agents" | "autogpt" | "custom"
    framework_version: str | None = None

    # Payment info (optional — Full integration only)
    payment: dict[str, Any] | None = None

    # Security
    public_key: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}

    @classmethod
    def from_dict(cls, data: dict) -> AgentManifest:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_json_file(self, path: str = ".well-known/aaip-agent.json") -> None:
        """Write manifest to .well-known/aaip-agent.json for auto-discovery."""
        import json
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


# ─────────────────────────────────────────────
# Proof of Execution (PoE)
# ─────────────────────────────────────────────

@dataclass
class PoETraceStep:
    """A single verifiable step in an agent's execution."""
    step_type: str           # "tool_call" | "llm_call" | "api_call" | "reasoning" | "retrieval"
    name: str                # tool name, model name, endpoint, etc.
    timestamp_ms: int        # Unix timestamp in milliseconds
    input_hash: str | None = None    # SHA-256 hash of input (privacy-preserving)
    output_hash: str | None = None   # SHA-256 hash of output
    latency_ms: int | None = None
    status: str = "success"  # "success" | "error" | "skipped"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PoETrace:
    """
    Proof-of-Execution trace — verifiable record of how an agent performed a task.

    This is AAIP's core fraud-prevention mechanism. The trace proves the agent
    genuinely executed work rather than fabricating or copying results.

    Privacy: sensitive data is stored as hashes, not raw content.
    """
    task_id: str
    agent_id: str
    task_description: str
    started_at_ms: int
    completed_at_ms: int

    # Execution steps
    steps: list[PoETraceStep] = field(default_factory=list)

    # Aggregated stats
    total_tool_calls: int = 0
    total_llm_calls: int = 0
    total_api_calls: int = 0
    total_tokens: int | None = None
    total_latency_ms: int | None = None

    # Raw tool calls (for richer jury context)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reasoning_steps: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: PoETraceStep) -> None:
        """Add an execution step to the trace."""
        self.steps.append(step)
        if step.step_type == "tool_call":
            self.total_tool_calls += 1
        elif step.step_type == "llm_call":
            self.total_llm_calls += 1
        elif step.step_type == "api_call":
            self.total_api_calls += 1

    def add_tool_call(self, tool_name: str, inputs: Any, output: Any, latency_ms: int = 0) -> None:
        """Convenience method to add a tool call step."""
        import hashlib
        import json
        import time
        step = PoETraceStep(
            step_type="tool_call",
            name=tool_name,
            timestamp_ms=int(time.time() * 1000),
            input_hash=hashlib.sha256(json.dumps(inputs, default=str).encode()).hexdigest()[:16],
            output_hash=hashlib.sha256(json.dumps(output, default=str).encode()).hexdigest()[:16],
            latency_ms=latency_ms,
        )
        self.add_step(step)
        self.tool_calls.append({
            "tool": tool_name,
            "input_hash": step.input_hash,
            "output_hash": step.output_hash,
            "latency_ms": latency_ms,
        })

    def add_reasoning(self, thought: str) -> None:
        """Add a reasoning step (stored as hash for privacy)."""
        import hashlib
        import time
        thought_hash = hashlib.sha256(thought.encode()).hexdigest()[:16]
        step = PoETraceStep(
            step_type="reasoning",
            name="reasoning",
            timestamp_ms=int(time.time() * 1000),
            output_hash=thought_hash,
        )
        self.add_step(step)
        self.reasoning_steps.append({"hash": thought_hash})

    def compute_hash(self) -> str:
        """
        Compute a SHA-256 hash of the entire trace.
        This is the cryptographic fingerprint of the execution.
        """
        import hashlib
        trace_str = f"{self.task_id}:{self.agent_id}:{self.started_at_ms}:{self.completed_at_ms}"
        for step in self.steps:
            trace_str += f":{step.step_type}:{step.name}:{step.timestamp_ms}:{step.status}"
        return hashlib.sha256(trace_str.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["poe_hash"] = self.compute_hash()
        return d

    @property
    def duration_ms(self) -> int:
        return self.completed_at_ms - self.started_at_ms

    @property
    def step_count(self) -> int:
        return len(self.steps)


# ─────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────

@dataclass
class EvaluationRequest:
    agent_id: str
    task_domain: str
    task_description: str
    agent_output: str
    trace: PoETrace | None = None
    judge_ids: list[str] | None = None
    benchmark_dataset_id: str | None = None
    async_mode: bool = False


@dataclass
class EvaluationResponse:
    evaluation_id: str
    agent_id: str
    task_domain: str
    judge_scores: dict[str, float]
    final_score: float
    score_variance: float
    agreement_level: str  # "high" | "moderate" | "low"
    confidence_interval: dict[str, float] = field(default_factory=dict)
    benchmark_score: float | None = None
    rules_score: float | None = None
    historical_reliability: float | None = None
    poe_verified: bool = False
    poe_hash: str | None = None
    timestamp: str | None = None

    def __post_init__(self):
        # Handle nested dict from API
        if isinstance(self.confidence_interval, dict) and "low" not in self.confidence_interval:
            low = getattr(self, "confidence_interval_low", None)
            high = getattr(self, "confidence_interval_high", None)
            if low is not None:
                self.confidence_interval = {"low": low, "high": high}

    @property
    def passed(self) -> bool:
        """True if score meets minimum threshold (70)."""
        return self.final_score >= 70.0

    @property
    def grade(self) -> str:
        s = self.final_score
        if s >= 95: return "Elite"  # noqa: E701
        if s >= 90: return "Gold"  # noqa: E701
        if s >= 80: return "Silver"  # noqa: E701
        if s >= 70: return "Bronze"  # noqa: E701
        return "Unrated"


# ─────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────

@dataclass
class DiscoveryResult:
    aaip_agent_id: str
    agent_name: str
    owner: str
    description: str = ""
    endpoint: str = ""
    capabilities: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    framework: str | None = None
    reputation_score: float | None = None
    evaluation_count: int = 0
    last_active: str | None = None

    def __post_init__(self):
        # Normalize field names from API
        if not self.aaip_agent_id:
            self.aaip_agent_id = getattr(self, "aaip_agent_id", "")


# ─────────────────────────────────────────────
# Reputation
# ─────────────────────────────────────────────

@dataclass
class ReputationTimeline:
    timeline: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def current_score(self) -> float:
        return self.summary.get("current_reputation", 0.0)

    @property
    def trend(self) -> float:
        return self.summary.get("trend_delta", 0.0)

    @property
    def evaluation_count(self) -> int:
        return self.summary.get("evaluations", 0)


# ─────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────

@dataclass
class LeaderboardEntry:
    rank: int
    aaip_agent_id: str
    agent_name: str
    company_name: str
    domain: str
    average_score: float
    evaluation_count: int
    last_evaluation: str | None = None

    def __post_init__(self):
        if not self.aaip_agent_id:
            self.aaip_agent_id = getattr(self, "aaip_agent_id", "")


# ─────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────

@dataclass
class PaymentQuote:
    agent_id: str
    amount: str
    currency: str  # "USDC" | "USDT"
    chain: str     # "base" | "ethereum" | "tron" | "solana"
    wallet_address: str
    expires_at: str
    quote_id: str = ""

    @property
    def amount_float(self) -> float:
        return float(self.amount)
