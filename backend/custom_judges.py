"""Custom judge registry and selection."""

import uuid
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import CustomJudge


class CustomJudgeCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    model_id: str = Field(..., min_length=2, max_length=200)
    domain: str = Field(..., pattern="^(coding|finance|general)$")
    provider: str = Field(default="openrouter", min_length=2, max_length=100)
    weight: float = Field(default=1.0, ge=0.1, le=5.0)
    system_prompt: Optional[str] = None
    config: dict = Field(default_factory=dict)


async def create_custom_judge(db: AsyncSession, request: CustomJudgeCreateRequest) -> dict:
    judge = CustomJudge(
        judge_id=f"judge-{uuid.uuid4().hex[:10]}",
        name=request.name,
        model_id=request.model_id,
        domain=request.domain,
        provider=request.provider,
        weight=request.weight,
        system_prompt=request.system_prompt,
        config=request.config,
    )
    db.add(judge)
    await db.commit()
    await db.refresh(judge)
    return serialize_judge(judge)


async def list_custom_judges(db: AsyncSession, domain: Optional[str] = None) -> list[dict]:
    query = select(CustomJudge).where(CustomJudge.is_active == 1).order_by(CustomJudge.created_at.desc())
    if domain:
        query = query.where(CustomJudge.domain == domain)
    result = await db.execute(query)
    return [serialize_judge(item) for item in result.scalars().all()]


async def get_custom_judges_for_domain(db: AsyncSession, domain: str) -> list[dict]:
    result = await db.execute(
        select(CustomJudge)
        .where(CustomJudge.domain == domain, CustomJudge.is_active == 1)
        .order_by(CustomJudge.weight.desc(), CustomJudge.created_at.asc())
    )
    judges = []
    for item in result.scalars().all():
        judges.append({
            "judge_id": item.judge_id,
            "rank": len(judges) + 1,
            "model_id": item.model_id,
            "name": item.name,
            "provider": item.provider,
            "weight": item.weight,
            "context_window": item.config.get("context_window", 128000),
            "pricing": item.config.get("pricing", {"prompt": 1.0, "completion": 1.0}),
            "custom": True,
            "system_prompt": item.system_prompt,
        })
    return judges


async def deactivate_custom_judge(db: AsyncSession, judge_id: str) -> bool:
    result = await db.execute(select(CustomJudge).where(CustomJudge.judge_id == judge_id))
    judge = result.scalar_one_or_none()
    if not judge:
        return False
    judge.is_active = 0
    await db.commit()
    return True


async def seed_default_custom_judges(db: AsyncSession) -> None:
    result = await db.execute(select(CustomJudge.id).limit(1))
    if result.first():
        return

    defaults = [
        CustomJudge(
            judge_id="judge-logic-panel",
            name="Logic Consistency Judge",
            model_id="openai/gpt-4o-mini",
            domain="general",
            provider="openrouter",
            weight=1.0,
            system_prompt="Focus on logical consistency and factual discipline.",
            config={"pricing": {"prompt": 0.15, "completion": 0.6}},
        ),
        CustomJudge(
            judge_id="judge-code-review",
            name="Code Review Judge",
            model_id="qwen/qwen-coder-turbo",
            domain="coding",
            provider="openrouter",
            weight=1.2,
            system_prompt="Focus on correctness, edge cases, and engineering quality.",
            config={"pricing": {"prompt": 0.2, "completion": 0.4}},
        ),
        CustomJudge(
            judge_id="judge-risk-review",
            name="Financial Risk Judge",
            model_id="anthropic/claude-3.5-sonnet",
            domain="finance",
            provider="openrouter",
            weight=1.3,
            system_prompt="Focus on risk, clarity, and unsupported claims.",
            config={"pricing": {"prompt": 3.0, "completion": 15.0}},
        ),
    ]
    db.add_all(defaults)
    await db.commit()


def serialize_judge(item: CustomJudge) -> dict:
    return {
        "judge_id": item.judge_id,
        "name": item.name,
        "model_id": item.model_id,
        "domain": item.domain,
        "provider": item.provider,
        "weight": item.weight,
        "system_prompt": item.system_prompt,
        "config": item.config or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
