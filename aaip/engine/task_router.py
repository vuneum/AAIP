"""
aaip/engine/task_router.py — Capability-Aware Task Router  v1.0.0

Routes AgentTask objects to the best available agent using:
  - Capability matching   (task.required_capabilities ⊆ agent.capabilities)
  - Cost-aware selection  (prefer cheapest capable agent)
  - Health-aware routing  (skip agents marked unhealthy)
  - Load balancing        (least-active among equally-ranked candidates)
  - Persistent registry   (backed by SQLite via AgentRegistry)

Agent registration:

    router = get_router()
    router.register(
        agent_id="agent_beta_01",
        address="0xABC...",
        capabilities={"summarise", "retrieve", "reason"},
        cost_per_task=0.05,
        max_concurrent=5,
    )

Task routing:

    task  = create_task("Summarise report", required_capabilities={"summarise"})
    agent = router.route(task)   # raises RoutingError if no capable agent

Health reporting:

    router.heartbeat("agent_beta_01")       # mark alive
    router.mark_unhealthy("agent_beta_01")  # exclude from routing
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import tempfile
import threading
import time
import os
from pathlib import Path
from typing import Any

from aaip.schemas.models import AgentTask, PaymentRequest

log = logging.getLogger("aaip.engine.task_router")

_REGISTRY_PATH = Path(os.environ.get(
    "AEP_REGISTRY_DB",
    str(Path.home() / ".aaip-registry.db")
))

_REGISTRY_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    address         TEXT NOT NULL,
    capabilities    TEXT NOT NULL DEFAULT '[]',
    cost_per_task   REAL NOT NULL DEFAULT 0.0,
    max_concurrent  INTEGER NOT NULL DEFAULT 5,
    active_tasks    INTEGER NOT NULL DEFAULT 0,
    healthy         INTEGER NOT NULL DEFAULT 1,
    last_heartbeat  REAL NOT NULL,
    registered_at   REAL NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agents_healthy ON agents(healthy);
"""


# ── Agent record ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class AgentRecord:
    agent_id:       str
    address:        str
    capabilities:   set[str]
    cost_per_task:  float        = 0.0
    max_concurrent: int          = 5
    active_tasks:   int          = 0
    healthy:        bool         = True
    last_heartbeat: float        = dataclasses.field(default_factory=time.time)
    registered_at:  float        = dataclasses.field(default_factory=time.time)
    metadata:       dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def utilization(self) -> float:
        return self.active_tasks / max(self.max_concurrent, 1)

    @property
    def has_capacity(self) -> bool:
        return self.active_tasks < self.max_concurrent and self.healthy

    def can_handle(self, required: set[str]) -> bool:
        """Return True if this agent has all required capabilities."""
        return required.issubset(self.capabilities)

    def routing_score(self, required: set[str]) -> float:
        """
        Lower is better.
        Balances cost, utilization, and capability specialisation.
        Agents with exact-match capability sets are preferred over
        over-qualified generalists (cost of specialisation).
        """
        if not self.can_handle(required):
            return float("inf")
        excess_caps = len(self.capabilities - required)
        return (
            self.cost_per_task * 10      # cost dominates
            + self.utilization * 5       # penalise busy agents
            + excess_caps * 0.5          # slight preference for specialists
        )


class RoutingError(Exception):
    """Raised when no agent can handle a task."""
    pass


# ── Persistent registry ────────────────────────────────────────────────────────

class AgentRegistry:
    """
    SQLite-backed agent registry.

    Thread-safe. Agents persist across process restarts.
    Use get_registry() for the module-level singleton.
    """

    # Heartbeat timeout — agents silent for this long are marked unhealthy
    HEARTBEAT_TIMEOUT_S: float = float(os.environ.get("AEP_HEARTBEAT_TIMEOUT", "60"))

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path or _REGISTRY_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_REGISTRY_SCHEMA)

    # ── Registration ──────────────────────────────────────────────────────

    def register(
        self,
        agent_id: str,
        address: str,
        capabilities: set[str] | list[str],
        cost_per_task: float = 0.0,
        max_concurrent: int = 5,
        metadata: dict | None = None,
    ) -> AgentRecord:
        """Register or update an agent in the pool."""
        caps = set(capabilities)
        rec  = AgentRecord(
            agent_id=agent_id,
            address=address,
            capabilities=caps,
            cost_per_task=cost_per_task,
            max_concurrent=max_concurrent,
            metadata=metadata or {},
        )
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT INTO agents
                    (agent_id, address, capabilities, cost_per_task,
                     max_concurrent, healthy, last_heartbeat, registered_at, metadata_json)
                VALUES (?,?,?,?,?,1,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    address=excluded.address,
                    capabilities=excluded.capabilities,
                    cost_per_task=excluded.cost_per_task,
                    max_concurrent=excluded.max_concurrent,
                    healthy=1,
                    last_heartbeat=excluded.last_heartbeat,
                    metadata_json=excluded.metadata_json
            """, (
                agent_id, address,
                json.dumps(sorted(caps)),
                cost_per_task, max_concurrent,
                time.time(), time.time(),
                json.dumps(metadata or {}),
            ))
        log.info("Agent registered: %s caps=%s cost=%.4f", agent_id, caps, cost_per_task)
        return rec

    def deregister(self, agent_id: str) -> bool:
        with self._lock, self._conn:
            c = self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
            return c.rowcount > 0

    # ── Health management ─────────────────────────────────────────────────

    def heartbeat(self, agent_id: str) -> None:
        """Mark agent alive. Call this periodically from agent process."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE agents SET healthy=1, last_heartbeat=? WHERE agent_id=?",
                (time.time(), agent_id)
            )

    def mark_unhealthy(self, agent_id: str, reason: str = "") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE agents SET healthy=0 WHERE agent_id=?", (agent_id,)
            )
        log.warning("Agent marked unhealthy: %s reason=%s", agent_id, reason)

    def expire_stale_agents(self) -> list[str]:
        """Mark agents whose heartbeat has timed out as unhealthy."""
        cutoff = time.time() - self.HEARTBEAT_TIMEOUT_S
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT agent_id FROM agents WHERE healthy=1 AND last_heartbeat < ?",
                (cutoff,)
            ).fetchall()
            if rows:
                ids = [r["agent_id"] for r in rows]
                self._conn.execute(
                    f"UPDATE agents SET healthy=0 WHERE agent_id IN ({','.join('?'*len(ids))})",
                    ids
                )
                for aid in ids:
                    log.warning("Agent expired (heartbeat timeout): %s", aid)
                return ids
        return []

    # ── Routing ───────────────────────────────────────────────────────────

    def route(self, required_capabilities: set[str] = frozenset()) -> AgentRecord:
        """
        Select the best available agent for a task.

        Selection algorithm (lower score = better):
          1. Filter: healthy=True, active < max_concurrent
          2. Filter: has all required capabilities
          3. Score:  cost * 10 + utilization * 5 + excess_caps * 0.5
          4. Tie-break: least active tasks

        Raises:
            RoutingError — if no agent satisfies the constraints.
        """
        self.expire_stale_agents()
        candidates = self._load_healthy()

        if not candidates:
            raise RoutingError("No healthy agents registered")

        capable = [a for a in candidates if a.can_handle(required_capabilities)]
        if not capable:
            raise RoutingError(
                f"No agent has capabilities {required_capabilities}. "
                f"Available caps: {self._all_capabilities()}"
            )

        best = min(capable, key=lambda a: (a.routing_score(required_capabilities),
                                           a.active_tasks))

        # Increment active task count
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE agents SET active_tasks = active_tasks + 1 WHERE agent_id=?",
                (best.agent_id,)
            )
        log.info("Task routed to %s (score=%.2f, caps=%s)",
                 best.agent_id, best.routing_score(required_capabilities),
                 best.capabilities)
        return best

    def release(self, agent_id: str) -> None:
        """Signal that an agent has finished a task."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE agents SET active_tasks = MAX(0, active_tasks - 1) WHERE agent_id=?",
                (agent_id,)
            )

    # ── Queries ───────────────────────────────────────────────────────────

    def get(self, agent_id: str) -> AgentRecord | None:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return _row_to_agent(row) if row else None

    def all(self) -> list[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents ORDER BY cost_per_task, active_tasks"
        ).fetchall()
        return [_row_to_agent(r) for r in rows]

    def pool_status(self) -> dict[str, Any]:
        rows = self._conn.execute("""
            SELECT
                COUNT(*)                                   AS total,
                SUM(healthy)                               AS healthy,
                COUNT(*) - SUM(healthy)                    AS unhealthy,
                SUM(active_tasks)                          AS active_tasks,
                AVG(CASE WHEN healthy=1 THEN cost_per_task END) AS avg_cost,
                GROUP_CONCAT(DISTINCT capabilities)        AS all_caps
            FROM agents
        """).fetchone()
        return dict(rows) if rows else {}

    # ── Internals ─────────────────────────────────────────────────────────

    def _load_healthy(self) -> list[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE healthy=1 AND active_tasks < max_concurrent"
        ).fetchall()
        return [_row_to_agent(r) for r in rows]

    def _all_capabilities(self) -> set[str]:
        rows = self._conn.execute("SELECT capabilities FROM agents WHERE healthy=1").fetchall()
        caps: set[str] = set()
        for r in rows:
            caps.update(json.loads(r["capabilities"]))
        return caps

    def close(self) -> None:
        self._conn.close()


# ── Row mapper ────────────────────────────────────────────────────────────────

def _row_to_agent(row: sqlite3.Row) -> AgentRecord:
    return AgentRecord(
        agent_id=row["agent_id"],
        address=row["address"],
        capabilities=set(json.loads(row["capabilities"])),
        cost_per_task=row["cost_per_task"],
        max_concurrent=row["max_concurrent"],
        active_tasks=row["active_tasks"],
        healthy=bool(row["healthy"]),
        last_heartbeat=row["last_heartbeat"],
        registered_at=row["registered_at"],
        metadata=json.loads(row["metadata_json"]),
    )


# ── Module singleton ──────────────────────────────────────────────────────────

_registry: AgentRegistry | None = None
_registry_lock = threading.Lock()


def get_registry(db_path: Path | str | None = None) -> AgentRegistry:
    """Return the module-level AgentRegistry singleton."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = AgentRegistry(db_path)
    return _registry


# ── Convenience helpers (backwards-compatible with old task_router API) ────────

def register_agent(
    agent_id: str,
    role: str = "executor",
    capacity: int = 5,
    capabilities: set[str] | None = None,
    address: str = "",
    cost_per_task: float = 0.0,
) -> AgentRecord:
    """Register an agent. Backwards-compatible wrapper."""
    caps = capabilities or {"execute", role}
    return get_registry().register(
        agent_id=agent_id,
        address=address or agent_id,
        capabilities=caps,
        cost_per_task=cost_per_task,
        max_concurrent=capacity,
    )


def route_task(task: AgentTask) -> str:
    """Route task, return agent_id. Raises RoutingError if no agent available."""
    required = getattr(task, "required_capabilities", set())
    rec = get_registry().route(required_capabilities=required)
    return rec.agent_id


def release_agent(agent_id: str) -> None:
    get_registry().release(agent_id)


def pool_status() -> dict[str, Any]:
    return get_registry().pool_status()


def create_task(
    description: str,
    agent_id: str = "",
    requester_id: str = "system",
    cost: float = 0.0,
    required_capabilities: set[str] | None = None,
) -> AgentTask:
    """Create an AgentTask, optionally with capability requirements."""
    task = AgentTask(
        description=description,
        agent_id=agent_id or "unassigned",
        requester_id=requester_id,
        cost=cost,
    )
    # Attach capabilities as a dynamic attribute (not in dataclass schema)
    object.__setattr__(task, "required_capabilities", required_capabilities or set())
    return task


def task_to_payment_request(task: AgentTask, recipient_address: str) -> PaymentRequest:
    """Convert a completed AgentTask into a PaymentRequest."""
    if task.status != "complete":
        raise ValueError(f"Cannot bill incomplete task {task.task_id}")
    if task.cost <= 0:
        raise ValueError(f"Task {task.task_id} has no billable cost")
    return PaymentRequest(
        agent_id=task.requester_id,
        recipient_address=recipient_address,
        amount=task.cost,
        currency=task.currency,
        poe_hash=task.poe_hash,
        metadata={"task_id": task.task_id, "description": task.description[:120]},
    )
