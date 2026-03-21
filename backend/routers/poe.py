"""
routers/poe.py
Proof of Execution submission and trace history endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_api_key, APIKey
from database import get_db
from poe import (
    submit_poe_trace, verify_poe_trace, get_agent_poe_stats,
    SubmitTraceRequest, TraceVerificationResult,
)
from traces import list_agent_traces

router = APIRouter(tags=["PoE"])


@router.post("/traces/submit")
async def submit_trace_endpoint(
    request: SubmitTraceRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    """Submit a Proof-of-Execution trace. Verifies hash, runs fraud detection, stores record."""
    return await submit_poe_trace(db, request)


@router.get("/traces/{trace_id}/verify", response_model=TraceVerificationResult)
async def verify_trace_endpoint(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> TraceVerificationResult:
    """Retrieve and verify a stored PoE trace by ID."""
    return await verify_poe_trace(db, trace_id)


@router.get("/agents/{aaip_agent_id}/traces")
async def get_agent_trace_history(
    aaip_agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    traces    = await list_agent_traces(db, aaip_agent_id, limit)
    poe_stats = await get_agent_poe_stats(db, aaip_agent_id)
    return {
        "agent_id":  aaip_agent_id,
        "traces":    traces,
        "count":     len(traces),
        "poe_stats": poe_stats,
    }
