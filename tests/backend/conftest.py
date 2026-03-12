"""
Backend test configuration.
sys.path is extended via PYTHONPATH=backend in CI (set in ci.yml).
This file sets default environment variables needed for backend imports.
"""

import os

os.environ.setdefault("AAIP_DEV_MODE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
