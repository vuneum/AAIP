"""
AAIP — Payment Module v1
Handles agent-to-agent payments via USDC/USDT stablecoins.

Architecture:
  Owner wallet → deposit → AAIP internal ledger → agent spends
  → provider receives credit → batch settlement on-chain
  → escrow/dispute only for high-value or disputed flows
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select, func, Column, String, Text, Integer, DateTime, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from database import Base


# ─────────────────────────────────────────────
# DB Models
# ─────────────────────────────────────────────

class Wallet(Base):
    __tablename__ = "wallets"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aaip_agent_id= Column(String(200), nullable=False, index=True)
    chain        = Column(String(50), nullable=False)   # base | ethereum | tron | solana
    address      = Column(String(200), nullable=False)
    wallet_mode  = Column(String(50), nullable=False, default="external")  # external | managed
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aaip_agent_id  = Column(String(200), nullable=False, index=True)
    entry_type     = Column(String(50), nullable=False)   # deposit | charge | credit | refund | fee
    amount         = Column(Numeric(20, 6), nullable=False)
    currency       = Column(String(10), nullable=False, default="USDC")
    chain          = Column(String(50), nullable=True)
    tx_hash        = Column(String(200), nullable=True, index=True)
    reference_id   = Column(String(200), nullable=True)   # payment_id, task_id, etc.
    status         = Column(String(50), nullable=False, default="pending")  # pending|confirmed|failed
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)


class Payment(Base):
    __tablename__ = "payments"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id      = Column(String(50), unique=True, nullable=False, index=True)
    quote_id        = Column(String(50), nullable=True)
    payer_agent_id  = Column(String(200), nullable=False, index=True)
    payee_agent_id  = Column(String(200), nullable=False, index=True)
    amount          = Column(Numeric(20, 6), nullable=False)
    currency        = Column(String(10), nullable=False, default="USDC")
    chain           = Column(String(50), nullable=False, default="base")
    tx_hash         = Column(String(200), nullable=True, index=True)
    status          = Column(String(50), nullable=False, default="pending")
    # pending | verified | confirmed | failed | refunded | disputed
    task_id         = Column(String(200), nullable=True)
    task_result     = Column(Text, nullable=True)
    escrow_released = Column(Boolean, nullable=False, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at    = Column(DateTime, nullable=True)
    metadata_json   = Column(JSON, nullable=False, default=dict)


class PaymentQuoteRecord(Base):
    __tablename__ = "payment_quotes"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_id        = Column(String(50), unique=True, nullable=False, index=True)
    agent_id        = Column(String(200), nullable=False, index=True)
    amount          = Column(Numeric(20, 6), nullable=False)
    currency        = Column(String(10), nullable=False, default="USDC")
    chain           = Column(String(50), nullable=False, default="base")
    wallet_address  = Column(String(200), nullable=False)
    expires_at      = Column(DateTime, nullable=False)
    used            = Column(Boolean, nullable=False, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────

class QuoteRequest(BaseModel):
    agent_id: str
    task: Optional[str] = None
    currency: str = "USDC"
    chain: str = "base"


class QuoteResponse(BaseModel):
    quote_id:       str
    agent_id:       str
    amount:         str
    currency:       str
    chain:          str
    wallet_address: str
    expires_at:     str
    instructions:   str


class VerifyPaymentRequest(BaseModel):
    tx_hash: str
    chain:   str = "base"
    quote_id: Optional[str] = None


class VerifyPaymentResponse(BaseModel):
    payment_id: str
    tx_hash:    str
    status:     str   # verified | failed | pending
    amount:     Optional[str]
    currency:   Optional[str]
    confirmed:  bool
    message:    str


class ExecutePaidTaskRequest(BaseModel):
    agent_id:         str
    task:             str
    payment_tx_hash:  str
    chain:            str = "base"
    quote_id:         Optional[str] = None


class WalletConnectRequest(BaseModel):
    aaip_agent_id: str
    chain:         str
    address:       str


class WalletInfo(BaseModel):
    wallet_id:     str
    aaip_agent_id: str
    chain:         str
    address:       str
    mode:          str


# ─────────────────────────────────────────────
# Chain Configs (add more chains here)
# ─────────────────────────────────────────────

CHAIN_CONFIGS = {
    "base": {
        "name": "Base",
        "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "usdt_contract": None,
        "explorer": "https://basescan.org/tx/",
        "confirmations_required": 1,
    },
    "ethereum": {
        "name": "Ethereum",
        "usdc_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "usdt_contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "explorer": "https://etherscan.io/tx/",
        "confirmations_required": 3,
    },
    "tron": {
        "name": "Tron",
        "usdc_contract": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",
        "usdt_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "explorer": "https://tronscan.org/#/transaction/",
        "confirmations_required": 1,
    },
    "solana": {
        "name": "Solana",
        "usdc_contract": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "usdt_contract": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "explorer": "https://solscan.io/tx/",
        "confirmations_required": 1,
    },
}

DEFAULT_PRICING = {
    "per_request": "0.0020",
    "currency": "USDC",
}


# ─────────────────────────────────────────────
# Core Functions
# ─────────────────────────────────────────────

async def create_quote(
    db: AsyncSession,
    request: QuoteRequest,
) -> QuoteResponse:
    """
    Create a payment quote for calling an agent.
    Quote expires in 15 minutes.
    """
    from database import Agent, AgentDiscoveryProfile

    # Get agent wallet
    result = await db.execute(
        select(Wallet).where(
            Wallet.aaip_agent_id == request.agent_id,
            Wallet.chain == request.chain,
            Wallet.is_active,
        )
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        # Use protocol default wallet if agent has none
        wallet_address = "0x0000000000000000000000000000000000000000"
    else:
        wallet_address = wallet.address

    quote_id = f"qt_{secrets.token_hex(12)}"
    amount = DEFAULT_PRICING["per_request"]
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    record = PaymentQuoteRecord(
        quote_id=quote_id,
        agent_id=request.agent_id,
        amount=Decimal(amount),
        currency=request.currency,
        chain=request.chain,
        wallet_address=wallet_address,
        expires_at=expires_at,
    )
    db.add(record)
    await db.commit()

    chain_cfg = CHAIN_CONFIGS.get(request.chain, CHAIN_CONFIGS["base"])

    return QuoteResponse(
        quote_id=quote_id,
        agent_id=request.agent_id,
        amount=amount,
        currency=request.currency,
        chain=request.chain,
        wallet_address=wallet_address,
        expires_at=expires_at.isoformat(),
        instructions=f"Send {amount} {request.currency} to {wallet_address} on {chain_cfg['name']}. Quote valid for 15 minutes.",
    )


async def verify_payment(
    db: AsyncSession,
    request: VerifyPaymentRequest,
) -> VerifyPaymentResponse:
    """
    Verify a stablecoin payment transaction on-chain.
    MVP: checks tx_hash format and records payment.
    Production: integrate with chain RPC / indexer.
    """
    payment_id = f"pay_{secrets.token_hex(12)}"

    # MVP: accept any well-formed tx hash and mark as verified
    # Production: query chain RPC to verify tx exists, amount, recipient
    is_valid_hash = (
        len(request.tx_hash) >= 32 and
        all(c in "0123456789abcdefABCDEF" for c in request.tx_hash.lstrip("0x"))
    )

    if not is_valid_hash:
        return VerifyPaymentResponse(
            payment_id=payment_id,
            tx_hash=request.tx_hash,
            status="failed",
            amount=None,
            currency=None,
            confirmed=False,
            message="Invalid transaction hash format",
        )

    # Record the payment
    payment = Payment(
        payment_id=payment_id,
        quote_id=request.quote_id,
        payer_agent_id="unknown",
        payee_agent_id="unknown",
        amount=Decimal("0.0020"),
        currency="USDC",
        chain=request.chain,
        tx_hash=request.tx_hash,
        status="verified",
        confirmed_at=datetime.utcnow(),
    )
    db.add(payment)

    # Add ledger entry
    ledger = LedgerEntry(
        aaip_agent_id="unknown",
        entry_type="deposit",
        amount=Decimal("0.0020"),
        currency="USDC",
        chain=request.chain,
        tx_hash=request.tx_hash,
        reference_id=payment_id,
        status="confirmed",
    )
    db.add(ledger)
    await db.commit()

    return VerifyPaymentResponse(
        payment_id=payment_id,
        tx_hash=request.tx_hash,
        status="verified",
        amount="0.0020",
        currency="USDC",
        confirmed=True,
        message="Payment verified. You may now execute the task.",
    )


async def execute_paid_task(
    db: AsyncSession,
    request: ExecutePaidTaskRequest,
) -> dict:
    """
    Execute a task after payment verification.
    Gate: checks payment status before allowing task execution.
    """
    # Verify payment exists and is confirmed
    result = await db.execute(
        select(Payment).where(
            Payment.tx_hash == request.payment_tx_hash,
            Payment.status == "verified",
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=402,
            detail="Payment not verified. Call POST /payments/verify first."
        )

    # Update payment with task reference
    payment.task_id = f"task_{secrets.token_hex(8)}"
    payment.status = "executing"
    await db.commit()

    return {
        "task_id": payment.task_id,
        "payment_id": payment.payment_id,
        "agent_id": request.agent_id,
        "task": request.task,
        "status": "executing",
        "message": "Payment confirmed. Task dispatched to agent.",
        "payment_amount": str(payment.amount),
        "payment_currency": payment.currency,
    }


async def connect_wallet(db: AsyncSession, request: WalletConnectRequest) -> WalletInfo:
    """Connect an external wallet to an agent."""
    result = await db.execute(
        select(Wallet).where(
            Wallet.aaip_agent_id == request.aaip_agent_id,
            Wallet.chain == request.chain,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.address = request.address
        existing.is_active = True
        await db.commit()
        w = existing
    else:
        w = Wallet(
            aaip_agent_id=request.aaip_agent_id,
            chain=request.chain,
            address=request.address,
            wallet_mode="external",
        )
        db.add(w)
        await db.commit()
        await db.refresh(w)

    return WalletInfo(
        wallet_id=str(w.id),
        aaip_agent_id=w.aaip_agent_id,
        chain=w.chain,
        address=w.address,
        mode=w.wallet_mode,
    )


async def get_agent_balance(db: AsyncSession, aaip_agent_id: str) -> dict:
    """Get internal ledger balance for an agent."""
    result = await db.execute(
        select(
            LedgerEntry.currency,
            func.sum(
                func.case(
                    (LedgerEntry.entry_type.in_(["deposit", "credit"]), LedgerEntry.amount),
                    else_=-LedgerEntry.amount
                )
            ).label("balance")
        )
        .where(
            LedgerEntry.aaip_agent_id == aaip_agent_id,
            LedgerEntry.status == "confirmed",
        )
        .group_by(LedgerEntry.currency)
    )
    balances = {row[0]: str(row[1] or 0) for row in result}
    return {
        "aaip_agent_id": aaip_agent_id,
        "balances": balances,
        "supported_currencies": ["USDC", "USDT"],
        "supported_chains": list(CHAIN_CONFIGS.keys()),
    }
