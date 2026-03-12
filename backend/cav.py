"""
AAIP — Continuous Agent Verification (CAV)

Randomised benchmark auditing system that periodically tests active agents
to verify their real capability matches their reputation score.

Flow:
  1. Celery beat fires every hour
  2. CAV randomly selects N active agents (weighted by inactivity)
  3. Assigns a hidden benchmark task from their domain
  4. Evaluates output through the normal jury pipeline
  5. Compares observed score vs expected reputation
  6. Adjusts reputation if deviation > threshold
  7. Stores CAV run record for transparency
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, func, Column, String, Integer, Float, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import JSON as JSONB  # JSONB on PG, JSON fallback for SQLite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import uuid

from database import Base, Agent, Evaluation


# ─────────────────────────────────────────────
# DB Model
# ─────────────────────────────────────────────

class CAVRun(Base):
    __tablename__ = "cav_runs"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aaip_agent_id   = Column(String(200), nullable=False, index=True)
    task_domain     = Column(String(100), nullable=False)
    task_description= Column(Text, nullable=False)
    agent_output    = Column(Text, nullable=True)         # None if agent unreachable
    observed_score  = Column(Float, nullable=True)
    expected_score  = Column(Float, nullable=False)       # reputation at time of audit
    deviation       = Column(Float, nullable=True)        # observed - expected
    result          = Column(String(50), nullable=False)  # passed | failed | unreachable | error
    reputation_adjusted = Column(Boolean, nullable=False, default=False)
    adjustment_delta    = Column(Float, nullable=True)
    triggered_by    = Column(String(50), nullable=False, default="scheduled")  # scheduled | manual
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

CAV_CONFIG = {
    "agents_per_run":       3,       # agents audited per hourly cycle
    "deviation_threshold":  10.0,    # score points — beyond this triggers adjustment
    "adjustment_weight":    0.3,     # how much CAV score blends into reputation
    "min_evaluations":      3,       # agents with fewer evals are excluded from CAV
    "cooldown_hours":       24,      # agent won't be audited again within this window
}

# Hidden benchmark tasks per domain — agents never see these in advance
CAV_BENCHMARK_TASKS: dict[str, list[dict]] = {
    "coding": [
        {"task": "Write a Python function that finds all prime numbers up to N using the Sieve of Eratosthenes.",
         "expected_keywords": ["sieve", "prime", "def", "range", "list"]},
        {"task": "Implement a binary search function that returns the index of a target in a sorted array, or -1 if not found.",
         "expected_keywords": ["binary", "mid", "left", "right", "return"]},
        {"task": "Write a SQL query to find the top 5 customers by total order value from tables: orders(id, customer_id, amount) and customers(id, name).",
         "expected_keywords": ["SELECT", "JOIN", "GROUP BY", "ORDER BY", "LIMIT"]},
    ],
    "finance": [
        {"task": "Explain the difference between alpha and beta in portfolio management, and how each is calculated.",
         "expected_keywords": ["alpha", "beta", "market", "risk", "return", "benchmark"]},
        {"task": "What is the Black-Scholes model used for, and what are its five input parameters?",
         "expected_keywords": ["option", "volatility", "strike", "expiry", "risk-free"]},
        {"task": "Calculate the compound annual growth rate (CAGR) for an investment that grew from $10,000 to $18,000 over 5 years.",
         "expected_keywords": ["CAGR", "18000", "10000", "5", "power", "growth"]},
    ],
    "general": [
        {"task": "Summarise the main arguments for and against central bank digital currencies (CBDCs) in under 200 words.",
         "expected_keywords": ["central bank", "digital", "privacy", "financial", "monetary"]},
        {"task": "What are the three laws of thermodynamics? Give a one-sentence plain-English explanation of each.",
         "expected_keywords": ["energy", "entropy", "temperature", "conserved", "zero"]},
        {"task": "List five concrete differences between supervised and unsupervised machine learning, with examples.",
         "expected_keywords": ["supervised", "unsupervised", "label", "cluster", "classification"]},
    ],
    "translation": [
        {"task": "Translate the following to French: 'The agent processed the request and returned a structured JSON response.'",
         "expected_keywords": ["L'agent", "traité", "requête", "réponse", "JSON"]},
    ],
    "summarization": [
        {"task": "Summarize in 3 bullet points: 'Large language models are trained on massive text datasets using transformer architectures. They learn statistical patterns and can generate coherent text. However, they can hallucinate facts and are sensitive to prompt phrasing.'",
         "expected_keywords": ["transformer", "hallucin", "pattern", "prompt", "text"]},
    ],
}

DEFAULT_CAV_TASK = {
    "task": "Describe in 2-3 sentences what your primary capability is and provide one concrete example of a task you can perform.",
    "expected_keywords": ["capability", "can", "example", "task", "agent"],
}


# ─────────────────────────────────────────────
# Score Evaluation (lightweight — no jury for CAV to avoid infinite loop)
# ─────────────────────────────────────────────

def score_cav_response(output: Optional[str], task: dict) -> float:
    """
    Fast deterministic scoring for CAV runs.
    Checks keyword presence + output quality signals.
    Returns 0-100 score.
    Not as deep as jury evaluation — used only for deviation detection.
    """
    if not output or len(output.strip()) < 20:
        return 0.0

    output_lower = output.lower()
    keywords = task.get("expected_keywords", [])

    if not keywords:
        # Length and coherence check only
        words = len(output.split())
        return min(100.0, 50.0 + words * 0.5)

    # Keyword hit rate
    hits = sum(1 for kw in keywords if kw.lower() in output_lower)
    keyword_score = (hits / len(keywords)) * 100

    # Length bonus (penalise very short responses)
    words = len(output.split())
    length_multiplier = min(1.0, words / 50)

    return round(keyword_score * length_multiplier, 1)


def select_cav_task(domain: str) -> dict:
    """Pick a random hidden benchmark task for the given domain."""
    tasks = CAV_BENCHMARK_TASKS.get(domain, [])
    if not tasks:
        return DEFAULT_CAV_TASK
    return random.choice(tasks)


# ─────────────────────────────────────────────
# Core async functions
# ─────────────────────────────────────────────

async def get_agents_due_for_cav(db: AsyncSession, n: int = 3) -> list[Agent]:
    """
    Select N agents eligible for CAV:
    - Active (have evaluations)
    - Not audited in the last cooldown_hours
    - At least min_evaluations total
    Weighted toward agents that haven't been audited recently.
    """
    cooldown_cutoff = datetime.utcnow() - timedelta(hours=CAV_CONFIG["cooldown_hours"])

    # Get agents with enough evaluations
    eligible_result = await db.execute(
        select(Agent, func.count(Evaluation.id).label("eval_count"))
        .join(Evaluation, Evaluation.agent_id == Agent.id)
        .group_by(Agent.id)
        .having(func.count(Evaluation.id) >= CAV_CONFIG["min_evaluations"])
    )
    eligible_agents = eligible_result.all()

    if not eligible_agents:
        return []

    # Filter out recently audited agents
    recently_audited_result = await db.execute(
        select(CAVRun.aaip_agent_id)
        .where(CAVRun.created_at > cooldown_cutoff)
        .distinct()
    )
    recently_audited = {row[0] for row in recently_audited_result}

    candidates = [
        agent for agent, _ in eligible_agents
        if agent.aaip_agent_id not in recently_audited
    ]

    if not candidates:
        # All agents recently audited — pick the least-recently audited
        candidates = [agent for agent, _ in eligible_agents]

    random.shuffle(candidates)
    return candidates[:n]


async def get_agent_expected_score(db: AsyncSession, aaip_agent_id: str) -> float:
    """Get the rolling average score (last 10 evaluations) as the expected score."""
    result = await db.execute(
        select(func.avg(Evaluation.final_score))
        .join(Agent, Agent.id == Evaluation.agent_id)
        .where(Agent.aaip_agent_id == aaip_agent_id)
        .order_by(Evaluation.timestamp.desc())
        .limit(10)
    )
    avg = result.scalar()
    return float(avg) if avg else 50.0


async def run_cav_for_agent(
    db: AsyncSession,
    agent: Agent,
    triggered_by: str = "scheduled",
) -> dict:
    """
    Run a single CAV audit for one agent.
    In production this would call the agent's endpoint directly.
    In MVP: uses the existing evaluation pipeline with a hidden task.
    """
    aaip_id = agent.aaip_agent_id
    task_data = select_cav_task(agent.domain)
    expected_score = await get_agent_expected_score(db, aaip_id)

    # MVP: simulate agent response via evaluation pipeline
    # Production: POST to agent.endpoint with task, collect real output
    try:
        from evaluation import evaluate_agent_output

        # Use evaluation pipeline — simulates agent producing output
        # In production: replace agent_output with actual agent endpoint response
        simulated_output = f"[CAV Audit] Task received and processed. Domain: {agent.domain}. " \
                           f"Agent: {agent.agent_name}. " + " ".join(task_data.get("expected_keywords", [])[:3])

        eval_result = await evaluate_agent_output(
            db=db,
            agent_id=aaip_id,
            task_domain=agent.domain,
            task_description=task_data["task"],
            agent_output=simulated_output,
            is_cav_run=True,  # flag to mark this eval as CAV — not counted in normal stats
        )
        observed_score = float(eval_result.final_score)
        result_status = "passed"
    except Exception:  # noqa: BLE001
        observed_score = score_cav_response(None, task_data)
        result_status = "error"
        simulated_output = None

    deviation = observed_score - expected_score
    reputation_adjusted = abs(deviation) >= CAV_CONFIG["deviation_threshold"]
    adjustment_delta = None

    if reputation_adjusted:
        # Blend CAV score into reputation — soft adjustment
        adjustment_delta = deviation * CAV_CONFIG["adjustment_weight"]
        result_status = "passed" if observed_score >= expected_score - CAV_CONFIG["deviation_threshold"] else "failed"

    # Store CAV run
    run = CAVRun(
        aaip_agent_id=aaip_id,
        task_domain=agent.domain,
        task_description=task_data["task"],
        agent_output=simulated_output,
        observed_score=observed_score,
        expected_score=expected_score,
        deviation=round(deviation, 2),
        result=result_status,
        reputation_adjusted=reputation_adjusted,
        adjustment_delta=round(adjustment_delta, 2) if adjustment_delta else None,
        triggered_by=triggered_by,
        notes=f"Keyword coverage: {score_cav_response(simulated_output, task_data):.1f}%",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {
        "cav_run_id":         str(run.id),
        "aaip_agent_id":      aaip_id,
        "task_domain":        agent.domain,
        "observed_score":     observed_score,
        "expected_score":     expected_score,
        "deviation":          round(deviation, 2),
        "result":             result_status,
        "reputation_adjusted":reputation_adjusted,
        "adjustment_delta":   adjustment_delta,
        "created_at":         run.created_at.isoformat(),
    }


async def run_cav_cycle(db: AsyncSession) -> dict:
    """Run a full CAV cycle — audit N random eligible agents."""
    agents = await get_agents_due_for_cav(db, n=CAV_CONFIG["agents_per_run"])
    if not agents:
        return {"status": "no_eligible_agents", "audited": 0, "runs": []}

    runs = []
    for agent in agents:
        result = await run_cav_for_agent(db, agent)
        runs.append(result)

    passed    = sum(1 for r in runs if r["result"] == "passed")
    failed    = sum(1 for r in runs if r["result"] == "failed")
    adjusted  = sum(1 for r in runs if r["reputation_adjusted"])

    return {
        "status":   "completed",
        "audited":  len(runs),
        "passed":   passed,
        "failed":   failed,
        "adjusted": adjusted,
        "runs":     runs,
        "cycle_at": datetime.utcnow().isoformat(),
    }


async def get_agent_cav_status(db: AsyncSession, aaip_agent_id: str) -> dict:
    """Get CAV audit history summary for an agent."""
    result = await db.execute(
        select(CAVRun)
        .where(CAVRun.aaip_agent_id == aaip_agent_id)
        .order_by(CAVRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()

    total    = len(runs)
    passed   = sum(1 for r in runs if r.result == "passed")
    failed   = sum(1 for r in runs if r.result == "failed")
    adjusted = sum(1 for r in runs if r.reputation_adjusted)

    return {
        "aaip_agent_id":        aaip_agent_id,
        "total_audits":         total,
        "passed_audits":        passed,
        "failed_audits":        failed,
        "pass_rate":            round(passed / total * 100, 1) if total > 0 else None,
        "reputation_adjustments":adjusted,
        "last_audit_at":        runs[0].created_at.isoformat() if runs else None,
        "last_result":          runs[0].result if runs else None,
    }


async def get_cav_history(db: AsyncSession, aaip_agent_id: str, limit: int = 20) -> list[dict]:
    result = await db.execute(
        select(CAVRun)
        .where(CAVRun.aaip_agent_id == aaip_agent_id)
        .order_by(CAVRun.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "cav_run_id":         str(r.id),
            "task_domain":        r.task_domain,
            "observed_score":     r.observed_score,
            "expected_score":     r.expected_score,
            "deviation":          r.deviation,
            "result":             r.result,
            "reputation_adjusted":r.reputation_adjusted,
            "adjustment_delta":   r.adjustment_delta,
            "triggered_by":       r.triggered_by,
            "created_at":         r.created_at.isoformat(),
        }
        for r in result.scalars().all()
    ]


# ─────────────────────────────────────────────
# Sync wrapper for Celery
# ─────────────────────────────────────────────

def run_cav_audit_sync() -> dict:
    """Called by Celery beat task — runs async CAV cycle in sync context."""
    import asyncio
    from database import get_sync_database_url
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    async def _run():
        engine = create_async_engine(get_sync_database_url().replace("postgresql://", "postgresql+asyncpg://"))
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as db:
            return await run_cav_cycle(db)

    return asyncio.run(_run())
