"""
AAIP — Authentication & API Key Middleware
Handles API key issuance, validation, rate limiting, and audit logging.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func, Column, String, DateTime, Integer, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import JSON as JSONB  # JSONB on PG, JSON fallback for SQLite
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from database import Base, get_db

# ─────────────────────────────────────────────
# DB Models
# ─────────────────────────────────────────────

class APIKey(Base):
    __tablename__ = "api_keys"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_id        = Column(String(20), unique=True, nullable=False, index=True)   # aaip_xxxxxxxxxxxx
    key_hash      = Column(String(64), nullable=False)                             # SHA-256 of full key
    name          = Column(String(200), nullable=False)
    owner_email   = Column(String(200), nullable=True)
    scopes        = Column(JSONB, nullable=False, default=list)                    # ["evaluate","register","admin"]
    rate_limit    = Column(Integer, nullable=False, default=1000)                  # requests/hour
    is_active     = Column(Boolean, nullable=False, default=True)
    last_used_at  = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    expires_at    = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_id      = Column(String(20), nullable=True, index=True)
    method      = Column(String(10), nullable=False)
    path        = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=True)
    ip_address  = Column(String(50), nullable=True)
    user_agent  = Column(String(200), nullable=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, index=True)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_id      = Column(String(20), nullable=False, index=True)
    window_start= Column(DateTime, nullable=False)
    request_count = Column(Integer, nullable=False, default=0)


# ─────────────────────────────────────────────
# Key Generation
# ─────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (full_key, key_id, key_hash)
    Full key format: aaip_<20 random chars>
    """
    random_part = secrets.token_urlsafe(30)[:40]
    key_id = f"aaip_{secrets.token_hex(8)}"
    full_key = f"{key_id}_{random_part}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, key_id, key_hash


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


# ─────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


async def get_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[APIKey]:
    """
    Extract and validate API key from Authorization header.
    Returns None if no key provided (public endpoints).
    Raises 401 if key is invalid/expired.
    """
    # Check for dev bypass in local mode
    if os.getenv("AAIP_DEV_MODE", "").lower() == "true":
        return None  # Allow all in dev

    if not credentials:
        return None

    token = credentials.credentials
    if not token:
        return None

    token_hash = hash_key(token)

    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == token_hash,
            APIKey.is_active,
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if key.expires_at and key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last used
    key.last_used_at = datetime.utcnow()
    await db.commit()

    return key


async def require_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """Require a valid API key — raises 401 if missing or invalid."""
    key = await get_api_key(request, credentials, db)
    if key is None and os.getenv("AAIP_DEV_MODE", "").lower() != "true":
        raise HTTPException(
            status_code=401,
            detail="API key required. Set Authorization: Bearer <your-key>"
        )
    return key


# ─────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────

# In-memory rate limit cache (use Redis in production)
_rate_cache: dict[str, tuple[int, float]] = {}  # key_id -> (count, window_start)


async def check_rate_limit(key: Optional[APIKey], request: Request) -> None:
    """
    Sliding window rate limiter.
    Default: 1000 requests/hour per key.
    IP-based for unauthenticated requests: 100/hour.
    """
    if os.getenv("AAIP_DEV_MODE", "").lower() == "true":
        return

    now = time.time()
    window = 3600  # 1 hour in seconds

    if key:
        bucket_key = key.key_id
        limit = key.rate_limit
    else:
        # IP-based for unauthenticated
        client_ip = request.client.host if request.client else "unknown"
        bucket_key = f"ip:{client_ip}"
        limit = 100

    count, window_start = _rate_cache.get(bucket_key, (0, now))

    # Reset window if expired
    if now - window_start > window:
        count = 0
        window_start = now

    count += 1
    _rate_cache[bucket_key] = (count, window_start)

    if count > limit:
        retry_after = int(window - (now - window_start))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )


# ─────────────────────────────────────────────
# Audit Logging
# ─────────────────────────────────────────────

async def log_request(
    db: AsyncSession,
    request: Request,
    key: Optional[APIKey],
    status_code: int,
) -> None:
    """Write an audit log entry for every API request."""
    try:
        log = AuditLog(
            key_id=key.key_id if key else None,
            method=request.method,
            path=str(request.url.path),
            status_code=status_code,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:200],
        )
        db.add(log)
        await db.commit()
    except Exception:
        pass  # Audit log failure should never break the request


# ─────────────────────────────────────────────
# API Key Management Endpoints (for main.py)
# ─────────────────────────────────────────────


class CreateAPIKeyRequest(BaseModel):
    name: str
    owner_email: Optional[str] = None
    scopes: list[str] = ["evaluate", "register", "discover"]
    rate_limit: int = 1000
    expires_days: Optional[int] = None


class CreateAPIKeyResponse(BaseModel):
    key_id: str
    api_key: str   # Only shown once
    name: str
    scopes: list[str]
    rate_limit: int
    expires_at: Optional[str]
    warning: str = "Store this key securely — it will not be shown again."


async def create_api_key(
    db: AsyncSession,
    request: CreateAPIKeyRequest,
) -> CreateAPIKeyResponse:
    full_key, key_id, key_hash = generate_api_key()

    expires_at = None
    if request.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_days)

    key = APIKey(
        key_id=key_id,
        key_hash=key_hash,
        name=request.name,
        owner_email=request.owner_email,
        scopes=request.scopes,
        rate_limit=request.rate_limit,
        expires_at=expires_at,
    )
    db.add(key)
    await db.commit()

    return CreateAPIKeyResponse(
        key_id=key_id,
        api_key=full_key,
        name=request.name,
        scopes=request.scopes,
        rate_limit=request.rate_limit,
        expires_at=expires_at.isoformat() if expires_at else None,
    )


async def revoke_api_key(db: AsyncSession, key_id: str) -> bool:
    result = await db.execute(select(APIKey).where(APIKey.key_id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        return False
    key.is_active = False
    await db.commit()
    return True


async def list_api_keys(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(APIKey).order_by(APIKey.created_at.desc()))
    return [
        {
            "key_id": k.key_id,
            "name": k.name,
            "scopes": k.scopes,
            "rate_limit": k.rate_limit,
            "is_active": k.is_active,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat(),
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in result.scalars().all()
    ]
