"""Trace persistence and retrieval."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import AgentTrace, Agent, Evaluation


async def save_agent_trace(
    db: AsyncSession,
    agent_db_id,
    task_domain: str,
    trace_payload: dict | None,
    evaluation_id=None,
):
    if not trace_payload:
        return None

    trace = AgentTrace(
        agent_id=agent_db_id,
        evaluation_id=evaluation_id,
        task_domain=task_domain,
        tool_calls=trace_payload.get("tool_calls", []),
        reasoning_steps=trace_payload.get("reasoning_steps", []),
        token_usage=trace_payload.get("token_usage", {}),
        latency_ms=trace_payload.get("latency_ms"),
        trace_metadata=trace_payload.get("metadata", {}),
    )
    db.add(trace)
    await db.flush()
    return trace


async def list_agent_traces(db: AsyncSession, aaip_agent_id: str, limit: int = 20) -> list[dict]:
    result = await db.execute(
        select(AgentTrace)
        .join(Agent, Agent.id == AgentTrace.agent_id)
        .where(Agent.aaip_agent_id == aaip_agent_id)
        .order_by(AgentTrace.created_at.desc())
        .limit(limit)
    )
    traces = result.scalars().all()
    return [serialize_trace(trace) for trace in traces]


async def get_trace_stats(db: AsyncSession, agent_db_id) -> dict:
    count_result = await db.execute(select(func.count(AgentTrace.id)).where(AgentTrace.agent_id == agent_db_id))
    avg_latency_result = await db.execute(select(func.avg(AgentTrace.latency_ms)).where(AgentTrace.agent_id == agent_db_id))
    total_steps_result = await db.execute(
        select(func.count(AgentTrace.id)).where(AgentTrace.agent_id == agent_db_id, AgentTrace.evaluation_id.is_not(None))
    )
    return {
        "trace_count": count_result.scalar() or 0,
        "average_latency_ms": round(float(avg_latency_result.scalar() or 0), 2),
        "evaluated_traces": total_steps_result.scalar() or 0,
    }


def serialize_trace(trace: AgentTrace) -> dict:
    return {
        "trace_id": str(trace.id),
        "evaluation_id": str(trace.evaluation_id) if trace.evaluation_id else None,
        "task_domain": trace.task_domain,
        "tool_calls": trace.tool_calls,
        "reasoning_steps": trace.reasoning_steps,
        "token_usage": trace.token_usage,
        "latency_ms": trace.latency_ms,
        "metadata": trace.trace_metadata,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }
