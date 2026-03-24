"""
routers/payments.py
Payment quote, verification, wallet, and chain endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_api_key, APIKey
from database import get_db
from registry import get_agent_by_arpp_id
from payments import (
    create_quote, verify_payment, execute_paid_task, connect_wallet, get_agent_balance,
    QuoteRequest, QuoteResponse, VerifyPaymentRequest, ExecutePaidTaskRequest,
    WalletConnectRequest, CHAIN_CONFIGS,
)

router = APIRouter(tags=["Payments"])


@router.post("/payments/quote", response_model=QuoteResponse)
async def get_payment_quote(
    request: QuoteRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> QuoteResponse:
    """Get a payment quote for calling an agent. Quote expires in 15 minutes."""
    agent = await get_agent_by_arpp_id(db, request.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await create_quote(db, request)


@router.post("/payments/verify")
async def verify_payment_endpoint(
    request: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    """Verify a stablecoin payment transaction on-chain."""
    return await verify_payment(db, request)


@router.post("/tasks/execute-paid")
async def execute_paid_task_endpoint(
    request: ExecutePaidTaskRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    """Execute a task after payment has been verified."""
    return await execute_paid_task(db, request)


@router.post("/wallets/connect")
async def connect_wallet_endpoint(
    request: WalletConnectRequest,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[APIKey] = Depends(get_api_key),
) -> dict:
    """Connect an external wallet (USDC/USDT) to your agent."""
    return await connect_wallet(db, request)


@router.get("/agents/{aaip_agent_id}/balance")
async def get_balance(
    aaip_agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get internal ledger balance for an agent."""
    return await get_agent_balance(db, aaip_agent_id)


@router.get("/payments/chains")
async def list_supported_chains() -> dict:
    """List all supported blockchain networks."""
    return {
        "chains": [
            {
                "id":       k,
                "name":     v["name"],
                "explorer": v["explorer"],
                "usdc":     bool(v["usdc_contract"]),
                "usdt":     bool(v["usdt_contract"]),
            }
            for k, v in CHAIN_CONFIGS.items()
        ]
    }
