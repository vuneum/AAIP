"""
routers/cav.py
Continuous Agent Verification and Shadow Mode endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_api_key, require_api_key, APIKey
from database import get_db
from registry import get_agent_by_arpp_id
from cav import run_cav_cycle, get_agent_cav_status, get_cav_history, run_cav_for_agent
from shadow import (
    create_shadow_session, run_shadow_evaluation, get_shadow_session, get_shadow_report,
    StartShadowRequest, RunShadowRequest,
)

router = APIRouter(tags=["CAV"])
shadow_router = APIRouter(tags=["Shadow Mode"])


@router.post("/cav/trigger")
async def trigger_cav_cycle(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_api_key),
) -> dict:
    """Manually trigger a CAV audit cycle (normally runs hourly via Celery)."""
    return await run_cav_cycle(db)


@router.post("/cav/agents/{aaip_agent_id}/audit")
async def audit_single_agent(
    aaip_agent_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_api_key),
) -> dict:
    """Trigger a CAV audit for a specific agent."""
    agent = await get_agent_by_arpp_id(db, aaip_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await run_cav_for_agent(db, agent, triggered_by="manual")


@router.get("/cav/agents/{aaip_agent_id}/status")
async def get_cav_agent_status(
    aaip_agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_agent_cav_status(db, aaip_agent_id)


@router.get("/cav/agents/{aaip_agent_id}/history")
async def get_cav_agent_history(
    aaip_agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "aaip_agent_id": aaip_agent_id,
        "history": await get_cav_history(db, aaip_agent_id, limit),
    }


@shadow_router.post("/shadow/sessions")
async def start_shadow_session(
    request: StartShadowRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> dict:
    """Start a shadow mode session — runs full AAIP pipeline without live reputation effects."""
    return await create_shadow_session(db, request)


@shadow_router.post("/shadow/sessions/{session_id}/run")
async def run_shadow_session(
    session_id: str,
    request: RunShadowRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a full shadow evaluation. Returns PoE verdict, jury score, CAV result, payment sim."""
    return await run_shadow_evaluation(db, session_id, request)


@shadow_router.get("/shadow/sessions/{session_id}")
async def get_shadow_session_endpoint(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_shadow_session(db, session_id)


@shadow_router.get("/shadow/sessions/{session_id}/report")
async def get_shadow_report_endpoint(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await get_shadow_report(db, session_id)
