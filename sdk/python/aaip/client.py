"""
AAIP Python SDK — Main Client
Autonomous Agent Infrastructure Protocol
https://aaip.dev
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .models import (
    AAIPError,
    AgentManifest,
    AuthError,
    DiscoveryResult,
    EvaluationResponse,
    LeaderboardEntry,
    NotFoundError,
    PaymentQuote,
    PoETrace,
    ReputationTimeline,
    ValidationError,
)

# ─────────────────────────────────────────────
# Base Client (shared logic)
# ─────────────────────────────────────────────

class _BaseClient:
    """Shared configuration and helpers."""

    DEFAULT_BASE_URL = "https://api.aaip.dev"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.environ.get("AAIP_API_KEY", "")
        self.base_url = (base_url or os.environ.get("AAIP_BASE_URL", self.DEFAULT_BASE_URL)).rstrip("/")  # noqa: E501
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "User-Agent": "aaip-python-sdk/1.0.0",
            "X-AAIP-Version": "1",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthError("Invalid or missing API key. Set AAIP_API_KEY or pass api_key=")
        if response.status_code == 404:
            raise NotFoundError(f"Resource not found: {response.url}")
        if response.status_code == 422:
            raise ValidationError(f"Validation error: {response.text}")
        if response.status_code >= 400:
            raise AAIPError(f"API error {response.status_code}: {response.text}")


# ─────────────────────────────────────────────
# Async Client
# ─────────────────────────────────────────────

class AsyncAAIPClient(_BaseClient):
    """
    Async AAIP client for Python async/await environments.

    Usage:
        async with AsyncAAIPClient(api_key="...") as client:
            agent = await client.register(manifest)
            result = await client.evaluate(agent_id, task, output)
    """

    def __init__(self, api_key=None, base_url=None, timeout=30.0):
        super().__init__(api_key, base_url, timeout)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(headers=self._headers(), timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(headers=self._headers(), timeout=self.timeout)
        return self._client

    async def _get(self, path: str, params: dict = None) -> Any:
        c = await self._get_client()
        r = await c.get(self._url(path), params=params)
        self._raise_for_status(r)
        return r.json()

    async def _post(self, path: str, body: dict = None) -> Any:
        c = await self._get_client()
        r = await c.post(self._url(path), json=body or {})
        self._raise_for_status(r)
        return r.json()

    async def _delete(self, path: str) -> Any:
        c = await self._get_client()
        r = await c.delete(self._url(path))
        self._raise_for_status(r)
        return r.json()

    # ── Identity & Registration ──────────────

    async def register(self, manifest: AgentManifest | dict) -> dict:
        """
        Register your agent with AAIP. Returns agent_id and registration details.
        AAIP does not create your agent — it registers an agent you already built.

        Args:
            manifest: AgentManifest or dict describing your agent's capabilities

        Returns:
            dict with aaip_agent_id, manifest_url, created_at
        """
        if isinstance(manifest, AgentManifest):
            body = {"manifest": manifest.to_dict()}
        else:
            body = {"manifest": manifest}
        return await self._post("/discovery/register", body)

    async def update_manifest(self, agent_id: str, manifest: AgentManifest | dict) -> dict:
        """Update an existing agent's manifest."""
        body = manifest.to_dict() if isinstance(manifest, AgentManifest) else manifest
        return await self._post(f"/agents/{agent_id}/manifest/update", body)

    async def get_agent(self, agent_id: str) -> dict:
        """Get full agent profile including reputation and trace stats."""
        return await self._get(f"/agents/{agent_id}")

    # ── Discovery ────────────────────────────

    async def discover(
        self,
        capability: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        min_reputation: float | None = None,
        limit: int = 20,
    ) -> list[DiscoveryResult]:
        """
        Discover agents by capability, domain, or tag.
        Results ranked by reputation score.

        Args:
            capability: e.g. "translation", "code_analysis", "image_generation"
            domain: e.g. "coding", "finance", "general"
            tag: any tag string
            min_reputation: filter agents below this score (0-100)
            limit: max results

        Returns:
            List of DiscoveryResult
        """
        params = {"limit": limit}
        if capability:
            params["capability"] = capability
        if domain:
            params["domain"] = domain
        if tag:
            params["tag"] = tag
        if min_reputation is not None:
            params["min_reputation"] = min_reputation

        data = await self._get("/discovery/agents", params=params)
        return [DiscoveryResult(**a) for a in data.get("agents", [])]

    async def crawl(self, base_url: str) -> dict:
        """Auto-discover an agent from its base URL by finding .aaip.json manifest."""
        return await self._post("/discovery/crawl", {"base_url": base_url})

    # ── Evaluation & AI Jury ─────────────────

    async def evaluate(
        self,
        agent_id: str,
        task_description: str,
        agent_output: str,
        domain: str = "general",
        trace: PoETrace | None = None,
        judge_ids: list[str] | None = None,
        benchmark_dataset_id: str | None = None,
        async_mode: bool = False,
    ) -> EvaluationResponse:
        """
        Submit agent output for multi-model jury evaluation.
        Optionally include a PoE trace for execution verification.

        Args:
            agent_id: AAIP agent ID
            task_description: what the task was
            agent_output: what the agent returned
            domain: coding | finance | general
            trace: PoETrace object for execution verification
            judge_ids: specific judge model IDs to use
            benchmark_dataset_id: compare against benchmark dataset
            async_mode: if True, returns job_id instead of waiting

        Returns:
            EvaluationResponse with scores, verdict, and PoE result
        """
        body = {
            "agent_id": agent_id,
            "task_domain": domain,
            "task_description": task_description,
            "agent_output": agent_output,
            "async_mode": async_mode,
        }
        if trace:
            body["trace"] = trace.to_dict()
        if judge_ids:
            body["selected_judge_ids"] = judge_ids
        if benchmark_dataset_id:
            body["benchmark_dataset_id"] = benchmark_dataset_id

        endpoint = "/jobs/evaluate" if async_mode else "/evaluate"
        data = await self._post(endpoint, body)
        return EvaluationResponse(**data)

    async def get_evaluation(self, evaluation_id: str) -> dict:
        """Get a specific evaluation result."""
        return await self._get(f"/evaluations/{evaluation_id}")

    async def get_job(self, job_id: str) -> dict:
        """Poll async evaluation job status."""
        return await self._get(f"/jobs/{job_id}")

    async def wait_for_job(self, job_id: str, poll_interval: float = 2.0, timeout: float = 120.0) -> dict:  # noqa: E501
        """Poll until async job completes or times out."""
        start = time.time()
        while True:
            job = await self.get_job(job_id)
            if job.get("status") in ("completed", "failed"):
                return job
            if time.time() - start > timeout:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            await asyncio.sleep(poll_interval)

    # ── Proof of Execution ───────────────────

    async def submit_trace(self, agent_id: str, trace: PoETrace) -> dict:
        """
        Submit a Proof-of-Execution trace for an agent task.
        Trace is hashed and stored as a verifiable execution record.

        Args:
            agent_id: AAIP agent ID
            trace: PoETrace with tool_calls, reasoning_steps, timestamps

        Returns:
            dict with trace_id, poe_hash, verification_status
        """
        body = {
            "agent_id": agent_id,
            "trace": trace.to_dict(),
            "poe_hash": trace.compute_hash(),
        }
        return await self._post("/traces/submit", body)

    async def verify_trace(self, trace_id: str) -> dict:
        """Verify a previously submitted PoE trace."""
        return await self._get(f"/traces/{trace_id}/verify")

    async def get_traces(self, agent_id: str, limit: int = 20) -> list[dict]:
        """Get execution trace history for an agent."""
        return await self._get(f"/agents/{agent_id}/traces", {"limit": limit})

    # ── Reputation ───────────────────────────

    async def get_reputation(self, agent_id: str, days: int = 30) -> ReputationTimeline:
        """Get reputation timeline and summary for an agent."""
        data = await self._get(f"/agents/{agent_id}/reputation", {"days": days})
        return ReputationTimeline(**data)

    async def get_leaderboard(
        self,
        domain: str | None = None,
        limit: int = 20
    ) -> list[LeaderboardEntry]:
        """Get global leaderboard, optionally filtered by domain."""
        params = {"limit": limit}
        if domain:
            params["domain"] = domain
        data = await self._get("/leaderboard", params)
        return [LeaderboardEntry(**e) for e in data.get("leaderboard", [])]

    async def get_badge(self, agent_id: str) -> dict:
        """Get badge data for embedding in README or website."""
        return await self._get(f"/agents/{agent_id}/badge")

    # ── Payments ─────────────────────────────

    async def get_quote(self, agent_id: str, task: str | None = None) -> PaymentQuote:
        """Get payment quote for calling an agent."""
        body = {"agent_id": agent_id}
        if task:
            body["task"] = task
        data = await self._post("/payments/quote", body)
        return PaymentQuote(**data)

    async def verify_payment(self, tx_hash: str, chain: str = "base") -> dict:
        """Verify a stablecoin payment transaction on-chain."""
        return await self._post("/payments/verify", {"tx_hash": tx_hash, "chain": chain})

    async def execute_paid_task(
        self,
        agent_id: str,
        task: str,
        payment_tx_hash: str,
        chain: str = "base",
    ) -> dict:
        """Execute a task after payment verification."""
        return await self._post("/tasks/execute-paid", {
            "agent_id": agent_id,
            "task": task,
            "payment_tx_hash": payment_tx_hash,
            "chain": chain,
        })

    # ── Judges & Benchmarks ──────────────────

    async def list_judges(self, domain: str | None = None) -> dict:
        """List available judge models for a domain."""
        if domain:
            return await self._get(f"/benchmarks/{domain}/judges")
        return await self._get("/judges/custom")

    async def create_judge(self, name: str, model_id: str, domain: str, system_prompt: str | None = None) -> dict:  # noqa: E501
        """Create a custom judge model."""
        body = {"name": name, "model_id": model_id, "domain": domain}
        if system_prompt:
            body["system_prompt"] = system_prompt
        return await self._post("/judges/custom", body)

    async def list_datasets(self, domain: str | None = None) -> dict:
        """List benchmark datasets."""
        params = {}
        if domain:
            params["domain"] = domain
        return await self._get("/benchmarks/datasets", params)

    # ── Network Stats ────────────────────────

    async def network_stats(self) -> dict:
        """Get global network statistics."""
        return await self._get("/stats/network")

    async def health(self) -> dict:
        """Check API health."""
        return await self._get("/health")


# ─────────────────────────────────────────────
# Sync Client (wraps async)
# ─────────────────────────────────────────────

class AAIPClient(_BaseClient):
    """
    Synchronous AAIP client.

    Usage:
        client = AAIPClient(api_key="...")
        agent = client.register(manifest)
        result = client.evaluate(agent_id, task, output)
    """

    def __init__(self, api_key=None, base_url=None, timeout=30.0):
        super().__init__(api_key, base_url, timeout)
        self._async = AsyncAAIPClient(api_key, base_url, timeout)
        self._loop: asyncio.AbstractEventLoop | None = None

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # Mirror all async methods synchronously
    def register(self, manifest): return self._run(self._async.register(manifest))
    def update_manifest(self, agent_id, manifest): return self._run(self._async.update_manifest(agent_id, manifest))  # noqa: E501
    def get_agent(self, agent_id): return self._run(self._async.get_agent(agent_id))
    def discover(self, capability=None, domain=None, tag=None, min_reputation=None, limit=20):
        return self._run(self._async.discover(capability, domain, tag, min_reputation, limit))
    def crawl(self, base_url): return self._run(self._async.crawl(base_url))
    def evaluate(self, agent_id, task_description, agent_output, domain="general", trace=None, judge_ids=None, benchmark_dataset_id=None, async_mode=False):  # noqa: E501
        return self._run(self._async.evaluate(agent_id, task_description, agent_output, domain, trace, judge_ids, benchmark_dataset_id, async_mode))  # noqa: E501
    def get_evaluation(self, evaluation_id): return self._run(self._async.get_evaluation(evaluation_id))  # noqa: E501
    def get_job(self, job_id): return self._run(self._async.get_job(job_id))
    def wait_for_job(self, job_id, poll_interval=2.0, timeout=120.0):
        return self._run(self._async.wait_for_job(job_id, poll_interval, timeout))
    def submit_trace(self, agent_id, trace): return self._run(self._async.submit_trace(agent_id, trace))  # noqa: E501
    def verify_trace(self, trace_id): return self._run(self._async.verify_trace(trace_id))
    def get_traces(self, agent_id, limit=20): return self._run(self._async.get_traces(agent_id, limit))  # noqa: E501
    def get_reputation(self, agent_id, days=30): return self._run(self._async.get_reputation(agent_id, days))  # noqa: E501
    def get_leaderboard(self, domain=None, limit=20): return self._run(self._async.get_leaderboard(domain, limit))  # noqa: E501
    def get_badge(self, agent_id): return self._run(self._async.get_badge(agent_id))
    def get_quote(self, agent_id, task=None): return self._run(self._async.get_quote(agent_id, task))  # noqa: E501
    def verify_payment(self, tx_hash, chain="base"): return self._run(self._async.verify_payment(tx_hash, chain))  # noqa: E501
    def execute_paid_task(self, agent_id, task, payment_tx_hash, chain="base"):
        return self._run(self._async.execute_paid_task(agent_id, task, payment_tx_hash, chain))
    def list_judges(self, domain=None): return self._run(self._async.list_judges(domain))
    def create_judge(self, name, model_id, domain, system_prompt=None):
        return self._run(self._async.create_judge(name, model_id, domain, system_prompt))
    def list_datasets(self, domain=None): return self._run(self._async.list_datasets(domain))
    def network_stats(self): return self._run(self._async.network_stats())
    def health(self): return self._run(self._async.health())
