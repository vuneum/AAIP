"""AAIP evaluation module with datasets, traces, and reputation-aware scoring."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Agent, Evaluation, init_db, async_session_maker


class EvaluationTraceInput(BaseModel):
    tool_calls: list[dict] = Field(default_factory=list)
    reasoning_steps: list[dict] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    latency_ms: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class EvaluationRequest(BaseModel):
    agent_id: str = Field(..., description="AAIP Agent ID")
    task_domain: str = Field(..., pattern="^(coding|finance|general)$")
    task_description: str = Field(..., min_length=1)
    agent_output: str = Field(..., min_length=1)
    benchmark_dataset_id: Optional[str] = Field(default=None)
    selected_judge_ids: list[str] = Field(default_factory=list)
    trace: Optional[EvaluationTraceInput] = None
    async_mode: bool = Field(default=False)


class EvaluationResponse(BaseModel):
    evaluation_id: str
    agent_id: str
    task_domain: str
    judge_scores: dict
    final_score: float
    score_variance: float
    confidence_interval: dict
    agreement_level: str
    benchmark_score: Optional[float] = None
    rules_score: Optional[float] = None
    historical_reliability: Optional[float] = None
    timestamp: datetime


async def evaluate_agent_output(
    db: AsyncSession,
    agent_id: str,
    task_domain: str,
    task_description: str,
    agent_output: str,
    benchmark_dataset_id: Optional[str] = None,
    trace: Optional[dict] = None,
    selected_judge_ids: Optional[list[str]] = None,
) -> EvaluationResponse:
    from benchmark_datasets import get_dataset_by_dataset_id
    from custom_judges import get_custom_judges_for_domain
    from oracle import get_judges_for_domain
    from judges import execute_parallel_judges, generate_mock_scores
    from consensus import calculate_consensus
    from retrieval import search_similar_outputs, format_context_for_judges, generate_embedding
    from traces import save_agent_trace

    agent = await resolve_agent(db, agent_id)
    if not agent:
        raise ValueError(f"Agent not found: {agent_id}")

    dataset = None
    if benchmark_dataset_id:
        dataset = await get_dataset_by_dataset_id(db, benchmark_dataset_id)

    default_judges = await get_judges_for_domain(task_domain, num_judges=3)
    custom_judges = await get_custom_judges_for_domain(db, task_domain)

    judges = custom_judges[:2] + default_judges
    if selected_judge_ids:
        selected = []
        all_judges = {judge.get("judge_id", judge["model_id"]): judge for judge in judges}
        all_judges.update({judge["model_id"]: judge for judge in judges})
        for item in selected_judge_ids:
            if item in all_judges:
                selected.append(all_judges[item])
        judges = selected or judges

    similar_outputs = await search_similar_outputs(
        db=db,
        agent_id=str(agent.id),
        task_domain=task_domain,
        agent_output=agent_output,
        top_k=3,
    )
    context = format_context_for_judges(similar_outputs)

    import os
    if os.getenv("OPENROUTER_API_KEY"):
        judge_results = await execute_parallel_judges(
            judges=judges,
            task_description=task_description,
            agent_output=agent_output,
            context=context,
        )
    else:
        judge_results = generate_mock_scores(num_judges=len(judges))

    consensus = calculate_consensus(judge_results["judge_scores"])
    rules_score = calculate_rules_score(task_description=task_description, agent_output=agent_output)
    benchmark_score = calculate_benchmark_score(agent_output=agent_output, dataset=dataset)
    historical_reliability = await calculate_historical_reliability(db, agent.id)

    final_score = weighted_final_score(
        judge_score=consensus["final_score"],
        benchmark_score=benchmark_score,
        rules_score=rules_score,
        historical_reliability=historical_reliability,
    )

    evaluation = Evaluation(
        agent_id=agent.id,
        task_domain=task_domain,
        task_description=task_description,
        agent_output=agent_output,
        output_embedding=await generate_embedding(agent_output),
        judge_scores=judge_results["judge_scores"],
        judge_metadata={
            "agreement_level": consensus["agreement_level"],
            "judges": judges,
            "errors": judge_results.get("errors", []),
        },
        benchmark_dataset_id=benchmark_dataset_id,
        benchmark_score=benchmark_score,
        historical_reliability=historical_reliability,
        rules_score=rules_score,
        final_score=final_score,
        score_variance=consensus["score_variance"],
        confidence_interval_low=consensus["confidence_interval_low"],
        confidence_interval_high=consensus["confidence_interval_high"],
    )
    db.add(evaluation)
    await db.flush()

    if trace:
        await save_agent_trace(
            db=db,
            agent_db_id=agent.id,
            task_domain=task_domain,
            trace_payload=trace,
            evaluation_id=evaluation.id,
        )

    await db.commit()
    await db.refresh(evaluation)

    return EvaluationResponse(
        evaluation_id=str(evaluation.id),
        agent_id=agent.aaip_agent_id,
        task_domain=evaluation.task_domain,
        judge_scores=evaluation.judge_scores,
        final_score=evaluation.final_score,
        score_variance=evaluation.score_variance or 0.0,
        confidence_interval={
            "low": evaluation.confidence_interval_low,
            "high": evaluation.confidence_interval_high,
        },
        agreement_level=consensus["agreement_level"],
        benchmark_score=evaluation.benchmark_score,
        rules_score=evaluation.rules_score,
        historical_reliability=evaluation.historical_reliability,
        timestamp=evaluation.timestamp,
    )


async def evaluate_agent_output_sync(**kwargs) -> dict:
    await init_db()
    async with async_session_maker() as db:
        response = await evaluate_agent_output(db=db, **kwargs)
        return response.model_dump(mode="json")


async def resolve_agent(db: AsyncSession, agent_id: str):
    agent = await db.get(Agent, agent_id)
    if agent:
        return agent
    result = await db.execute(select(Agent).where(Agent.aaip_agent_id == agent_id))
    return result.scalar_one_or_none()


def calculate_rules_score(task_description: str, agent_output: str) -> float:
    score = 65.0
    if len(agent_output.strip()) > 40:
        score += 10
    if len(agent_output.split()) > 20:
        score += 5
    if any(token in agent_output.lower() for token in ["because", "therefore", "however", "risk"]):
        score += 10
    if task_description.lower().startswith("write") and any(token in agent_output for token in ["def ", "function", "return"]):
        score += 10
    return min(100.0, score)


def calculate_benchmark_score(agent_output: str, dataset: Optional[dict]) -> Optional[float]:
    if not dataset:
        return None
    base = 70.0
    length_factor = min(len(agent_output) / 20.0, 20.0)
    category_bonus = len(dataset.get("metadata", {}).get("categories", [])) * 2
    return round(min(100.0, base + length_factor + category_bonus), 2)


async def calculate_historical_reliability(db: AsyncSession, agent_db_id) -> float:
    result = await db.execute(
        select(Evaluation.final_score)
        .where(Evaluation.agent_id == agent_db_id)
        .order_by(Evaluation.timestamp.desc())
        .limit(10)
    )
    scores = [float(row[0]) for row in result.all()]
    if not scores:
        return 75.0
    return round(sum(scores) / len(scores), 2)


def weighted_final_score(
    judge_score: float,
    benchmark_score: Optional[float],
    rules_score: Optional[float],
    historical_reliability: Optional[float],
) -> float:
    benchmark = benchmark_score if benchmark_score is not None else judge_score
    rules = rules_score if rules_score is not None else judge_score
    historical = historical_reliability if historical_reliability is not None else judge_score
    final = (judge_score * 0.4) + (benchmark * 0.3) + (rules * 0.2) + (historical * 0.1)
    return round(final, 2)


async def get_evaluation_history(db: AsyncSession, aaip_agent_id: str, limit: int = 20) -> list[dict]:
    agent = await resolve_agent(db, aaip_agent_id)
    if not agent:
        return []
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.agent_id == agent.id)
        .order_by(Evaluation.timestamp.desc())
        .limit(limit)
    )
    evaluations = result.scalars().all()
    return [
        {
            "evaluation_id": str(item.id),
            "task_domain": item.task_domain,
            "task_description": item.task_description,
            "judge_scores": item.judge_scores,
            "benchmark_dataset_id": item.benchmark_dataset_id,
            "benchmark_score": item.benchmark_score,
            "rules_score": item.rules_score,
            "historical_reliability": item.historical_reliability,
            "final_score": item.final_score,
            "timestamp": item.timestamp.isoformat(),
        }
        for item in evaluations
    ]
