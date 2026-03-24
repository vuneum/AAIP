"""Agent reputation calculations over time."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Agent, Evaluation


async def get_agent_reputation_timeline(db: AsyncSession, aaip_agent_id: str, days: int = 30) -> dict:
    result = await db.execute(select(Agent).where(Agent.aaip_agent_id == aaip_agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return {"timeline": [], "summary": {}}

    start = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.agent_id == agent.id, Evaluation.timestamp >= start)
        .order_by(Evaluation.timestamp.asc())
    )
    evaluations = result.scalars().all()

    timeline = []
    rolling_scores = []
    for item in evaluations:
        rolling_scores.append(float(item.final_score))
        recent = rolling_scores[-5:]
        timeline.append({
            "timestamp": item.timestamp.isoformat(),
            "score": item.final_score,
            "rolling_average": round(sum(recent) / len(recent), 2),
            "agreement": item.judge_metadata.get("agreement_level") if item.judge_metadata else None,
            "benchmark_dataset_id": item.benchmark_dataset_id,
        })

    latest = timeline[-1]["rolling_average"] if timeline else 0
    earliest = timeline[0]["rolling_average"] if timeline else 0
    return {
        "timeline": timeline,
        "summary": {
            "window_days": days,
            "evaluations": len(evaluations),
            "current_reputation": latest,
            "trend_delta": round(latest - earliest, 2) if timeline else 0,
        },
    }
