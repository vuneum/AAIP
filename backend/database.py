"""
AAIP - Database Module
Async SQLAlchemy models and session management
"""

import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import create_engine, text

Base = declarative_base()


class Agent(Base):
    __tablename__ = 'agents'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aaip_agent_id = Column(String(100), unique=True, nullable=False, index=True)
    company_name = Column(String(200), nullable=False)
    agent_name = Column(String(200), nullable=False)
    domain = Column(String(50), nullable=False)
    version = Column(String(50), default="1.0.0")
    created_at = Column(DateTime, default=datetime.utcnow)

    evaluations = relationship("Evaluation", back_populates="agent")
    traces = relationship("AgentTrace", back_populates="agent")
    jobs = relationship("EvaluationJob", back_populates="agent")


class AgentDiscoveryProfile(Base):
    __tablename__ = 'agent_discovery_profiles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'), nullable=False, unique=True)
    manifest_url = Column(String(500), nullable=False, unique=True, index=True)
    endpoint_url = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    domains = Column(JSONB, nullable=False, default=list)
    tools = Column(JSONB, nullable=False, default=list)
    tags = Column(JSONB, nullable=False, default=list)
    public_key = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    evaluation_snapshot = Column(JSONB, nullable=False, default=dict)
    manifest_json = Column(JSONB, nullable=False, default=dict)
    discovery_status = Column(String(50), nullable=False, default='active')
    crawl_status = Column(String(50), nullable=False, default='success')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", backref="discovery_profile")


class BenchmarkCache(Base):
    __tablename__ = 'benchmark_cache'

    id = Column(Integer, primary_key=True)
    domain = Column(String(50), unique=True, nullable=False, index=True)
    rankings = Column(JSONB, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow)


class CustomJudge(Base):
    __tablename__ = 'custom_judges'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    judge_id = Column(String(120), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    model_id = Column(String(200), nullable=False)
    domain = Column(String(50), nullable=False)
    provider = Column(String(100), nullable=False, default="openrouter")
    weight = Column(Float, nullable=False, default=1.0)
    system_prompt = Column(Text, nullable=True)
    config = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class BenchmarkDataset(Base):
    __tablename__ = 'benchmark_datasets'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(String(120), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    domain = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    task_count = Column(Integer, nullable=False, default=0)
    source = Column(String(200), nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class Evaluation(Base):
    __tablename__ = 'evaluations'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'), nullable=False)
    task_domain = Column(String(50), nullable=False)
    task_description = Column(Text, nullable=False)
    agent_output = Column(Text, nullable=False)
    output_embedding = Column(JSONB, nullable=True)
    judge_scores = Column(JSONB, nullable=False)
    judge_metadata = Column(JSONB, nullable=False, default=dict)
    benchmark_dataset_id = Column(String(120), nullable=True)
    benchmark_score = Column(Float, nullable=True)
    historical_reliability = Column(Float, nullable=True)
    rules_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=False)
    score_variance = Column(Float, nullable=True)
    confidence_interval_low = Column(Float, nullable=True)
    confidence_interval_high = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="evaluations")
    trace = relationship("AgentTrace", back_populates="evaluation", uselist=False)


class AgentTrace(Base):
    __tablename__ = 'agent_traces'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'), nullable=False)
    evaluation_id = Column(UUID(as_uuid=True), ForeignKey('evaluations.id'), nullable=True)
    task_domain = Column(String(50), nullable=False)
    tool_calls = Column(JSONB, nullable=False, default=list)
    reasoning_steps = Column(JSONB, nullable=False, default=list)
    token_usage = Column(JSONB, nullable=False, default=dict)
    latency_ms = Column(Integer, nullable=True)
    trace_metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="traces")
    evaluation = relationship("Evaluation", back_populates="trace")


class EvaluationJob(Base):
    __tablename__ = 'evaluation_jobs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String(120), unique=True, nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('agents.id'), nullable=False)
    status = Column(String(40), nullable=False, default='queued')
    payload = Column(JSONB, nullable=False)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = relationship("Agent", back_populates="jobs")


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://arpp:arpp_secret@db:5432/arpp"
    )


def get_sync_database_url() -> str:
    return get_database_url().replace("postgresql+asyncpg", "postgresql")


engine = None
async_session_maker: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global engine, async_session_maker
    if engine is None:
        engine = create_async_engine(get_database_url(), echo=False, future=True)
        async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if async_session_maker is None:
        await init_db()
    async with async_session_maker() as session:
        yield session


async def create_tables() -> None:
    sync_engine = create_engine(get_sync_database_url())
    with sync_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
