"""Initial AAIP schema — auth, PoE, payments tables

Revision ID: 0001_initial_aaip
Revises: 
Create Date: 2025-01-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_aaip"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── api_keys ────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key_id", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_email", sa.String(200), nullable=True),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("rate_limit", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )

    # ── audit_logs ──────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key_id", sa.String(20), nullable=True, index=True),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )

    # ── rate_limit_buckets ──────────────────
    op.create_table(
        "rate_limit_buckets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key_id", sa.String(20), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── poe_records ─────────────────────────
    op.create_table(
        "poe_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("aaip_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("task_id", sa.String(200), nullable=False, index=True),
        sa.Column("task_description", sa.Text(), nullable=True),
        sa.Column("started_at_ms", sa.Integer(), nullable=False),
        sa.Column("completed_at_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("steps_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tool_calls_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("reasoning_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("token_usage", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("poe_hash", sa.String(64), nullable=False, index=True),
        sa.Column("hash_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fraud_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )

    # ── wallets ─────────────────────────────
    op.create_table(
        "wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aaip_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("chain", sa.String(50), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("wallet_mode", sa.String(50), nullable=False, server_default="external"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ── ledger_entries ───────────────────────
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aaip_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USDC"),
        sa.Column("chain", sa.String(50), nullable=True),
        sa.Column("tx_hash", sa.String(200), nullable=True, index=True),
        sa.Column("reference_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )

    # ── payments ────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("quote_id", sa.String(50), nullable=True),
        sa.Column("payer_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("payee_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USDC"),
        sa.Column("chain", sa.String(50), nullable=False, server_default="base"),
        sa.Column("tx_hash", sa.String(200), nullable=True, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("task_id", sa.String(200), nullable=True),
        sa.Column("task_result", sa.Text(), nullable=True),
        sa.Column("escrow_released", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    # ── payment_quotes ───────────────────────
    op.create_table(
        "payment_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_id", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USDC"),
        sa.Column("chain", sa.String(50), nullable=False, server_default="base"),
        sa.Column("wallet_address", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("payment_quotes")
    op.drop_table("payments")
    op.drop_table("ledger_entries")
    op.drop_table("wallets")
    op.drop_table("poe_records")
    op.drop_table("rate_limit_buckets")
    op.drop_table("audit_logs")
    op.drop_table("api_keys")
