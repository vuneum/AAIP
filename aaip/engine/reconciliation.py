"""
aaip/engine/reconciliation.py — Credits ↔ Chain Settlement Reconciliation  v1.0.0

Closes the loop between off-chain credit accumulation and on-chain settlement.

Flow:
  1. Agents transact in credits (instant, gas-free, via CreditsAdapter)
  2. Reconciler periodically checks credit balances vs settlement threshold
  3. When an agent's unsettled credits >= threshold → batch settle on-chain
  4. On-chain tx receipt is recorded; credit balance is zeroed for that batch
  5. Full audit trail: credits journal + settlement receipts in SQLite

This is the "hybrid accounting" model:
  credits = immediate finality for agents
  chain   = periodic settlement for trust / auditability

Environment variables:
  AEP_SETTLE_THRESHOLD_ETH   Minimum ETH-equivalent credits to trigger settlement (default 0.1)
  AEP_SETTLE_INTERVAL_S      Reconciliation poll interval in seconds (default 3600 = 1h)
  AEP_SETTLE_DB              Path to reconciliation SQLite store
  AEP_SETTLE_RECIPIENT       On-chain address that receives batched settlements

Usage::

    from aaip.engine.reconciliation import get_reconciler

    rec = get_reconciler()

    # Record credit movements (called by CreditsAdapter automatically)
    rec.record_credit_tx("agent_beta_01", 0.05, "payment")

    # Check what's pending settlement
    pending = rec.pending_settlements()

    # Run one reconciliation pass (normally called on a schedule)
    results = await rec.settle_all()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from aaip.aep.config import cfg
from aaip.aep.adapters.credits import CreditsAdapter
from aaip.schemas.models import PaymentRequest, PaymentStatus

log = logging.getLogger("aaip.engine.reconciliation")

_SETTLE_THRESHOLD = float(os.environ.get("AEP_SETTLE_THRESHOLD_ETH", "0.1"))
_SETTLE_INTERVAL  = float(os.environ.get("AEP_SETTLE_INTERVAL_S",    "3600"))
_SETTLE_DB        = Path(os.environ.get("AEP_SETTLE_DB",
                          str(Path.home() / ".aaip-reconciliation.db")))
_SETTLE_RECIPIENT = os.environ.get("AEP_SETTLE_RECIPIENT", "")

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS credit_journal (
    journal_id    TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    amount_eth    REAL NOT NULL,
    direction     TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    settled       INTEGER NOT NULL DEFAULT 0,
    batch_id      TEXT,
    recorded_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settlement_batches (
    batch_id      TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    total_eth     REAL NOT NULL,
    tx_count      INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    tx_hash       TEXT,
    explorer_url  TEXT,
    error         TEXT,
    created_at    REAL NOT NULL,
    settled_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_journal_agent   ON credit_journal(agent_id, settled);
CREATE INDEX IF NOT EXISTS idx_batch_agent     ON settlement_batches(agent_id);
CREATE INDEX IF NOT EXISTS idx_batch_status    ON settlement_batches(status);
"""


# ── SettlementResult ──────────────────────────────────────────────────────────

class SettlementResult:
    __slots__ = ("agent_id", "batch_id", "total_eth", "tx_count",
                 "status", "tx_hash", "explorer_url", "error")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ── Reconciler ────────────────────────────────────────────────────────────────

class Reconciler:
    """
    Manages the credits ↔ on-chain settlement lifecycle.

    Thread-safe. Designed to run as a background asyncio task.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        threshold_eth: float = _SETTLE_THRESHOLD,
        recipient_address: str = _SETTLE_RECIPIENT,
        credits_adapter: CreditsAdapter | None = None,
    ) -> None:
        self._path      = Path(db_path or _SETTLE_DB)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._threshold = threshold_eth
        self._recipient = recipient_address
        self._credits   = credits_adapter or CreditsAdapter(initial_balance=0.0)
        self._lock      = threading.Lock()
        self._conn      = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    # ── Credit journal ─────────────────────────────────────────────────────

    def record_credit_tx(
        self,
        agent_id: str,
        amount_eth: float,
        reason: str = "payment",
        direction: str = "credit",   # "credit" or "debit"
    ) -> str:
        """Record a credit movement that will eventually be settled on-chain."""
        jid = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT INTO credit_journal
                    (journal_id, agent_id, amount_eth, direction, reason, recorded_at)
                VALUES (?,?,?,?,?,?)
            """, (jid, agent_id, amount_eth, direction, reason, time.time()))
        log.debug("Credit recorded: %s %s %.6f ETH (%s)", agent_id, direction, amount_eth, reason)
        return jid

    def unsettled_balance(self, agent_id: str) -> float:
        """Return the total unsettled credit balance for an agent (ETH)."""
        row = self._conn.execute("""
            SELECT SUM(CASE WHEN direction='credit' THEN amount_eth
                            ELSE -amount_eth END) AS balance
            FROM credit_journal
            WHERE agent_id=? AND settled=0
        """, (agent_id,)).fetchone()
        return round(float(row["balance"] or 0), 12)

    def pending_settlements(self) -> list[dict[str, Any]]:
        """Return agents with unsettled balances >= threshold."""
        rows = self._conn.execute("""
            SELECT agent_id,
                   SUM(CASE WHEN direction='credit' THEN amount_eth ELSE -amount_eth END) AS balance,
                   COUNT(*) AS tx_count
            FROM credit_journal
            WHERE settled=0
            GROUP BY agent_id
            HAVING balance >= ?
            ORDER BY balance DESC
        """, (self._threshold,)).fetchall()
        return [{"agent_id": r["agent_id"], "balance": r["balance"],
                 "tx_count": r["tx_count"]} for r in rows]

    # ── Settlement ─────────────────────────────────────────────────────────

    async def settle_agent(
        self,
        agent_id: str,
        recipient_address: str | None = None,
        adapter=None,
    ) -> SettlementResult:
        """
        Settle all outstanding credits for one agent on-chain.

        Steps:
          1. Sum unsettled credit_journal entries
          2. Execute on-chain payment (real adapter or mock)
          3. Mark journal entries as settled
          4. Record settlement batch
        """
        from aaip.engine.payment_manager import process_payment

        recipient = recipient_address or self._recipient
        if not recipient:
            return SettlementResult(
                agent_id=agent_id, batch_id="", total_eth=0, tx_count=0,
                status="skipped", tx_hash=None, explorer_url=None,
                error="No recipient address configured (AEP_SETTLE_RECIPIENT)"
            )

        balance = self.unsettled_balance(agent_id)
        if balance < self._threshold:
            return SettlementResult(
                agent_id=agent_id, batch_id="", total_eth=balance, tx_count=0,
                status="below_threshold", tx_hash=None, explorer_url=None, error=None
            )

        # Get journal entry IDs to mark settled
        journal_ids = [r["journal_id"] for r in self._conn.execute(
            "SELECT journal_id FROM credit_journal WHERE agent_id=? AND settled=0",
            (agent_id,)
        ).fetchall()]

        batch_id = str(uuid.uuid4())

        # Create settlement batch record
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT INTO settlement_batches
                    (batch_id, agent_id, total_eth, tx_count, status, created_at)
                VALUES (?,?,?,?,?,?)
            """, (batch_id, agent_id, balance, len(journal_ids), "pending", time.time()))

        # Execute on-chain payment
        try:
            req = PaymentRequest(
                agent_id=agent_id,
                recipient_address=recipient,
                amount=balance,
                currency=cfg.payment_symbol,
                metadata={
                    "type":       "credit_settlement",
                    "batch_id":   batch_id,
                    "tx_count":   len(journal_ids),
                    "period":     time.strftime("%Y-%m"),
                },
                idempotency_key=f"settle:{agent_id}:{batch_id}",
            )
            receipt = await asyncio.get_event_loop().run_in_executor(
                None, lambda: process_payment(req, adapter=adapter)
            )
        except Exception as exc:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE settlement_batches SET status='failed', error=? WHERE batch_id=?",
                    (str(exc), batch_id)
                )
            log.error("Settlement failed for %s: %s", agent_id, exc)
            return SettlementResult(
                agent_id=agent_id, batch_id=batch_id, total_eth=balance,
                tx_count=len(journal_ids), status="failed", tx_hash=None,
                explorer_url=None, error=str(exc)
            )

        if receipt.status == PaymentStatus.SUCCESS:
            # Mark journal entries settled
            with self._lock, self._conn:
                placeholders = ",".join("?" * len(journal_ids))
                self._conn.execute(
                    f"UPDATE credit_journal SET settled=1, batch_id=? WHERE journal_id IN ({placeholders})",
                    [batch_id] + journal_ids
                )
                self._conn.execute("""
                    UPDATE settlement_batches
                    SET status='settled', tx_hash=?, explorer_url=?, settled_at=?
                    WHERE batch_id=?
                """, (receipt.tx_hash, receipt.explorer_url, time.time(), batch_id))

            log.info("Settled %.6f ETH for %s → tx=%s", balance, agent_id,
                     (receipt.tx_hash or "")[:18])

            return SettlementResult(
                agent_id=agent_id, batch_id=batch_id, total_eth=balance,
                tx_count=len(journal_ids), status="settled",
                tx_hash=receipt.tx_hash, explorer_url=receipt.explorer_url, error=None
            )
        else:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE settlement_batches SET status='failed', error=? WHERE batch_id=?",
                    (receipt.error, batch_id)
                )
            return SettlementResult(
                agent_id=agent_id, batch_id=batch_id, total_eth=balance,
                tx_count=len(journal_ids), status="failed", tx_hash=None,
                explorer_url=None, error=receipt.error
            )

    async def settle_all(self, adapter=None) -> list[SettlementResult]:
        """Run one full reconciliation pass — settle all agents above threshold."""
        pending = self.pending_settlements()
        if not pending:
            log.info("Reconciliation pass: nothing to settle")
            return []

        log.info("Reconciliation pass: %d agents to settle", len(pending))
        results = []
        for entry in pending:
            result = await self.settle_agent(entry["agent_id"], adapter=adapter)
            results.append(result)
            log.info("  %s: %.6f ETH → %s", entry["agent_id"],
                     entry["balance"], result.status)
        return results

    async def run_forever(self, interval_s: float = _SETTLE_INTERVAL, adapter=None) -> None:
        """Run reconciliation on a schedule. Call as asyncio task."""
        log.info("Reconciliation loop started (interval=%.0fs)", interval_s)
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.settle_all(adapter=adapter)
            except Exception as exc:
                log.error("Reconciliation error: %s", exc)

    # ── Reporting ──────────────────────────────────────────────────────────

    def batches(self, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        if agent_id:
            rows = self._conn.execute(
                "SELECT * FROM settlement_batches WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM settlement_batches ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        row = self._conn.execute("""
            SELECT
                COUNT(DISTINCT agent_id)                          AS agents,
                SUM(CASE WHEN settled=0 THEN amount_eth ELSE 0 END) AS pending_eth,
                SUM(CASE WHEN settled=1 THEN amount_eth ELSE 0 END) AS settled_eth,
                COUNT(CASE WHEN settled=0 THEN 1 END)             AS pending_txs,
                COUNT(CASE WHEN settled=1 THEN 1 END)             AS settled_txs
            FROM credit_journal
        """).fetchone()
        return dict(row) if row else {}

    def close(self) -> None:
        self._conn.close()


# ── Module singleton ──────────────────────────────────────────────────────────

_reconciler: Reconciler | None = None
_rec_lock = threading.Lock()


def get_reconciler(**kwargs) -> Reconciler:
    global _reconciler
    with _rec_lock:
        if _reconciler is None:
            _reconciler = Reconciler(**kwargs)
    return _reconciler
