"""
routers/agents.py
Agent registration, retrieval, manifest, and badge endpoints.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_api_key, APIKey
from database import get_db
from registry import (
    register_agent, get_agent_by_arpp_id, get_all_agents, get_agent_stats,
    AgentRegisterRequest, AgentRegisterResponse, AgentInfo,
)
from reputation import get_agent_reputation_timeline
from traces import get_trace_stats
from poe import get_agent_poe_stats
from discovery import DiscoveryManifest, upsert_discovered_agent, get_discovery_profile

router = APIRouter(tags=["Agents"])


@router.post("/agents/register", response_model=AgentRegisterResponse)
async def register_agent_endpoint(
    request: AgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> AgentRegisterResponse:
    """Register an agent with AAIP. AAIP does not build your agent — you register one you built."""
    try:
        return await register_agent(
            db=db,
            company_name=request.company_name,
            agent_name=request.agent_name,
            domain=request.domain,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents(db: AsyncSession = Depends(get_db)) -> list[AgentInfo]:
    return await get_all_agents(db)


@router.get("/agents/{aaip_agent_id}")
async def get_agent(aaip_agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    agent = await get_agent_by_arpp_id(db, aaip_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    stats       = await get_agent_stats(db, agent.id)
    trace_stats = await get_trace_stats(db, agent.id)
    reputation  = await get_agent_reputation_timeline(db, aaip_agent_id, days=30)
    poe_stats   = await get_agent_poe_stats(db, aaip_agent_id)

    return {
        "agent": {
            "aaip_agent_id": agent.aaip_agent_id,
            "company_name":  agent.company_name,
            "agent_name":    agent.agent_name,
            "domain":        agent.domain,
            "version":       agent.version,
            "created_at":    agent.created_at.isoformat(),
        },
        "statistics":  stats,
        "trace_stats": trace_stats,
        "poe_stats":   poe_stats,
        "reputation":  reputation["summary"],
    }


@router.post("/agents/{aaip_agent_id}/manifest/update")
async def update_agent_manifest(
    aaip_agent_id: str,
    manifest: dict,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    """Update an existing agent's manifest."""
    agent = await get_agent_by_arpp_id(db, aaip_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        dm           = DiscoveryManifest(**manifest)
        manifest_url = f"aaip://local/{dm.owner}/{dm.agent_name}"
        await upsert_discovered_agent(
            db=db, manifest=dm, manifest_url=manifest_url,
            discovery_status="active", crawl_status="manual",
        )
        return {"status": "updated", "aaip_agent_id": aaip_agent_id, "manifest": manifest}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/agents/{aaip_agent_id}/badge")
async def get_agent_badge(aaip_agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get badge data for embedding in README or websites."""
    agent = await get_agent_by_arpp_id(db, aaip_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    stats      = await get_agent_stats(db, agent.id)
    reputation = await get_agent_reputation_timeline(db, aaip_agent_id, days=30)
    score      = reputation["summary"].get("current_reputation", 0)
    count      = stats.get("total_evaluations", 0)

    if score >= 95:   grade, color = "Elite",   "gold"
    elif score >= 90: grade, color = "Gold",    "yellow"
    elif score >= 80: grade, color = "Silver",  "lightgrey"
    elif score >= 70: grade, color = "Bronze",  "orange"
    else:             grade, color = "Unrated", "red"

    label      = "AAIP Score"
    message    = f"{score:.0f} ({grade})"
    shield_url = f"https://img.shields.io/badge/{label.replace(' ', '_')}-{message.replace(' ', '_')}-{color}"
    return {
        "aaip_agent_id":   aaip_agent_id,
        "agent_name":      agent.agent_name,
        "score":           round(score, 1),
        "grade":           grade,
        "evaluation_count": count,
        "badge": {
            "label":      label,
            "message":    message,
            "color":      color,
            "shield_url": shield_url,
            "markdown":   f"[![AAIP Score]({shield_url})](https://vuneum.com/agents/{aaip_agent_id})",
            "html":       f'<img src="{shield_url}" alt="AAIP Score">',
        },
    }
