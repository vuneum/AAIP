"""
routers/validators.py
Leaderboard, reputation, discovery, benchmark, and domain endpoints.
"""
from __future__ import annotations

from typing import Optional
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_api_key, require_api_key, APIKey
from database import get_db, Agent, Evaluation, EvaluationJob
from evaluation import evaluate_agent_output, get_evaluation_history, EvaluationRequest, EvaluationResponse, resolve_agent
from oracle import get_benchmark_rankings, get_judges_for_domain
from benchmark_datasets import seed_default_datasets, list_benchmark_datasets
from custom_judges import (
    create_custom_judge, list_custom_judges, deactivate_custom_judge, CustomJudgeCreateRequest,
)
from reputation import get_agent_reputation_timeline
from discovery import (
    DiscoveryRegisterRequest, crawl_and_register_agent,
    upsert_discovered_agent, get_discovery_profile, list_discoverable_agents,
)
from tasks import process_evaluation_job

router = APIRouter()


# ── Reputation & Leaderboard ──────────────────────────────────────────────────

@router.get("/agents/{aaip_agent_id}/reputation", tags=["Reputation"])
async def get_agent_reputation(
    aaip_agent_id: str,
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_agent_reputation_timeline(db, aaip_agent_id, days)


@router.get("/leaderboard", tags=["Reputation"])
async def get_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    domain: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = (
        select(
            Agent.aaip_agent_id,
            Agent.company_name,
            Agent.agent_name,
            Agent.domain,
            func.avg(Evaluation.final_score).label("avg_score"),
            func.count(Evaluation.id).label("evaluation_count"),
            func.max(Evaluation.timestamp).label("last_evaluation"),
        )
        .join(Evaluation, Evaluation.agent_id == Agent.id)
        .group_by(Agent.id)
        .order_by(func.avg(Evaluation.final_score).desc())
        .limit(limit)
    )
    if domain:
        query = query.where(Agent.domain == domain)
    rows = (await db.execute(query)).all()
    return {
        "leaderboard": [
            {
                "rank":             i,
                "aaip_agent_id":    row.aaip_agent_id,
                "company_name":     row.company_name,
                "agent_name":       row.agent_name,
                "domain":           row.domain,
                "average_score":    round(float(row.avg_score), 2),
                "evaluation_count": row.evaluation_count,
                "last_evaluation":  row.last_evaluation.isoformat() if row.last_evaluation else None,
            }
            for i, row in enumerate(rows, 1)
        ],
        "total_agents":  len(rows),
        "domain_filter": domain,
    }


# ── Evaluation ────────────────────────────────────────────────────────────────

@router.post("/evaluate", response_model=EvaluationResponse, tags=["Evaluation"])
async def evaluate_endpoint(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> EvaluationResponse:
    try:
        if request.async_mode:
            raise HTTPException(status_code=400, detail="Use /jobs/evaluate for async evaluation")
        return await evaluate_agent_output(
            db=db,
            agent_id=request.agent_id,
            task_domain=request.task_domain,
            task_description=request.task_description,
            agent_output=request.agent_output,
            benchmark_dataset_id=request.benchmark_dataset_id,
            trace=request.trace.model_dump() if request.trace else None,
            selected_judge_ids=request.selected_judge_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/evaluate", tags=["Evaluation"])
async def queue_evaluation_job(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    agent = await resolve_agent(db, request.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    job = EvaluationJob(
        job_id=job_id,
        agent_id=agent.id,
        status="queued",
        payload={
            "task_domain":          request.task_domain,
            "task_description":     request.task_description,
            "agent_output":         request.agent_output,
            "benchmark_dataset_id": request.benchmark_dataset_id,
            "selected_judge_ids":   request.selected_judge_ids,
            "trace":                request.trace.model_dump() if request.trace else None,
        },
    )
    db.add(job)
    await db.commit()

    try:
        task           = process_evaluation_job.delay(job_id)
        celery_task_id = task.id
    except Exception:
        celery_task_id = None

    return {"job_id": job_id, "status": "queued", "celery_task_id": celery_task_id}


@router.get("/jobs/{job_id}", tags=["Evaluation"])
async def get_evaluation_job(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(EvaluationJob).where(EvaluationJob.job_id == job_id))
    job    = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id":     job.job_id,
        "status":     job.status,
        "result":     job.result,
        "error":      job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.get("/agents/{aaip_agent_id}/evaluations", tags=["Evaluation"])
async def get_agent_evaluations(
    aaip_agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    evaluations = await get_evaluation_history(db, aaip_agent_id, limit)
    return {"agent_id": aaip_agent_id, "evaluations": evaluations, "count": len(evaluations)}


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.post("/discovery/register", tags=["Discovery"])
async def register_discovery_manifest(
    request: DiscoveryRegisterRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    try:
        if request.manifest is not None:
            manifest_url = (
                str(request.manifest_url)
                if request.manifest_url
                else f"aaip://local/{request.manifest.owner}/{request.manifest.agent_name}"
            )
            return await upsert_discovered_agent(
                db=db, manifest=request.manifest, manifest_url=manifest_url,
                discovery_status="active", crawl_status="manual",
            )
        if request.manifest_url is not None:
            return await crawl_and_register_agent(
                db=db, manifest_url=str(request.manifest_url), path_hints=request.path_hints,
            )
        raise HTTPException(status_code=400, detail="manifest or manifest_url is required")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch manifest: {e}")


@router.post("/discovery/crawl", tags=["Discovery"])
async def crawl_discovery_endpoint(base_url: str, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await crawl_and_register_agent(db=db, base_url=base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to crawl: {e}")


@router.get("/discovery/agents", tags=["Discovery"])
async def list_discovery_agents(
    domain: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    capability: Optional[str] = Query(None),
    min_reputation: Optional[float] = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agents = await list_discoverable_agents(db=db, domain=domain or capability, tag=tag, limit=limit)
    if min_reputation is not None:
        agents = [a for a in agents if (a.get("reputation_score") or 0) >= min_reputation]
    return {"agents": agents, "count": len(agents)}


@router.get("/agents/{aaip_agent_id}/discovery", tags=["Discovery"])
async def get_agent_discovery(aaip_agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    profile = await get_discovery_profile(db, aaip_agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Discovery profile not found")
    return profile


@router.get("/agents/{aaip_agent_id}/manifest", tags=["Discovery"])
async def get_agent_manifest(aaip_agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    profile = await get_discovery_profile(db, aaip_agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return profile["manifest"]


# ── Benchmarks & Judges ───────────────────────────────────────────────────────

@router.get("/benchmarks/datasets", tags=["Benchmarks"])
async def get_benchmark_datasets(
    domain: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"datasets": await list_benchmark_datasets(db, domain)}


@router.get("/benchmarks/{domain}/judges", tags=["Benchmarks"])
async def get_domain_judges(domain: str, db: AsyncSession = Depends(get_db)) -> dict:
    return {
        "domain":        domain,
        "judges":        await get_judges_for_domain(domain, num_judges=5),
        "custom_judges": await list_custom_judges(db, domain),
    }


@router.get("/benchmarks/{domain}/rankings", tags=["Benchmarks"])
async def get_domain_rankings(domain: str) -> dict:
    return {"domain": domain, "rankings": await get_benchmark_rankings(domain)}


@router.post("/judges/custom", tags=["Benchmarks"])
async def create_custom_judge_endpoint(
    request: CustomJudgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    return await create_custom_judge(db, request)


@router.get("/judges/custom", tags=["Benchmarks"])
async def get_custom_judges_endpoint(
    domain: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"judges": await list_custom_judges(db, domain)}


@router.delete("/judges/custom/{judge_id}", tags=["Benchmarks"])
async def delete_custom_judge_endpoint(
    judge_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    deleted = await deactivate_custom_judge(db, judge_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Judge not found")
    return {"status": "deleted", "judge_id": judge_id}


# ── Domains & Network Stats ───────────────────────────────────────────────────

@router.get("/domains", tags=["System"])
async def list_domains(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(Agent.domain, func.count(Agent.id).label("count"))
        .group_by(Agent.domain)
        .order_by(func.count(Agent.id).desc())
    )
    db_domains = [{"domain": row[0], "agent_count": row[1]} for row in result]
    return {
        "domains": db_domains,
        "note":    "Domains are open tags — any capability string is valid",
        "examples": ["coding", "finance", "general", "translation", "image_generation"],
    }


@router.get("/stats/network", tags=["System"])
async def get_network_stats(db: AsyncSession = Depends(get_db)) -> dict:
    total_agents      = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    total_evaluations = (await db.execute(select(func.count(Evaluation.id)))).scalar() or 0
    avg_score         = (await db.execute(select(func.avg(Evaluation.final_score)))).scalar() or 0

    result = await db.execute(
        select(Evaluation.task_domain, func.count(Evaluation.id), func.avg(Evaluation.final_score))
        .group_by(Evaluation.task_domain)
    )
    domain_stats = {
        row[0]: {"count": row[1], "average_score": round(float(row[2]), 2) if row[2] else 0}
        for row in result
    }

    recent = (
        await db.execute(select(Evaluation).order_by(Evaluation.timestamp.desc()).limit(10))
    ).scalars().all()

    return {
        "total_agents":          total_agents,
        "total_evaluations":     total_evaluations,
        "average_network_score": round(float(avg_score), 2),
        "domain_breakdown":      domain_stats,
        "recent_activity": [
            {
                "evaluation_id": str(e.id),
                "agent_id":      str(e.agent_id),
                "domain":        e.task_domain,
                "score":         e.final_score,
                "timestamp":     e.timestamp.isoformat(),
            }
            for e in recent
        ],
    }
