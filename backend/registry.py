"""AAIP — Agent Registry Module (open capability domains)"""

import random
import string
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Agent


# Open domain — any alphanumeric tag, no hardcoded enum
class AgentRegisterRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    agent_name:   str = Field(..., min_length=1, max_length=200)
    domain:       str = Field(..., min_length=1, max_length=100)

    @field_validator("domain")
    @classmethod
    def clean_domain(cls, v: str) -> str:
        # Normalise: lowercase, strip whitespace, allow alphanumeric + underscore + hyphen
        cleaned = v.lower().strip().replace(" ", "_")
        if not all(c.isalnum() or c in "-_" for c in cleaned):
            raise ValueError("domain must be alphanumeric (hyphens and underscores allowed)")
        return cleaned


class AgentRegisterResponse(BaseModel):
    aaip_agent_id: str
    company_name:  str
    agent_name:    str
    domain:        str
    version:       str
    created_at:    datetime


class AgentInfo(BaseModel):
    id:            str
    aaip_agent_id: str
    company_name:  str
    agent_name:    str
    domain:        str
    version:       str
    created_at:    datetime


def generate_aaip_agent_id(company_name: str, agent_name: str) -> str:
    company_clean = "".join(c.lower() for c in company_name if c.isalnum())
    agent_clean   = "".join(c.lower() for c in agent_name if c.isalnum())
    random_id     = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{company_clean}/{agent_clean}/{random_id}"


async def register_agent(
    db: AsyncSession,
    company_name: str,
    agent_name: str,
    domain: str,
) -> AgentRegisterResponse:
    agent = Agent(
        aaip_agent_id=generate_aaip_agent_id(company_name, agent_name),
        company_name=company_name,
        agent_name=agent_name,
        domain=domain,
        version="1.0.0",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentRegisterResponse(
        aaip_agent_id=agent.aaip_agent_id,
        company_name=agent.company_name,
        agent_name=agent.agent_name,
        domain=agent.domain,
        version=agent.version,
        created_at=agent.created_at,
    )


async def get_agent_by_arpp_id(db: AsyncSession, aaip_agent_id: str):
    result = await db.execute(
        select(Agent).where(Agent.aaip_agent_id == aaip_agent_id)
    )
    return result.scalar_one_or_none()


async def get_all_agents(db: AsyncSession) -> list[AgentInfo]:
    result = await db.execute(select(Agent).order_by(Agent.created_at.desc()))
    return [
        AgentInfo(
            id=str(a.id),
            aaip_agent_id=a.aaip_agent_id,
            company_name=a.company_name,
            agent_name=a.agent_name,
            domain=a.domain,
            version=a.version,
            created_at=a.created_at,
        )
        for a in result.scalars().all()
    ]


async def get_agent_stats(db: AsyncSession, agent_id) -> dict:
    from database import Evaluation
    from sqlalchemy import func

    total = (
        await db.execute(
            select(func.count(Evaluation.id)).where(Evaluation.agent_id == agent_id)
        )
    ).scalar() or 0

    avg = (
        await db.execute(
            select(func.avg(Evaluation.final_score)).where(Evaluation.agent_id == agent_id)
        )
    ).scalar() or 0

    result = await db.execute(
        select(
            Evaluation.task_domain,
            func.avg(Evaluation.final_score),
            func.count(Evaluation.id),
        )
        .where(Evaluation.agent_id == agent_id)
        .group_by(Evaluation.task_domain)
    )
    domain_breakdown = {
        row[0]: {
            "average_score": round(float(row[1]), 2) if row[1] else 0,
            "count": row[2],
        }
        for row in result
    }

    return {
        "total_evaluations": total,
        "average_score": round(float(avg), 2),
        "domain_breakdown": domain_breakdown,
    }
