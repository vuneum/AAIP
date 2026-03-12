"""Benchmark dataset registry for AAIP."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import BenchmarkDataset

DEFAULT_DATASETS = [
    {
        "dataset_id": "bench-code-mini",
        "name": "Code Reliability Mini",
        "domain": "coding",
        "description": "Seed coding benchmark set for correctness and edge-case coverage.",
        "task_count": 25,
        "source": "internal",
        "metadata_json": {"categories": ["algorithms", "bugfix", "testing"]},
    },
    {
        "dataset_id": "bench-fin-risk-mini",
        "name": "Finance Risk Review Mini",
        "domain": "finance",
        "description": "Seed finance benchmark focused on reasoning, caution, and unsupported claims.",
        "task_count": 20,
        "source": "internal",
        "metadata_json": {"categories": ["forecasting", "risk", "analysis"]},
    },
    {
        "dataset_id": "bench-general-qa-mini",
        "name": "General QA Mini",
        "domain": "general",
        "description": "Seed general benchmark focused on factuality and completeness.",
        "task_count": 30,
        "source": "internal",
        "metadata_json": {"categories": ["qa", "reasoning", "summarization"]},
    },
]


async def seed_default_datasets(db: AsyncSession) -> None:
    result = await db.execute(select(BenchmarkDataset.id).limit(1))
    if result.first():
        return
    db.add_all([BenchmarkDataset(**item) for item in DEFAULT_DATASETS])
    await db.commit()


async def list_benchmark_datasets(db: AsyncSession, domain: str | None = None) -> list[dict]:
    query = select(BenchmarkDataset).order_by(BenchmarkDataset.created_at.desc())
    if domain:
        query = query.where(BenchmarkDataset.domain == domain)
    result = await db.execute(query)
    return [serialize_dataset(item) for item in result.scalars().all()]


async def get_dataset_by_dataset_id(db: AsyncSession, dataset_id: str) -> dict | None:
    result = await db.execute(select(BenchmarkDataset).where(BenchmarkDataset.dataset_id == dataset_id))
    item = result.scalar_one_or_none()
    return serialize_dataset(item) if item else None


def serialize_dataset(item: BenchmarkDataset) -> dict:
    return {
        "dataset_id": item.dataset_id,
        "name": item.name,
        "domain": item.domain,
        "description": item.description,
        "task_count": item.task_count,
        "source": item.source,
        "metadata": item.metadata_json or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
