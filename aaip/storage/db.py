"""
aaip/storage/db.py — Persistence Layer

SQLite-backed storage for:
  - PaymentRequest history
  - ExecutionReceipt audit trail
  - AgentWallet state
  - Nonce registry (replay protection)

Uses only stdlib sqlite3 — zero extra dependencies.
Atomic writes via transactions. Thread-safe via WAL mode.

Usage::

    from aaip.storage.db import PaymentStore
    store = PaymentStore()                       # default path from cfg
    store.save_request(payment_request)
    store.save_receipt(execution_receipt)
    receipts = store.get_receipts(agent_id="agent_beta_01")
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any

from aaip.aep.config import cfg
from aaip.schemas.models import (
    AdapterType,
    AgentWallet,
    ExecutionReceipt,
    PaymentRequest,
    PaymentStatus,
    ValidationOutcome,
    ValidationResult,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS payment_requests (
    request_id        TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    recipient_address TEXT NOT NULL,
    amount            REAL NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'ETH',
    poe_hash          TEXT,
    idempotency_key   TEXT UNIQUE,
    status            TEXT NOT NULL DEFAULT 'pending',
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    requested_at      REAL NOT NULL,
    created_at        REAL NOT NULL DEFAULT (unixepoch('now','subsec'))
);

CREATE TABLE IF NOT EXISTS execution_receipts (
    receipt_id    TEXT PRIMARY KEY,
    request_id    TEXT NOT NULL REFERENCES payment_requests(request_id),
    agent_id      TEXT NOT NULL,
    recipient     TEXT NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'ETH',
    status        TEXT NOT NULL,
    tx_hash       TEXT,
    explorer_url  TEXT,
    poe_hash      TEXT,
    block_number  INTEGER,
    gas_used      INTEGER,
    adapter       TEXT NOT NULL DEFAULT 'mock',
    error         TEXT,
    settled_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_wallets (
    wallet_id      TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL UNIQUE,
    address        TEXT NOT NULL,
    chain_id       INTEGER NOT NULL DEFAULT 11155111,
    currency       TEXT NOT NULL DEFAULT 'ETH',
    balance        REAL NOT NULL DEFAULT 0,
    total_paid     REAL NOT NULL DEFAULT 0,
    total_received REAL NOT NULL DEFAULT 0,
    tx_count       INTEGER NOT NULL DEFAULT 0,
    cav_score      REAL NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    last_active_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nonce_registry (
    nonce_key   TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    poe_hash    TEXT,
    used_at     REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_agent    ON execution_receipts(agent_id);
CREATE INDEX IF NOT EXISTS idx_receipts_poe      ON execution_receipts(poe_hash);
CREATE INDEX IF NOT EXISTS idx_requests_agent    ON payment_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_nonce_expires     ON nonce_registry(expires_at);
"""


class PaymentStore:
    """
    Thread-safe SQLite store for the full AEP payment lifecycle.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path or cfg.db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    # ── Payment Requests ──────────────────────────────────────────────

    def save_request(self, req: PaymentRequest) -> None:
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT OR IGNORE INTO payment_requests
                    (request_id, agent_id, recipient_address, amount, currency,
                     poe_hash, idempotency_key, status, metadata_json, requested_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                req.request_id, req.agent_id, req.recipient_address,
                req.amount, req.currency, req.poe_hash,
                req.idempotency_key or req.fingerprint,
                "pending",
                json.dumps(req.metadata),
                req.requested_at,
            ))

    def get_request(self, request_id: str) -> PaymentRequest | None:
        row = self._conn.execute(
            "SELECT * FROM payment_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        return _row_to_request(row) if row else None

    def is_duplicate(self, idempotency_key: str) -> bool:
        return bool(self._conn.execute(
            "SELECT 1 FROM payment_requests WHERE idempotency_key=?",
            (idempotency_key,)
        ).fetchone())

    # ── Execution Receipts ────────────────────────────────────────────

    def save_receipt(self, receipt: ExecutionReceipt) -> None:
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT OR REPLACE INTO execution_receipts
                    (receipt_id, request_id, agent_id, recipient, amount, currency,
                     status, tx_hash, explorer_url, poe_hash, block_number,
                     gas_used, adapter, error, settled_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                receipt.receipt_id, receipt.request_id, receipt.agent_id,
                receipt.recipient, receipt.amount, receipt.currency,
                receipt.status.value, receipt.tx_hash, receipt.explorer_url,
                receipt.poe_hash, receipt.block_number, receipt.gas_used,
                receipt.adapter.value, receipt.error, receipt.settled_at,
            ))
            # Update request status
            self._conn.execute(
                "UPDATE payment_requests SET status=? WHERE request_id=?",
                (receipt.status.value, receipt.request_id)
            )

    def get_receipts(
        self,
        agent_id: str | None = None,
        poe_hash: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionReceipt]:
        clauses, params = [], []
        if agent_id: clauses.append("agent_id=?");  params.append(agent_id)
        if poe_hash: clauses.append("poe_hash=?");  params.append(poe_hash)
        if status:   clauses.append("status=?");    params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM execution_receipts {where} ORDER BY settled_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return [_row_to_receipt(r) for r in rows]

    def get_receipt(self, receipt_id: str) -> ExecutionReceipt | None:
        row = self._conn.execute(
            "SELECT * FROM execution_receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
        return _row_to_receipt(row) if row else None

    # ── Agent Wallets ─────────────────────────────────────────────────

    def upsert_wallet(self, wallet: AgentWallet) -> None:
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT INTO agent_wallets
                    (wallet_id, agent_id, address, chain_id, currency,
                     balance, total_paid, total_received, tx_count,
                     cav_score, created_at, last_active_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    balance=excluded.balance,
                    total_paid=excluded.total_paid,
                    total_received=excluded.total_received,
                    tx_count=excluded.tx_count,
                    cav_score=excluded.cav_score,
                    last_active_at=excluded.last_active_at
            """, (
                wallet.wallet_id, wallet.agent_id, wallet.address,
                wallet.chain_id, wallet.currency, wallet.balance,
                wallet.total_paid, wallet.total_received,
                wallet.tx_count, wallet.cav_score,
                wallet.created_at, wallet.last_active_at,
            ))

    def get_wallet(self, agent_id: str) -> AgentWallet | None:
        row = self._conn.execute(
            "SELECT * FROM agent_wallets WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return _row_to_wallet(row) if row else None

    def all_wallets(self) -> list[AgentWallet]:
        rows = self._conn.execute(
            "SELECT * FROM agent_wallets ORDER BY cav_score DESC"
        ).fetchall()
        return [_row_to_wallet(r) for r in rows]

    # ── Nonce Registry (replay protection) ───────────────────────────

    def register_nonce(self, nonce_key: str, agent_id: str, poe_hash: str | None = None) -> bool:
        """
        Register a nonce. Returns False if already used (replay detected).
        Nonces expire after cfg.nonce_window_s seconds.
        """
        expires = time.time() + cfg.nonce_window_s
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO nonce_registry (nonce_key, agent_id, poe_hash, used_at, expires_at)"
                        " VALUES (?,?,?,?,?)",
                        (nonce_key, agent_id, poe_hash, time.time(), expires)
                    )
                return True
            except sqlite3.IntegrityError:
                return False  # duplicate — replay detected

    def purge_expired_nonces(self) -> int:
        with self._lock, self._conn:
            c = self._conn.execute(
                "DELETE FROM nonce_registry WHERE expires_at < ?", (time.time(),)
            )
            return c.rowcount

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute("""
            SELECT
                COUNT(*)                                         AS total_receipts,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status='success' THEN amount ELSE 0 END) AS total_volume,
                COUNT(DISTINCT agent_id)                         AS unique_agents
            FROM execution_receipts
        """).fetchone()
        return dict(row)


    def get_receipt_by_idempotency_key(self, idem_key: str) -> "ExecutionReceipt | None":
        """Look up a receipt directly via the payment_request idempotency_key."""
        row = self._conn.execute("""
            SELECT r.* FROM execution_receipts r
            JOIN payment_requests p ON p.request_id = r.request_id
            WHERE p.idempotency_key = ? AND r.status = 'success'
            ORDER BY r.settled_at DESC LIMIT 1
        """, (idem_key,)).fetchone()
        return _row_to_receipt(row) if row else None

    def close(self) -> None:
        self._conn.close()


# ── Row mappers ───────────────────────────────────────────────────────────────

def _row_to_request(row: sqlite3.Row) -> PaymentRequest:
    return PaymentRequest(
        request_id=row["request_id"],
        agent_id=row["agent_id"],
        recipient_address=row["recipient_address"],
        amount=row["amount"],
        currency=row["currency"],
        poe_hash=row["poe_hash"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        requested_at=row["requested_at"],
    )


def _row_to_receipt(row: sqlite3.Row) -> ExecutionReceipt:
    return ExecutionReceipt(
        receipt_id=row["receipt_id"],
        request_id=row["request_id"],
        agent_id=row["agent_id"],
        recipient=row["recipient"],
        amount=row["amount"],
        currency=row["currency"],
        status=PaymentStatus(row["status"]),
        tx_hash=row["tx_hash"],
        explorer_url=row["explorer_url"],
        poe_hash=row["poe_hash"],
        block_number=row["block_number"],
        gas_used=row["gas_used"],
        adapter=AdapterType(row["adapter"]),
        error=row["error"],
        settled_at=row["settled_at"],
    )


def _row_to_wallet(row: sqlite3.Row) -> AgentWallet:
    return AgentWallet(
        wallet_id=row["wallet_id"],
        agent_id=row["agent_id"],
        address=row["address"],
        chain_id=row["chain_id"],
        currency=row["currency"],
        balance=row["balance"],
        total_paid=row["total_paid"],
        total_received=row["total_received"],
        tx_count=row["tx_count"],
        cav_score=row["cav_score"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )

