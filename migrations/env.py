"""
Alembic environment configuration for AAIP database migrations.
"""

from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# Import all models so Alembic can detect them
from database import Base
import auth     # APIKey, AuditLog, RateLimitBucket
import poe      # PoERecord
import payments # Wallet, LedgerEntry, Payment, PaymentQuoteRecord

# Alembic Config
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from env
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://arpp:arpp_secret@localhost:5432/arpp")
# Sync URL for migrations (alembic doesn't support asyncpg directly)
SYNC_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("asyncpg+postgresql://", "postgresql://")


def run_migrations_offline() -> None:
    context.configure(
        url=SYNC_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": SYNC_URL},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
