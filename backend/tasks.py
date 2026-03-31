"""AAIP — Celery async job worker."""

import asyncio
import os

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database import EvaluationJob, Agent

celery_app = Celery(
    "aaip",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    beat_schedule={
        # CAV: run every hour — randomly audits active agents
        "cav-hourly-audit": {
            "task": "aaip.cav_audit",
            "schedule": crontab(minute=0),  # top of every hour
        },
    },
)


@celery_app.task(name="aaip.evaluate_job")
def process_evaluation_job(job_id: str):
    """Process a queued evaluation job synchronously in Celery worker."""
    from database import get_sync_database_url
    from evaluation import evaluate_agent_output_sync

    engine = create_engine(get_sync_database_url())
    with Session(engine) as session:
        job = session.execute(
            select(EvaluationJob).where(EvaluationJob.job_id == job_id)
        ).scalar_one_or_none()
        if not job:
            return {"error": "job not found"}

        agent = session.execute(
            select(Agent).where(Agent.id == job.agent_id)
        ).scalar_one_or_none()
        if not agent:
            job.status = "failed"
            job.error = "Agent not found"
            session.commit()
            return {"error": job.error}

        job.status = "running"
        session.commit()

        try:
            result = asyncio.run(
                evaluate_agent_output_sync(
                    agent_id=str(agent.id),
                    task_domain=job.payload["task_domain"],
                    task_description=job.payload["task_description"],
                    agent_output=job.payload["agent_output"],
                    benchmark_dataset_id=job.payload.get("benchmark_dataset_id"),
                    trace=job.payload.get("trace"),
                    selected_judge_ids=job.payload.get("selected_judge_ids"),
                )
            )
            job.status = "completed"
            job.result = result
            session.commit()
            return result
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            session.commit()
            raise


@celery_app.task(name="aaip.cav_audit")
def run_cav_audit():
    """
    CAV hourly audit task.
    Selects random active agents and runs hidden benchmark evaluations.
    Imported here to avoid circular imports at module load time.
    """
    try:
        from cav import run_cav_audit_sync
        return run_cav_audit_sync()
    except Exception as exc:
        return {"error": str(exc), "task": "cav_audit"}


@celery_app.task(name="aaip.shadow_cleanup")
def cleanup_shadow_sessions():
    """Periodically clean up expired shadow mode sessions (>24h old)."""
    try:
        from shadow import cleanup_expired_sessions_sync
        return cleanup_expired_sessions_sync()
    except Exception as exc:
        return {"error": str(exc), "task": "shadow_cleanup"}
