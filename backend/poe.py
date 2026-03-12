"""
AAIP — Proof of Execution (PoE) Backend
Handles trace submission, cryptographic verification, and fraud detection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select, func, Column, String, Text, Integer, DateTime, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import JSON as JSONB  # JSONB on PG, JSON fallback for SQLite
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from database import Base, get_db, Agent, AgentTrace


# ─────────────────────────────────────────────
# DB Model — PoE Record
# ─────────────────────────────────────────────

class PoERecord(Base):
    __tablename__ = "poe_records"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id        = Column(UUID(as_uuid=True), nullable=False, index=True)
    aaip_agent_id   = Column(String(200), nullable=False, index=True)
    task_id         = Column(String(200), nullable=False, index=True)
    task_description= Column(Text, nullable=True)

    # Execution metadata
    started_at_ms   = Column(Integer, nullable=False)
    completed_at_ms = Column(Integer, nullable=False)
    duration_ms     = Column(Integer, nullable=True)
    step_count      = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(Integer, nullable=False, default=0)
    llm_call_count  = Column(Integer, nullable=False, default=0)
    api_call_count  = Column(Integer, nullable=False, default=0)
    total_tokens    = Column(Integer, nullable=True)

    # The full trace (steps stored as hashes — privacy preserving)
    steps_json      = Column(JSONB, nullable=False, default=list)
    tool_calls_json = Column(JSONB, nullable=False, default=list)
    reasoning_json  = Column(JSONB, nullable=False, default=list)
    token_usage     = Column(JSONB, nullable=False, default=dict)

    # Cryptographic proof
    poe_hash        = Column(String(64), nullable=False, index=True)  # SHA-256 of trace
    hash_verified   = Column(Boolean, nullable=False, default=False)
    fraud_flags     = Column(JSONB, nullable=False, default=list)

    # Link to evaluation if submitted together
    evaluation_id   = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_at      = Column(DateTime, default=datetime.utcnow, index=True)


# ─────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────

class PoETraceStepInput(BaseModel):
    step_type:    str
    name:         str
    timestamp_ms: int
    input_hash:   Optional[str] = None
    output_hash:  Optional[str] = None
    latency_ms:   Optional[int] = None
    status:       str = "success"
    metadata:     dict = Field(default_factory=dict)


class PoETraceInput(BaseModel):
    task_id:          str
    agent_id:         str
    task_description: str = ""
    started_at_ms:    int
    completed_at_ms:  int
    steps:            list[PoETraceStepInput] = Field(default_factory=list)
    total_tool_calls: int = 0
    total_llm_calls:  int = 0
    total_api_calls:  int = 0
    total_tokens:     Optional[int] = None
    tool_calls:       list[dict] = Field(default_factory=list)
    reasoning_steps:  list[dict] = Field(default_factory=list)
    token_usage:      dict = Field(default_factory=dict)
    poe_hash:         Optional[str] = None
    metadata:         dict = Field(default_factory=dict)


class SubmitTraceRequest(BaseModel):
    agent_id: str
    trace:    PoETraceInput
    poe_hash: Optional[str] = None


class TraceVerificationResult(BaseModel):
    trace_id:        str
    poe_hash:        str
    hash_verified:   bool
    step_count:      int
    tool_calls:      int
    duration_ms:     int
    fraud_flags:     list[str]
    verdict:         str   # "verified" | "suspicious" | "invalid"
    verified_at:     str


# ─────────────────────────────────────────────
# Hash Verification
# ─────────────────────────────────────────────

def compute_trace_hash(trace: PoETraceInput) -> str:
    """Recompute SHA-256 hash from trace data. Must match client-side computation."""
    parts = [trace.task_id, trace.agent_id, str(trace.started_at_ms)]
    for step in trace.steps:
        parts.append(f"{step.step_type}:{step.name}:{step.timestamp_ms}:{step.status}")
    data = ":".join(parts)
    return hashlib.sha256(data.encode()).hexdigest()


def verify_hash(trace: PoETraceInput, submitted_hash: str) -> bool:
    """Verify the submitted hash matches recomputed hash."""
    expected = compute_trace_hash(trace)
    return hmac_compare(expected, submitted_hash)


def hmac_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


# ─────────────────────────────────────────────
# Fraud Detection
# ─────────────────────────────────────────────

def detect_fraud_signals(trace: PoETraceInput) -> list[str]:
    """
    Heuristic fraud detection on execution traces.
    Returns list of flag strings — empty means clean.
    """
    flags = []

    # 1. Zero steps — agent claims work was done with no trace
    if len(trace.steps) == 0:
        flags.append("NO_EXECUTION_STEPS")

    # 2. Impossibly fast execution
    duration = trace.completed_at_ms - trace.started_at_ms
    if duration < 100 and trace.total_tool_calls > 0:
        flags.append("SUSPICIOUSLY_FAST_EXECUTION")

    # 3. Completed before started
    if trace.completed_at_ms <= trace.started_at_ms:
        flags.append("INVALID_TIMESTAMPS")

    # 4. Future timestamps
    now_ms = int(time.time() * 1000)
    if trace.started_at_ms > now_ms + 60000:  # > 1 min in future
        flags.append("FUTURE_TIMESTAMP")

    # 5. Steps out of chronological order
    timestamps = [s.timestamp_ms for s in trace.steps]
    if timestamps != sorted(timestamps):
        flags.append("STEPS_OUT_OF_ORDER")

    # 6. Claimed tool calls don't match step count
    actual_tool_steps = sum(1 for s in trace.steps if s.step_type == "tool_call")
    if abs(actual_tool_steps - trace.total_tool_calls) > 2:
        flags.append("TOOL_COUNT_MISMATCH")

    # 7. Replay attack — task completed with no reasoning
    if trace.total_tool_calls > 3 and len(trace.reasoning_steps) == 0:
        flags.append("NO_REASONING_FOR_COMPLEX_TASK")

    return flags


# ─────────────────────────────────────────────
# Core Functions
# ─────────────────────────────────────────────

async def submit_poe_trace(
    db: AsyncSession,
    request: SubmitTraceRequest,
) -> dict:
    """
    Submit and verify a Proof-of-Execution trace.
    Stores trace, verifies hash, runs fraud detection.
    """
    trace = request.trace
    submitted_hash = request.poe_hash or trace.poe_hash or ""

    # Resolve agent
    result = await db.execute(
        select(Agent).where(Agent.aaip_agent_id == request.agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent not found: {request.agent_id}")

    # Verify hash
    computed_hash = compute_trace_hash(trace)
    hash_verified = hmac_compare(computed_hash, submitted_hash) if submitted_hash else False

    # Fraud detection
    fraud_flags = detect_fraud_signals(trace)

    # Determine verdict
    if not hash_verified and submitted_hash:
        verdict = "invalid"
    elif fraud_flags:
        verdict = "suspicious"
    else:
        verdict = "verified"

    duration_ms = trace.completed_at_ms - trace.started_at_ms

    # Save to DB
    record = PoERecord(
        agent_id=agent.id,
        aaip_agent_id=request.agent_id,
        task_id=trace.task_id,
        task_description=trace.task_description,
        started_at_ms=trace.started_at_ms,
        completed_at_ms=trace.completed_at_ms,
        duration_ms=duration_ms,
        step_count=len(trace.steps),
        tool_call_count=trace.total_tool_calls,
        llm_call_count=trace.total_llm_calls,
        api_call_count=trace.total_api_calls,
        total_tokens=trace.total_tokens,
        steps_json=[s.model_dump() for s in trace.steps],
        tool_calls_json=trace.tool_calls,
        reasoning_json=trace.reasoning_steps,
        token_usage=trace.token_usage,
        poe_hash=computed_hash,
        hash_verified=hash_verified,
        fraud_flags=fraud_flags,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "trace_id": str(record.id),
        "task_id": trace.task_id,
        "poe_hash": computed_hash,
        "hash_verified": hash_verified,
        "verdict": verdict,
        "step_count": len(trace.steps),
        "tool_calls": trace.total_tool_calls,
        "duration_ms": duration_ms,
        "fraud_flags": fraud_flags,
        "submitted_at": record.created_at.isoformat(),
    }


async def verify_poe_trace(db: AsyncSession, trace_id: str) -> TraceVerificationResult:
    """Retrieve and return verification status of a stored trace."""
    result = await db.execute(
        select(PoERecord).where(PoERecord.id == trace_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    verdict = "verified" if record.hash_verified and not record.fraud_flags else (
        "suspicious" if record.fraud_flags else "unverified"
    )

    return TraceVerificationResult(
        trace_id=str(record.id),
        poe_hash=record.poe_hash,
        hash_verified=record.hash_verified,
        step_count=record.step_count,
        tool_calls=record.tool_call_count,
        duration_ms=record.duration_ms or 0,
        fraud_flags=record.fraud_flags or [],
        verdict=verdict,
        verified_at=datetime.utcnow().isoformat(),
    )


async def get_agent_poe_stats(db: AsyncSession, aaip_agent_id: str) -> dict:
    """Get aggregate PoE statistics for an agent."""
    result = await db.execute(
        select(
            func.count(PoERecord.id),
            func.avg(PoERecord.duration_ms),
            func.avg(PoERecord.step_count),
            func.sum(func.cast(PoERecord.hash_verified, Integer)),
        ).where(PoERecord.aaip_agent_id == aaip_agent_id)
    )
    row = result.one()
    total = row[0] or 0
    verified = int(row[3] or 0)

    # Count fraud flags
    fraud_result = await db.execute(
        select(func.count(PoERecord.id)).where(
            PoERecord.aaip_agent_id == aaip_agent_id,
            func.jsonb_array_length(PoERecord.fraud_flags) > 0,
        )
    )
    flagged = fraud_result.scalar() or 0

    return {
        "total_traces": total,
        "verified_traces": verified,
        "flagged_traces": flagged,
        "verification_rate": round(verified / total * 100, 1) if total > 0 else 0,
        "avg_duration_ms": round(float(row[1] or 0), 1),
        "avg_steps": round(float(row[2] or 0), 1),
    }

