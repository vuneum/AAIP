"""Add CAV and Shadow Mode tables

Revision ID: 0002_cav_shadow
Revises: 0001_initial_aaip
Create Date: 2025-03-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_cav_shadow"
down_revision = "0001_initial_aaip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cav_runs ────────────────────────────
    op.create_table(
        "cav_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aaip_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("task_domain", sa.String(100), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=False),
        sa.Column("agent_output", sa.Text(), nullable=True),
        sa.Column("observed_score", sa.Float(), nullable=True),
        sa.Column("expected_score", sa.Float(), nullable=False),
        sa.Column("deviation", sa.Float(), nullable=True),
        sa.Column("result", sa.String(50), nullable=False),
        sa.Column("reputation_adjusted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("adjustment_delta", sa.Float(), nullable=True),
        sa.Column("triggered_by", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )

    # ── shadow_sessions ─────────────────────
    op.create_table(
        "shadow_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("aaip_agent_id", sa.String(200), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("report_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("shadow_sessions")
    op.drop_table("cav_runs")
