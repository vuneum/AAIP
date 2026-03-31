"""
aaip/engine/billing.py — Usage Metering & Billing Engine

"Stripe for AI Agents" — tracks per-agent usage and generates
automatic payment requests when billing thresholds are hit.

Features:
  - Per-endpoint / per-tool token metering
  - Configurable pricing tiers (per-token, per-call, flat)
  - Auto-billing: fire PaymentRequest when usage_usd >= threshold
  - Period-based aggregation (daily / monthly)
  - UsageRecord persistence to SQLite via PaymentStore

Usage::

    meter = UsageMeter()
    meter.record("agent_beta_01", "reasoner", tokens_in=512, tokens_out=256)
    meter.record("agent_beta_01", "retriever", tokens_in=128, tokens_out=64)

    # Get current spend
    total = meter.total_cost("agent_beta_01")

    # Flush a billing cycle (generates PaymentRequest if owed > 0)
    receipts = meter.flush_billing("agent_beta_01", recipient_address="0x...")
"""

from __future__ import annotations

import dataclasses
import decimal
import logging
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from aaip.aep.config import cfg
from aaip.schemas.models import PaymentRequest, UsageRecord

log = logging.getLogger("aaip.engine.billing")

# ── Pricing catalogue ─────────────────────────────────────────────────────────
# Cost in USD per 1000 tokens.  Override by passing a custom catalogue.

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "reasoner":   {"per_1k_in": 0.003,  "per_1k_out": 0.015,  "per_call": 0.0},
    "summariser": {"per_1k_in": 0.001,  "per_1k_out": 0.002,  "per_call": 0.0},
    "retriever":  {"per_1k_in": 0.0005, "per_1k_out": 0.0005, "per_call": 0.001},
    "formatter":  {"per_1k_in": 0.001,  "per_1k_out": 0.001,  "per_call": 0.0},
    # catch-all for unknown endpoints
    "_default":   {"per_1k_in": 0.002,  "per_1k_out": 0.008,  "per_call": 0.0},
}

# Rough ETH/USD conversion (configurable via AEP_ETH_USD_RATE env var)
import os as _os
_ETH_USD_RATE = decimal.Decimal(_os.environ.get("AEP_ETH_USD_RATE", "3500.0"))
PROTOCOL_FEE_RATE = float(_os.environ.get("AEP_PROTOCOL_FEE_RATE", "0.02"))  # Keep as float for backward compatibility
_PROTOCOL_FEE_RATE_DECIMAL = decimal.Decimal(str(PROTOCOL_FEE_RATE))  # Decimal version for internal calculations

_treasury_raw = _os.environ.get("AEP_TREASURY_ADDRESS", "").strip()
_adapter      = _os.environ.get("AEP_ADAPTER", "mock").strip().lower()

if not _treasury_raw:
    if _adapter == "evm":
        raise EnvironmentError(
            "AEP_TREASURY_ADDRESS is not set. "
            "Set it in your .env file to the wallet that should receive "
            "the 2% protocol fee. "
            "Example: AEP_TREASURY_ADDRESS=0xYourTreasuryWallet"
        )
    PROTOCOL_TREASURY: str | None = None
else:
    PROTOCOL_TREASURY = _treasury_raw

# Auto-bill when accumulated USD spend hits this threshold
_AUTO_BILL_THRESHOLD_USD = decimal.Decimal(_os.environ.get("AEP_BILL_THRESHOLD_USD", "1.0"))

_BILLING_DB_PATH = Path(_os.environ.get("AEP_BILLING_DB", str(Path.home() / ".aaip-billing.db")))

_BILLING_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS usage_records (
    record_id   TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    cost_eth    REAL NOT NULL DEFAULT 0,
    period      TEXT NOT NULL DEFAULT '',
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_agent  ON usage_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_period ON usage_records(period);
"""


# ── Pricing helper ────────────────────────────────────────────────────────────

def calculate_cost(
    endpoint: str,
    tokens_in: int,
    tokens_out: int,
    pricing: dict | None = None,
) -> tuple[float, float]:
    """
    Return (cost_usd, cost_eth) for a single tool call.
    Uses Decimal internally to avoid IEEE 754 rounding errors.
    """
    p = (pricing or DEFAULT_PRICING)
    rates = p.get(endpoint, p.get("_default", {}))
    
    # Convert rates to Decimal for precise calculations
    per_call = decimal.Decimal(str(rates.get("per_call", 0.0)))
    per_1k_in = decimal.Decimal(str(rates.get("per_1k_in", 0.002)))
    per_1k_out = decimal.Decimal(str(rates.get("per_1k_out", 0.008)))
    
    # Calculate cost in USD using Decimal
    cost_usd_decimal = (
        per_call
        + decimal.Decimal(tokens_in) / decimal.Decimal('1000') * per_1k_in
        + decimal.Decimal(tokens_out) / decimal.Decimal('1000') * per_1k_out
    )
    
    # Calculate cost in ETH using Decimal
    cost_eth_decimal = cost_usd_decimal / _ETH_USD_RATE
    
    # Round and convert to float for backward compatibility
    cost_usd = float(cost_usd_decimal.quantize(decimal.Decimal('1e-8'), rounding=decimal.ROUND_HALF_UP))
    cost_eth = float(cost_eth_decimal.quantize(decimal.Decimal('1e-12'), rounding=decimal.ROUND_HALF_UP))
    
    return cost_usd, cost_eth


def current_period() -> str:
    """Return YYYY-MM billing period string."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")


# ── UsageMeter ────────────────────────────────────────────────────────────────

class UsageMeter:
    """
    Tracks per-agent, per-endpoint token usage and accumulated cost.

    Thread-safe via SQLite WAL + in-process lock.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        pricing: dict | None = None,
        auto_bill_threshold_usd: float = float(_AUTO_BILL_THRESHOLD_USD),
    ) -> None:
        self._db_path   = Path(db_path or _BILLING_DB_PATH)
        self._pricing   = pricing or DEFAULT_PRICING
        self._threshold = auto_bill_threshold_usd
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_BILLING_SCHEMA)

    def record(
        self,
        agent_id: str,
        endpoint: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        period: str | None = None,
    ) -> UsageRecord:
        """
        Record a metered usage event for an agent.

        Args:
            agent_id:   The agent being billed.
            endpoint:   Tool or API endpoint name.
            tokens_in:  Input tokens consumed.
            tokens_out: Output tokens generated.
            period:     Billing period override (default: current month).

        Returns:
            UsageRecord — the persisted record with cost fields filled.
        """
        cost_usd, cost_eth = calculate_cost(endpoint, tokens_in, tokens_out, self._pricing)
        rec = UsageRecord(
            agent_id=agent_id,
            endpoint=endpoint,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            cost_eth=cost_eth,
            period=period or current_period(),
        )
        with self._conn:
            self._conn.execute(
                "INSERT INTO usage_records (record_id,agent_id,endpoint,"
                "tokens_in,tokens_out,cost_usd,cost_eth,period,recorded_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rec.record_id, rec.agent_id, rec.endpoint,
                 rec.tokens_in, rec.tokens_out, rec.cost_usd, rec.cost_eth,
                 rec.period, rec.recorded_at),
            )
        log.debug("Metered %s/%s: $%.6f (%.8f ETH)", agent_id, endpoint, cost_usd, cost_eth)
        return rec

    def total_cost(
        self,
        agent_id: str,
        period: str | None = None,
    ) -> dict[str, float]:
        """
        Return aggregated cost for an agent in the given period.

        Returns:
            {"tokens_in": int, "tokens_out": int, "cost_usd": float, "cost_eth": float}
        """
        period = period or current_period()
        row = self._conn.execute("""
            SELECT
                SUM(tokens_in)  AS tokens_in,
                SUM(tokens_out) AS tokens_out,
                SUM(cost_usd)   AS cost_usd,
                SUM(cost_eth)   AS cost_eth
            FROM usage_records
            WHERE agent_id=? AND period=?
        """, (agent_id, period)).fetchone()
        return {
            "tokens_in":  row["tokens_in"]  or 0,
            "tokens_out": row["tokens_out"] or 0,
            "cost_usd":   round(row["cost_usd"] or 0, 8),
            "cost_eth":   round(row["cost_eth"] or 0, 12),
            "period":     period,
        }

    def breakdown(self, agent_id: str, period: str | None = None) -> list[dict]:
        """Per-endpoint cost breakdown for an agent."""
        period = period or current_period()
        rows = self._conn.execute("""
            SELECT endpoint,
                   SUM(tokens_in)  AS tokens_in,
                   SUM(tokens_out) AS tokens_out,
                   SUM(cost_usd)   AS cost_usd,
                   COUNT(*)        AS calls
            FROM usage_records
            WHERE agent_id=? AND period=?
            GROUP BY endpoint
            ORDER BY cost_usd DESC
        """, (agent_id, period)).fetchall()
        return [dict(r) for r in rows]

    def generate_invoice(
        self,
        agent_id: str,
        recipient_address: str,
        period: str | None = None,
    ) -> PaymentRequest | None:
        """
        Generate a PaymentRequest for all unpaid usage in the period.

        Returns None if there is nothing to bill (cost_eth == 0).
        """
        totals = self.total_cost(agent_id, period)
        if totals["cost_eth"] <= 0:
            log.info("No billable usage for %s in %s", agent_id, totals["period"])
            return None

        req = PaymentRequest(
            agent_id=agent_id,
            recipient_address=recipient_address,
            amount=totals["cost_eth"],
            currency="ETH",
            metadata={
                "type":       "usage_invoice",
                "period":     totals["period"],
                "cost_usd":   totals["cost_usd"],
                "tokens_in":  totals["tokens_in"],
                "tokens_out": totals["tokens_out"],
            },
            idempotency_key=f"invoice:{agent_id}:{totals['period']}",
        )
        log.info("Invoice generated: agent=%s period=%s cost_usd=$%.4f cost_eth=%.8f ETH",
                 agent_id, totals["period"], totals["cost_usd"], totals["cost_eth"])
        return req

    def flush_billing(
        self,
        agent_id: str,
        recipient_address: str,
        period: str | None = None,
        adapter=None,
    ) -> dict[str, Any]:
        """
        Check if agent owes >= threshold and auto-pay if so.

        Returns result dict with invoice and payment outcome.
        """
        from aaip.engine.payment_manager import process_payment

        totals  = self.total_cost(agent_id, period)
        invoice = self.generate_invoice(agent_id, recipient_address, period)

        if invoice is None:
            return {"billed": False, "reason": "nothing_owed", "totals": totals}

        if totals["cost_usd"] < self._threshold:
            return {
                "billed": False,
                "reason": f"below_threshold (${totals['cost_usd']:.4f} < ${self._threshold})",
                "totals": totals,
                "invoice": invoice.to_dict() if hasattr(invoice, 'to_dict') else {},
            }

        receipt = process_payment(invoice, adapter=adapter)
        return {
            "billed":  True,
            "receipt": receipt.to_dict() if hasattr(receipt, 'to_dict') else {},
            "totals":  totals,
        }

    def all_agents_summary(self, period: str | None = None) -> list[dict]:
        """Return per-agent cost summary across all agents for a period."""
        period = period or current_period()
        rows = self._conn.execute("""
            SELECT agent_id,
                   SUM(tokens_in + tokens_out) AS total_tokens,
                   SUM(cost_usd)               AS cost_usd,
                   SUM(cost_eth)               AS cost_eth,
                   COUNT(*)                    AS calls
            FROM usage_records
            WHERE period=?
            GROUP BY agent_id
            ORDER BY cost_usd DESC
        """, (period,)).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
