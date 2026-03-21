"""
aaip/engine/queue.py — Durable Task Queue  v1.4.0

A production-grade queue with three backends:

  MemoryBackend   — fast, in-process, no durability (demo/test)
  FileBackend     — durable, JSON-file WAL, survives restarts
  RedisBackend    — durable, distributed, requires redis-py

Backend selection (AEP_QUEUE_BACKEND env var):
  memory  → MemoryBackend (default)
  file    → FileBackend   (AEP_QUEUE_PATH)
  redis   → RedisBackend  (AEP_REDIS_URL)

Features:
  - Job states: PENDING → RUNNING → COMPLETE | FAILED | CANCELLED
  - Per-job retry policy (max_retries, backoff_s)
  - Dead-letter queue (failed jobs that exhausted retries)
  - Cancellation support
  - Job TTL (auto-purge old completed jobs)
  - Queue statistics

Usage::

    async with TaskQueue(workers=3) as q:
        jid = await q.submit("Analyse Q1", cost=0.05, max_retries=2)
        job = await q.wait(jid, timeout=30)
        print(job.status, job.result)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

log = logging.getLogger("aaip.engine.queue")


# ── Job model ─────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETE  = "complete"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    DEAD      = "dead"           # exhausted retries → dead-letter


@dataclasses.dataclass
class Job:
    job_id:       str
    task:         str
    agent_id:     str
    cost:         float            = 0.0
    currency:     str              = "ETH"
    max_retries:  int              = 0
    backoff_s:    float            = 1.0
    status:       JobStatus        = JobStatus.PENDING
    result:       dict[str, Any]   = dataclasses.field(default_factory=dict)
    error:        str | None       = None
    attempts:     int              = 0
    created_at:   float            = dataclasses.field(default_factory=time.time)
    started_at:   float | None     = None
    finished_at:  float | None     = None
    ttl_s:        float            = 3600.0      # auto-purge after 1h

    @property
    def elapsed(self) -> float | None:
        if self.started_at and self.finished_at:
            return round(self.finished_at - self.started_at, 3)
        return None

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETE, JobStatus.FAILED,
                               JobStatus.CANCELLED, JobStatus.DEAD)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d["status"] = JobStatus(d.get("status", "pending"))
        return cls(**d)


# ── Backends ──────────────────────────────────────────────────────────────────

class _MemoryBackend:
    """In-memory backend. Fast, zero-config, no durability."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: list[str]     = []   # job_id queue
        self._lock  = threading.Lock()

    def enqueue(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._queue.append(job.job_id)

    def dequeue(self) -> Job | None:
        with self._lock:
            while self._queue:
                jid = self._queue.pop(0)
                job = self._jobs.get(jid)
                if job and job.status == JobStatus.PENDING:
                    return job
        return None

    def update(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def requeue(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._queue.append(job.job_id)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                job.finished_at = time.time()
                return True
        return False

    def purge_expired(self) -> int:
        cutoff = time.time()
        with self._lock:
            before = len(self._jobs)
            to_del = [
                jid for jid, j in self._jobs.items()
                if j.is_terminal and j.finished_at
                and (cutoff - j.finished_at) > j.ttl_s
            ]
            for jid in to_del:
                del self._jobs[jid]
        return len(to_del)

    def dead_letters(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status == JobStatus.DEAD]

    def stats(self) -> dict[str, Any]:
        jobs = list(self._jobs.values())
        return {
            "total":    len(jobs),
            "pending":  sum(1 for j in jobs if j.status == JobStatus.PENDING),
            "running":  sum(1 for j in jobs if j.status == JobStatus.RUNNING),
            "complete": sum(1 for j in jobs if j.status == JobStatus.COMPLETE),
            "failed":   sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "dead":     sum(1 for j in jobs if j.status == JobStatus.DEAD),
            "cancelled":sum(1 for j in jobs if j.status == JobStatus.CANCELLED),
            "backend":  "memory",
        }


class _FileBackend:
    """
    Durable file-based backend.

    Jobs are persisted as newline-delimited JSON in AEP_QUEUE_PATH.
    On startup the file is replayed — RUNNING jobs are reset to PENDING
    (they were interrupted mid-flight) and re-enqueued.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path or os.environ.get("AEP_QUEUE_PATH",
                          str(Path.home() / ".aaip-queue.jsonl")))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock  = threading.Lock()
        self._mem   = _MemoryBackend()
        self._restore()

    def _restore(self) -> None:
        """Load existing jobs and reset any that were mid-flight."""
        if not self._path.exists():
            return
        seen: dict[str, Job] = {}
        try:
            with self._path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    job = Job.from_dict(json.loads(line))
                    seen[job.job_id] = job
        except Exception as e:
            log.warning("Queue restore partial failure: %s", e)

        restored = 0
        for job in seen.values():
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.PENDING  # reset interrupted jobs
                job.started_at = None
            self._mem._jobs[job.job_id] = job
            if job.status == JobStatus.PENDING:
                self._mem._queue.append(job.job_id)
                restored += 1

        if restored:
            log.info("Queue restored: %d jobs re-enqueued", restored)

    def _persist(self, job: Job) -> None:
        """Append job state to WAL file (atomic line write)."""
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(job.to_dict()) + "\n")
        except Exception as e:
            log.error("Queue persist failed: %s", e)

    def _compact(self) -> None:
        """Rewrite file with only latest state per job (garbage collect)."""
        jobs = list(self._mem._jobs.values())
        tmp  = self._path.with_suffix(".tmp")
        with tmp.open("w") as f:
            for job in jobs:
                if not job.is_terminal:
                    f.write(json.dumps(job.to_dict()) + "\n")
        tmp.replace(self._path)

    def enqueue(self, job: Job) -> None:
        self._mem.enqueue(job)
        self._persist(job)

    def dequeue(self) -> Job | None:
        return self._mem.dequeue()

    def update(self, job: Job) -> None:
        self._mem.update(job)
        self._persist(job)

    def requeue(self, job: Job) -> None:
        self._mem.requeue(job)
        self._persist(job)

    def get(self, job_id: str) -> Job | None:
        return self._mem.get(job_id)

    def all(self) -> list[Job]:
        return self._mem.all()

    def cancel(self, job_id: str) -> bool:
        ok = self._mem.cancel(job_id)
        if ok:
            self._persist(self._mem.get(job_id))
        return ok

    def purge_expired(self) -> int:
        n = self._mem.purge_expired()
        if n:
            self._compact()
        return n

    def dead_letters(self) -> list[Job]:
        return self._mem.dead_letters()

    def stats(self) -> dict[str, Any]:
        s = self._mem.stats()
        s["backend"] = "file"
        s["path"]    = str(self._path)
        return s


class _RedisBackend:
    """
    Redis-backed durable queue.

    Uses BLPOP for efficient blocking dequeue.
    Jobs stored as Redis hashes keyed by job_id.
    Dead-letter jobs pushed to a separate list.

    Requires: pip install redis
    Configured via: AEP_REDIS_URL (default redis://localhost:6379/0)
    """

    _QUEUE_KEY = "aaip:queue:pending"
    _DEAD_KEY  = "aaip:queue:dead"
    _JOB_PREFIX = "aaip:job:"

    def __init__(self, url: str | None = None) -> None:
        try:
            import redis
        except ImportError:
            raise ImportError("redis-py is not installed. Run: pip install redis")

        self._url = url or os.environ.get("AEP_REDIS_URL", "redis://localhost:6379/0")
        import redis as redis_lib
        self._r = redis_lib.from_url(self._url, decode_responses=True)
        self._r.ping()
        self._mem = _MemoryBackend()   # in-memory mirror for fast reads
        self._restore_from_redis()
        log.info("RedisBackend connected: %s", self._url)

    def _restore_from_redis(self) -> None:
        keys = self._r.keys(f"{self._JOB_PREFIX}*")
        for key in keys:
            data = self._r.hgetall(key)
            if data:
                try:
                    job = Job.from_dict({k: json.loads(v) if v.startswith(('{','[','"')) else v for k, v in data.items()})
                    self._mem._jobs[job.job_id] = job
                except Exception:
                    pass

    def _save_job(self, job: Job) -> None:
        key = f"{self._JOB_PREFIX}{job.job_id}"
        d = job.to_dict()
        self._r.hset(key, mapping={k: json.dumps(v) for k, v in d.items()})
        if job.ttl_s > 0:
            self._r.expire(key, int(job.ttl_s))

    def enqueue(self, job: Job) -> None:
        self._mem.enqueue(job)
        self._save_job(job)
        self._r.rpush(self._QUEUE_KEY, job.job_id)

    def dequeue(self) -> Job | None:
        result = self._r.blpop(self._QUEUE_KEY, timeout=0.1)
        if not result:
            return None
        _, job_id = result
        data = self._r.hgetall(f"{self._JOB_PREFIX}{job_id}")
        if not data:
            return None
        try:
            job = Job.from_dict({k: json.loads(v) if v.startswith(('{','[','"','t','f')) else v for k, v in data.items()})
            return job if job.status == JobStatus.PENDING else None
        except Exception:
            return None

    def update(self, job: Job) -> None:
        self._mem.update(job)
        self._save_job(job)

    def requeue(self, job: Job) -> None:
        self._mem.requeue(job)
        self._save_job(job)
        self._r.rpush(self._QUEUE_KEY, job.job_id)

    def get(self, job_id: str) -> Job | None:
        job = self._mem.get(job_id)
        if job:
            return job
        data = self._r.hgetall(f"{self._JOB_PREFIX}{job_id}")
        if not data:
            return None
        return Job.from_dict({k: json.loads(v) if v.startswith(('{','[','"')) else v for k, v in data.items()})

    def all(self) -> list[Job]:
        return self._mem.all()

    def cancel(self, job_id: str) -> bool:
        ok = self._mem.cancel(job_id)
        if ok:
            self._save_job(self._mem.get(job_id))
        return ok

    def purge_expired(self) -> int:
        return self._mem.purge_expired()

    def dead_letters(self) -> list[Job]:
        ids = self._r.lrange(self._DEAD_KEY, 0, -1)
        return [j for j in (self.get(jid) for jid in ids) if j]

    def stats(self) -> dict[str, Any]:
        s = self._mem.stats()
        s["backend"]   = "redis"
        s["queue_len"] = self._r.llen(self._QUEUE_KEY)
        s["dead_len"]  = self._r.llen(self._DEAD_KEY)
        s["redis_url"] = self._url
        return s


# ── Backend factory ───────────────────────────────────────────────────────────

def _make_backend():
    name = os.environ.get("AEP_QUEUE_BACKEND", "memory").lower()
    if name == "file":
        return _FileBackend()
    if name == "redis":
        return _RedisBackend()
    return _MemoryBackend()


# ── Default executor ──────────────────────────────────────────────────────────

async def _default_executor(job: Job) -> dict[str, Any]:
    import concurrent.futures
    loop = asyncio.get_event_loop()

    def _run():
        from aaip.engine import execution_engine, payment_manager
        from aaip.schemas.models import PaymentRequest
        exec_result = execution_engine.run_task(
            task_description=job.task,
            agent_id=job.agent_id,
            fast=True,
        )
        receipt = None
        if job.cost > 0:
            from aaip.orchestrator import DEMO_RECIPIENT
            req = PaymentRequest(
                agent_id=job.agent_id,
                recipient_address=DEMO_RECIPIENT,
                amount=job.cost,
                poe_hash=exec_result["poe_hash"],
                metadata={"job_id": job.job_id},
            )
            receipt = payment_manager.process_payment(req)
        return {
            "poe_hash":   exec_result["poe_hash"],
            "steps":      exec_result["trace"]["step_count"],
            "tokens":     exec_result["trace"]["total_tokens"],
            "receipt_id": receipt.receipt_id if receipt else None,
            "tx_hash":    receipt.tx_hash    if receipt else None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _run)


# ── TaskQueue ─────────────────────────────────────────────────────────────────

class TaskQueue:
    """
    Asyncio task queue with:
      - Pluggable durable backend (memory / file / redis)
      - Per-job retry with exponential backoff
      - Dead-letter queue for exhausted jobs
      - Cancellation
      - Job TTL + auto-purge
      - Queue-level statistics
    """

    def __init__(
        self,
        workers: int = 3,
        executor_fn: Callable[[Job], Awaitable[dict]] | None = None,
        backend=None,
    ) -> None:
        self._workers     = workers
        self._executor_fn = executor_fn or _default_executor
        self._backend     = backend or _make_backend()
        self._futures:    dict[str, asyncio.Future] = {}
        self._worker_tasks: list[asyncio.Task]      = []
        self._running     = False
        self._purge_task: asyncio.Task | None       = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self._workers):
            t = asyncio.create_task(self._worker(i), name=f"aep-worker-{i}")
            self._worker_tasks.append(t)
        self._purge_task = asyncio.create_task(self._purge_loop(), name="aep-purge")
        log.info("TaskQueue started: workers=%d backend=%s",
                 self._workers, type(self._backend).__name__)

    async def stop(self) -> None:
        self._running = False
        if self._purge_task:
            self._purge_task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        log.info("TaskQueue stopped")

    async def __aenter__(self):
        await self.start(); return self

    async def __aexit__(self, *_):
        await self.stop()

    # ── Job submission ────────────────────────────────────────────────────

    async def submit(
        self,
        task: str,
        agent_id: str = "agent_beta_01",
        cost: float = 0.0,
        currency: str = "ETH",
        max_retries: int = 0,
        backoff_s: float = 1.0,
        ttl_s: float = 3600.0,
    ) -> str:
        job = Job(
            job_id=str(uuid.uuid4()),
            task=task,
            agent_id=agent_id,
            cost=cost,
            currency=currency,
            max_retries=max_retries,
            backoff_s=backoff_s,
            ttl_s=ttl_s,
        )
        fut = asyncio.get_event_loop().create_future()
        self._futures[job.job_id] = fut
        self._backend.enqueue(job)
        log.debug("Job enqueued: %s  task=%.40s", job.job_id[:8], task)
        return job.job_id

    async def wait(self, job_id: str, timeout: float = 60.0) -> Job:
        fut = self._futures.get(job_id)
        if fut is None:
            # Reconstruct a future from backend state (for pre-existing jobs)
            job = self._backend.get(job_id)
            if not job:
                raise KeyError(f"Unknown job_id: {job_id}")
            if job.is_terminal:
                return job
            raise KeyError(f"Job {job_id} has no waitable future in this process")
        await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        return self._backend.get(job_id)

    def cancel(self, job_id: str) -> bool:
        ok = self._backend.cancel(job_id)
        if ok:
            fut = self._futures.pop(job_id, None)
            if fut and not fut.done():
                fut.set_result(self._backend.get(job_id))
        return ok

    def get_job(self, job_id: str) -> Job | None:
        return self._backend.get(job_id)

    def all_jobs(self) -> list[Job]:
        return self._backend.all()

    def dead_letters(self) -> list[Job]:
        return self._backend.dead_letters()

    def stats(self) -> dict[str, Any]:
        s = self._backend.stats()
        s["workers"] = self._workers
        return s

    # ── Worker ────────────────────────────────────────────────────────────

    async def _worker(self, worker_id: int) -> None:
        log.debug("Worker %d started", worker_id)
        while self._running:
            job = self._backend.dequeue()
            if job is None:
                await asyncio.sleep(0.05)
                continue

            job.status     = JobStatus.RUNNING
            job.started_at = time.time()
            job.attempts  += 1
            self._backend.update(job)
            log.debug("Worker %d executing job %s (attempt %d)", worker_id, job.job_id[:8], job.attempts)

            try:
                result       = await self._executor_fn(job)
                job.result   = result
                job.status   = JobStatus.COMPLETE
                job.finished_at = time.time()
                self._backend.update(job)
                log.info("Job %s complete in %.2fs", job.job_id[:8], job.elapsed)

            except Exception as exc:
                job.error = str(exc)
                log.warning("Job %s failed (attempt %d/%d): %s",
                            job.job_id[:8], job.attempts, job.max_retries + 1, exc)

                if job.attempts <= job.max_retries:
                    # Retry with exponential backoff
                    backoff = job.backoff_s * (2 ** (job.attempts - 1))
                    log.info("Retrying job %s in %.1fs", job.job_id[:8], backoff)
                    await asyncio.sleep(backoff)
                    job.status = JobStatus.PENDING
                    self._backend.requeue(job)
                    continue
                else:
                    # Dead-letter
                    job.status      = JobStatus.DEAD
                    job.finished_at = time.time()
                    self._backend.update(job)
                    log.error("Job %s dead-lettered after %d attempts", job.job_id[:8], job.attempts)

            finally:
                fut = self._futures.get(job.job_id)
                if fut and not fut.done():
                    fut.set_result(job)

    async def _purge_loop(self) -> None:
        """Periodically remove expired terminal jobs."""
        while True:
            await asyncio.sleep(300)   # every 5 minutes
            try:
                n = self._backend.purge_expired()
                if n:
                    log.info("Purged %d expired jobs", n)
            except Exception as e:
                log.warning("Purge failed: %s", e)
