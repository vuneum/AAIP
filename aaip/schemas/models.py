"""
aaip/schemas/models.py — AEP Protocol Definition Layer

Dataclass-based models (stdlib only — no pydantic required).
Each model has:
  - typed fields with defaults
  - a validate() method that raises ValueError on bad input
  - to_dict() / from_dict() for JSON serialisation

Install pydantic for full validation + JSON Schema export:
    pip install pydantic>=2.0
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import time
import uuid
from enum import Enum
from typing import Any


# ── Enumerations ──────────────────────────────────────────────────────────────

class PaymentStatus(str, Enum):
    PENDING   = "pending"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"

class ValidationOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ABSTAIN  = "ABSTAIN"

class AdapterType(str, Enum):
    MOCK    = "mock"
    EVM     = "evm"
    SOLANA  = "solana"
    CREDITS = "credits"


# ── Validation helpers ────────────────────────────────────────────────────────

_POE_HASH_RE  = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_AGENT_ID_RE  = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")
_ADDRESS_RE   = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _validate_poe_hash(v: str) -> str:
    if not _POE_HASH_RE.match(v):
        raise ValueError(f"poe_hash must be 0x + 64 hex chars, got {v!r}")
    return v.lower() if not v.startswith("0x") else v


def _validate_agent_id(v: str) -> str:
    if not _AGENT_ID_RE.match(v):
        raise ValueError(f"agent_id must be alphanumeric/underscore/dash, got {v!r}")
    return v


_SOLANA_B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _validate_address(v: str, field_name: str = "address") -> str:
    """
    Validate an on-chain address.

    Accepts:
      - EVM:    0x-prefixed 40-hex-char string  (case-insensitive)
      - Solana: 32-44 char base58 string
      - Credits: any non-empty alphanumeric agent_id (off-chain)

    The check is permissive for off-chain adapters (credits/tests) where
    the address is really an agent identifier. For EVM-formatted strings
    the hex check is strict.
    """
    if not v or not isinstance(v, str):
        raise ValueError(f"{field_name} must be a non-empty string")

    # EVM format: strict hex check
    if v.startswith("0x"):
        if len(v) != 42 or not all(c in "0123456789abcdefABCDEF" for c in v[2:]):
            raise ValueError(
                f"{field_name} looks like an EVM address but is malformed: {v!r}. "
                "Expected 0x + 40 hex chars."
            )
        return v

    # Solana format: base58, 32-44 chars
    if 32 <= len(v) <= 44 and all(c in _SOLANA_B58 for c in v):
        return v

    # Off-chain / credits: accept agent_id-style strings
    if _AGENT_ID_RE.match(v):
        return v

    raise ValueError(
        f"{field_name} is not a valid address: {v!r}. "
        "Expected EVM (0x...), Solana (base58), or agent_id."
    )


def _uid() -> str: return str(uuid.uuid4())
def _now() -> float: return time.time()


# ── Mixin ─────────────────────────────────────────────────────────────────────

class _Serialisable:
    def to_dict(self) -> dict[str, Any]:
        def _convert(v):
            if isinstance(v, Enum):      return v.value
            if isinstance(v, _Serialisable): return v.to_dict()
            if dataclasses.is_dataclass(v):  return dataclasses.asdict(v)
            return v
        return {k: _convert(v) for k, v in dataclasses.asdict(self).items()}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ── Core protocol models ──────────────────────────────────────────────────────

@dataclasses.dataclass
class PoEReference(_Serialisable):
    """Lightweight pointer to a Proof-of-Execution."""
    poe_hash:  str
    agent_id:  str
    timestamp: float               = dataclasses.field(default_factory=_now)
    task_id:   str | None          = None

    def __post_init__(self):
        self.poe_hash  = _validate_poe_hash(self.poe_hash)
        self.agent_id  = _validate_agent_id(self.agent_id)


@dataclasses.dataclass
class ValidationResult(_Serialisable):
    """Outcome from the AAIP validator panel."""
    outcome:         ValidationOutcome
    signals:         list[str]     = dataclasses.field(default_factory=list)
    validator_count: int           = 3
    approved_count:  int           = 0
    threshold:       float         = 0.667
    validated_at:    float         = dataclasses.field(default_factory=_now)

    def __post_init__(self):
        if not isinstance(self.outcome, ValidationOutcome):
            self.outcome = ValidationOutcome(self.outcome)


@dataclasses.dataclass
class PaymentRequest(_Serialisable):
    """
    Inbound request to execute an agent payment.
    The canonical input to execute_payment() and POST /payments.
    """
    agent_id:          str
    recipient_address: str
    amount:            float
    currency:          str                  = "ETH"
    poe_hash:          str | None           = None
    metadata:          dict[str, Any]       = dataclasses.field(default_factory=dict)
    idempotency_key:   str | None           = None
    request_id:        str                  = dataclasses.field(default_factory=_uid)
    requested_at:      float                = dataclasses.field(default_factory=_now)

    def __post_init__(self):
        self.agent_id = _validate_agent_id(self.agent_id)
        _validate_address(self.recipient_address, "recipient_address")
        if self.amount <= 0:
            raise ValueError(f"amount must be > 0, got {self.amount}")
        if self.amount > 1_000_000:
            raise ValueError(f"amount {self.amount} exceeds safety cap")
        if self.poe_hash:
            self.poe_hash = _validate_poe_hash(self.poe_hash)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.agent_id}:{self.recipient_address}:{self.amount}:{self.poe_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclasses.dataclass
class ExecutionReceipt(_Serialisable):
    """
    Signed proof that a payment settled.
    Immutable once created — represents a settled fact.
    """
    request_id:   str
    agent_id:     str
    recipient:    str
    amount:       float
    status:       PaymentStatus
    currency:     str                    = "ETH"
    tx_hash:      str | None             = None
    explorer_url: str | None             = None
    poe_hash:     str | None             = None
    block_number: int | None             = None
    gas_used:     int | None             = None
    protocol_fee:   float | None = None
    fee_rate:       float        = 0.02
    treasury:       str | None   = None
    adapter:      AdapterType            = AdapterType.MOCK
    error:        str | None             = None
    settled_at:   float                  = dataclasses.field(default_factory=_now)
    validation:   ValidationResult | None = None
    receipt_id:   str                    = dataclasses.field(default_factory=_uid)

    def __post_init__(self):
        if not isinstance(self.status,  PaymentStatus): self.status  = PaymentStatus(self.status)
        if not isinstance(self.adapter, AdapterType):   self.adapter = AdapterType(self.adapter)
        if self.status == PaymentStatus.SUCCESS and not self.tx_hash:
            raise ValueError("tx_hash required when status is SUCCESS")


@dataclasses.dataclass
class AgentWallet(_Serialisable):
    """
    An agent's on-chain identity and payment ledger.
    Tracks address, balances, tx history, and CAV score.
    """
    agent_id:       str
    address:        str
    chain_id:       int   = 11155111
    currency:       str   = "ETH"
    balance:        float = 0.0
    total_paid:     float = 0.0
    total_received: float = 0.0
    tx_count:       int   = 0
    cav_score:      float = 0.0
    wallet_id:      str   = dataclasses.field(default_factory=_uid)
    created_at:     float = dataclasses.field(default_factory=_now)
    last_active_at: float = dataclasses.field(default_factory=_now)

    def __post_init__(self):
        self.agent_id = _validate_agent_id(self.agent_id)
        _validate_address(self.address, "wallet address")

    def credit(self, amount: float) -> "AgentWallet":
        return dataclasses.replace(self,
            total_received=round(self.total_received + amount, 18),
            tx_count=self.tx_count + 1,
            last_active_at=time.time())

    def debit(self, amount: float) -> "AgentWallet":
        return dataclasses.replace(self,
            total_paid=round(self.total_paid + amount, 18),
            tx_count=self.tx_count + 1,
            last_active_at=time.time())

    def bump_cav(self, delta: float = 1.0) -> "AgentWallet":
        return dataclasses.replace(self,
            cav_score=round(self.cav_score + delta, 4))


@dataclasses.dataclass
class AgentTask(_Serialisable):
    """
    A billable unit of work.
    Every AAIP pipeline step maps to one AgentTask.
    The cost field drives automatic payment on completion.
    """
    description:  str
    agent_id:     str
    requester_id: str
    cost:         float          = 0.0
    currency:     str            = "ETH"
    poe_hash:     str | None     = None
    status:       str            = "pending"
    task_id:      str            = dataclasses.field(default_factory=_uid)
    created_at:   float          = dataclasses.field(default_factory=_now)
    completed_at: float | None   = None
    result_hash:  str | None     = None

    def __post_init__(self):
        self.agent_id     = _validate_agent_id(self.agent_id)
        self.requester_id = _validate_agent_id(self.requester_id)
        if len(self.description.encode("utf-8")) > 4096:
            raise ValueError("description exceeds 4096 bytes")
        if self.cost < 0:
            raise ValueError("cost must be >= 0")


@dataclasses.dataclass
class UsageRecord(_Serialisable):
    """
    Metered usage for SaaS/API billing.
    Accumulated per agent per period; used to generate PaymentRequests.
    """
    agent_id:    str
    endpoint:    str
    tokens_in:   int   = 0
    tokens_out:  int   = 0
    cost_usd:    float = 0.0
    cost_eth:    float = 0.0
    period:      str   = ""
    record_id:   str   = dataclasses.field(default_factory=_uid)
    recorded_at: float = dataclasses.field(default_factory=_now)

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out
