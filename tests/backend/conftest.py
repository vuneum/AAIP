"""
Backend test configuration.
sys.path is extended via PYTHONPATH=backend in CI (set in ci.yml).
This file sets default environment variables needed for backend imports,
and imports all backend models so they register against Base.metadata
before the test db_session fixture calls create_all.
"""

import os

os.environ.setdefault("AAIP_DEV_MODE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

# Import all modules that define SQLAlchemy models so every table
# is registered on database.Base.metadata before create_all runs.
import auth       # noqa: F401, E402  (APIKey, AuditLog, RateLimitBucket)
import payments   # noqa: F401, E402  (Wallet, LedgerEntry, Payment, PaymentQuoteRecord)
import poe        # noqa: F401, E402  (PoERecord)
import cav        # noqa: F401, E402  (CAVRun)
import shadow     # noqa: F401, E402  (ShadowSession)
import registry   # noqa: F401, E402  (Agent registration models)
