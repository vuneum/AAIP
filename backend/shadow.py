"""
AAIP — Shadow Mode

Lets developers run the full AAIP validation pipeline in simulation:
  - PoE trace verification         ✓ (real)
  - AI jury evaluation             ✓ (real, but not stored in prod stats)
  - CAV benchmark check            ✓ (real, simulated result)
  - Escrow / payment               ✗ (simulated only)
  - Reputation update              ✗ (simulated only — delta shown but not applied)

Everything runs, nothing permanent is written to live agent stats.
Developer gets a detailed report explaining what would have happened.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select, Column, String, Text, Float, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from database import Base


# ─────────────────────────────────────────────
# DB Model
# ─────────────────────────────────────────────

class ShadowSession(Base):
    __tablename__ = "shadow_sessions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id     = Column(String(50), unique=True, nullable=False, index=True)
    aaip_agent_id  = Column(String(200), nullable=False, index=True)
    status         = Column(String(50), nullable=False, default="active")
    # active | completed | expired
    report_json    = Column(JSONB, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    expires_at     = Column(DateTime, nullable=False)
    completed_at   = Column(DateTime, nullable=True)


# ─────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────

class StartShadowRequest(BaseModel):
    aaip_agent_id: str
    ttl_hours: int = Field(default=24, ge=1, le=72)


class RunShadowRequest(BaseModel):
    task_description: str = Field(..., min_length=5)
    agent_output:     str = Field(..., min_length=1)
    domain:           str = "general"
    trace:            Optional[dict] = None
    poe_hash:         Optional[str] = None


class ShadowReport(BaseModel):
    session_id:               str
    aaip_agent_id:            str
    task_description:         str
    domain:                   str

    # PoE
    poe_trace_received:       bool
    poe_hash_verified:        bool
    poe_fraud_flags:          list[str]
    poe_verdict:              str

    # Jury
    simulated_jury_score:     float
    simulated_grade:          str
    simulated_passed:         bool
    judge_breakdown:          dict

    # CAV
    cav_audit_triggered:      bool
    cav_simulated_score:      Optional[float]
    cav_result:               Optional[str]

    # Payment
    simulated_payment_amount: str
    simulated_payment_currency: str
    payment_would_execute:    bool

    # Reputation
    current_reputation:       float
    reputation_delta:         float
    projected_reputation:     float

    # Feedback
    issues:                   list[str]
    recommendations:          list[str]
    production_ready:         bool

    completed_at:             str


class ShadowSessionResponse(BaseModel):
    session_id:    str
    aaip_agent_id: str
    status:        str
    created_at:    str
    expires_at:    str
    report:        Optional[dict] = None


# ─────────────────────────────────────────────
# Grade helper (mirrors evaluation.py)
# ─────────────────────────────────────────────

def score_to_grade(score: float) -> tuple[str, bool]:
    if score >= 95: return "Elite", True
    if score >= 90: return "Gold", True
    if score >= 80: return "Silver", True
    if score >= 70: return "Bronze", True
    return "Unrated", False


# ─────────────────────────────────────────────
# Core functions
# ─────────────────────────────────────────────

async def create_shadow_session(
    db: AsyncSession,
    request: StartShadowRequest,
) -> ShadowSessionResponse:
    """Create a new shadow mode session for an agent."""
    session_id = f"shadow_{secrets.token_hex(12)}"
    expires_at = datetime.utcnow() + timedelta(hours=request.ttl_hours)

    session = ShadowSession(
        session_id=session_id,
        aaip_agent_id=request.aaip_agent_id,
        status="active",
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return ShadowSessionResponse(
        session_id=session_id,
        aaip_agent_id=request.aaip_agent_id,
        status="active",
        created_at=session.created_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )


async def run_shadow_evaluation(
    db: AsyncSession,
    session_id: str,
    request: RunShadowRequest,
) -> ShadowReport:
    """
    Run the full AAIP pipeline in shadow mode.
    Everything is real except reputation writes and payment execution.
    """
    # 1. Fetch session
    result = await db.execute(
        select(ShadowSession).where(ShadowSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Shadow session not found: {session_id}")

    if session.status == "expired" or session.expires_at < datetime.utcnow():
        from fastapi import HTTPException
        raise HTTPException(status_code=410, detail="Shadow session has expired")

    aaip_agent_id = session.aaip_agent_id
    issues: list[str] = []
    recommendations: list[str] = []

    # ─ 2. PoE Trace verification ─────────────
    poe_trace_received = request.trace is not None
    poe_hash_verified  = False
    poe_fraud_flags:   list[str] = []
    poe_verdict        = "no_trace"

    if poe_trace_received and request.trace:
        try:
            from poe import (
                PoETraceInput, PoETraceStepInput,
                verify_hash, detect_fraud_signals,
            )
            trace_input = PoETraceInput(**request.trace)
            poe_hash_verified = verify_hash(trace_input, request.poe_hash or "") if request.poe_hash else False
            poe_fraud_flags = detect_fraud_signals(trace_input)

            if poe_fraud_flags:
                poe_verdict = "suspicious"
                issues.append(f"PoE fraud signals detected: {', '.join(poe_fraud_flags)}")
            elif poe_hash_verified:
                poe_verdict = "verified"
            else:
                poe_verdict = "unverified"
                recommendations.append("Submit poe_hash with your trace for full cryptographic verification.")
        except Exception as e:
            poe_verdict = "error"
            issues.append(f"PoE trace parsing error: {str(e)[:100]}")
    else:
        recommendations.append("Include a PoE trace for higher trust scores — agents with verified traces rank higher.")

    # ─ 3. Jury evaluation (real, shadow-flagged) ─
    try:
        from evaluation import evaluate_agent_output
        from database import Agent as AgentModel

        agent_result = await db.execute(
            select(AgentModel).where(AgentModel.aaip_agent_id == aaip_agent_id)
        )
        agent = agent_result.scalar_one_or_none()

        if agent:
            eval_result = await evaluate_agent_output(
                db=db,
                agent_id=aaip_agent_id,
                task_domain=request.domain,
                task_description=request.task_description,
                agent_output=request.agent_output,
                trace=request.trace,
                is_shadow=True,  # Flag: don't update live reputation stats
            )
            jury_score = float(eval_result.final_score)
            judge_breakdown = dict(eval_result.judge_scores or {})
        else:
            # Agent not registered — simulate score from output quality
            words = len(request.agent_output.split())
            jury_score = min(85.0, 40.0 + words * 0.3)
            judge_breakdown = {"simulated": jury_score}
            recommendations.append("Register your agent with AAIP before production to get real jury scores.")
    except Exception as e:
        jury_score = 70.0
        judge_breakdown = {"error": str(e)[:50]}
        issues.append("Jury evaluation encountered an error — check agent_output format.")

    grade, passed = score_to_grade(jury_score)

    if jury_score < 70:
        issues.append(f"Score {jury_score:.1f} is below the Bronze threshold (70). Agent needs improvement.")
    elif jury_score < 80:
        recommendations.append("Score is in Bronze range. Aim for 80+ (Silver) for better discovery ranking.")

    # ─ 4. CAV simulation ─────────────────────
    # 30% chance of CAV trigger per evaluation (mirrors real prod frequency)
    import random
    cav_triggered = random.random() < 0.30
    cav_score = None
    cav_result = None

    if cav_triggered:
        try:
            from cav import select_cav_task, score_cav_response
            task_data = select_cav_task(request.domain)
            cav_score = score_cav_response(request.agent_output, task_data)
            cav_result = "passed" if cav_score >= 60 else "failed"
            if cav_result == "failed":
                issues.append(f"CAV simulation failed (score: {cav_score:.1f}). Hidden benchmarks may penalise this agent.")
        except Exception:
            cav_triggered = False

    # ─ 5. Payment simulation ─────────────────
    simulated_amount = "0.0020"
    simulated_currency = "USDC"
    payment_would_execute = jury_score >= 70 and poe_verdict in ("verified", "unverified", "no_trace")

    if not payment_would_execute:
        issues.append("Payment would NOT execute — score below threshold or PoE marked suspicious.")

    # ─ 6. Reputation simulation ──────────────
    try:
        from reputation import get_agent_reputation_timeline
        rep_data = await get_agent_reputation_timeline(db, aaip_agent_id, days=7)
        current_rep = float(rep_data["summary"].get("current_reputation", 50.0))
    except Exception:
        current_rep = 50.0

    # Blended reputation delta (same formula as live system)
    reputation_delta = round((jury_score - current_rep) * 0.1, 2)
    projected_rep = round(min(100.0, max(0.0, current_rep + reputation_delta)), 1)

    if abs(reputation_delta) > 5:
        recommendations.append(f"This evaluation would shift reputation by {reputation_delta:+.1f} points → {projected_rep}.")

    # ─ 7. Production readiness ───────────────
    production_ready = (
        jury_score >= 70 and
        poe_verdict != "suspicious" and
        len([i for i in issues if "error" in i.lower()]) == 0
    )

    if not production_ready:
        recommendations.append("Resolve all issues above before enabling live transactions.")

    if not issues:
        recommendations.append("No issues found — agent looks production-ready.")

    # ─ Build report ──────────────────────────
    report = ShadowReport(
        session_id=session_id,
        aaip_agent_id=aaip_agent_id,
        task_description=request.task_description,
        domain=request.domain,
        poe_trace_received=poe_trace_received,
        poe_hash_verified=poe_hash_verified,
        poe_fraud_flags=poe_fraud_flags,
        poe_verdict=poe_verdict,
        simulated_jury_score=round(jury_score, 1),
        simulated_grade=grade,
        simulated_passed=passed,
        judge_breakdown=judge_breakdown,
        cav_audit_triggered=cav_triggered,
        cav_simulated_score=round(cav_score, 1) if cav_score is not None else None,
        cav_result=cav_result,
        simulated_payment_amount=simulated_amount,
        simulated_payment_currency=simulated_currency,
        payment_would_execute=payment_would_execute,
        current_reputation=round(current_rep, 1),
        reputation_delta=reputation_delta,
        projected_reputation=projected_rep,
        issues=issues,
        recommendations=recommendations,
        production_ready=production_ready,
        completed_at=datetime.utcnow().isoformat(),
    )

    # Save report to session
    session.status = "completed"
    session.completed_at = datetime.utcnow()
    session.report_json = report.model_dump()
    await db.commit()

    return report


async def get_shadow_session(db: AsyncSession, session_id: str) -> ShadowSessionResponse:
    result = await db.execute(
        select(ShadowSession).where(ShadowSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Shadow session not found")

    return ShadowSessionResponse(
        session_id=session.session_id,
        aaip_agent_id=session.aaip_agent_id,
        status=session.status,
        created_at=session.created_at.isoformat(),
        expires_at=session.expires_at.isoformat(),
        report=session.report_json,
    )


async def get_shadow_report(db: AsyncSession, session_id: str) -> dict:
    result = await db.execute(
        select(ShadowSession).where(ShadowSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Shadow session not found")
    if not session.report_json:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Shadow report not yet generated — run POST /shadow/sessions/{id}/run first")
    return session.report_json


# ─────────────────────────────────────────────
# Celery cleanup sync wrapper
# ─────────────────────────────────────────────

def cleanup_expired_sessions_sync() -> dict:
    """Mark expired sessions. Called by Celery beat."""
    import asyncio
    from database import get_sync_database_url
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    async def _run():
        engine = create_async_engine(get_sync_database_url().replace("postgresql://", "postgresql+asyncpg://"))
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as db:
            result = await db.execute(
                select(ShadowSession).where(
                    ShadowSession.expires_at < datetime.utcnow(),
                    ShadowSession.status == "active",
                )
            )
            expired = result.scalars().all()
            for s in expired:
                s.status = "expired"
            await db.commit()
            return {"expired_sessions_cleaned": len(expired)}

    return asyncio.run(_run())
