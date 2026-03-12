"""
AAIP — Autonomous Agent Infrastructure Protocol
FastAPI Application v1.0

Routes are organised into focused routers:
    routers/agents.py      — registration, manifest, badge
    routers/poe.py         — trace submission and verification
    routers/cav.py         — CAV audit cycles + shadow mode
    routers/payments.py    — quotes, wallet, escrow
    routers/validators.py  — evaluation, leaderboard, discovery, benchmarks
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import init_db, get_db, create_tables
from auth import check_rate_limit, create_api_key, revoke_api_key, list_api_keys, CreateAPIKeyRequest, CreateAPIKeyResponse, get_db as auth_get_db
from benchmark_datasets import seed_default_datasets
from custom_judges import seed_default_custom_judges
from oracle import get_benchmark_rankings

from routers.agents     import router as agents_router
from routers.poe        import router as poe_router
from routers.cav        import router as cav_router, shadow_router
from routers.payments   import router as payments_router
from routers.validators import router as validators_router


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await create_tables()

    async for db in get_db():
        await seed_default_datasets(db)
        await seed_default_custom_judges(db)
        break

    for domain in ["coding", "finance", "general"]:
        try:
            await get_benchmark_rankings(domain)
        except Exception:
            pass

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AAIP API",
    description="Autonomous Agent Infrastructure Protocol — Identity · Discovery · Reputation · Payments",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware ────────────────────────────────────────────────────────────────

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    try:
        await check_rate_limit(None, request)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    return await call_next(request)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check() -> dict:
    return {
        "status":    "healthy",
        "service":   "AAIP",
        "version":   "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": [
            "agent-identity", "discovery-protocol", "multi-model-jury",
            "proof-of-execution", "reputation-timeline", "async-jobs",
            "payments-v1", "api-key-auth", "shadow-mode",
            "python-sdk", "typescript-sdk", "go-sdk", "rust-sdk",
            "langchain-adapter", "crewai-adapter", "openai-agents-adapter",
        ],
    }


# ── API Key Management ────────────────────────────────────────────────────────

@app.post("/keys", response_model=CreateAPIKeyResponse, tags=["Auth"])
async def create_key_endpoint(request: CreateAPIKeyRequest, db=Depends(get_db)) -> CreateAPIKeyResponse:
    """Create a new API key. The full key is only shown once."""
    return await create_api_key(db, request)


@app.get("/keys", tags=["Auth"])
async def list_keys_endpoint(db=Depends(get_db)) -> dict:
    return {"keys": await list_api_keys(db)}


@app.delete("/keys/{key_id}", tags=["Auth"])
async def revoke_key_endpoint(key_id: str, db=Depends(get_db)) -> dict:
    if not await revoke_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "key_id": key_id}


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(agents_router)
app.include_router(poe_router)
app.include_router(cav_router)
app.include_router(shadow_router)
app.include_router(payments_router)
app.include_router(validators_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
