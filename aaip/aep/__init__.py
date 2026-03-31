"""
AEP — Agent Economy Protocol
Public surface.

Quick-start::

    from aaip.aep import execute_payment, anchor_proof

    result = execute_payment(
        agent_id="my_agent",
        recipient_address="0xABCDEF...",
        amount=0.01,
        poe_hash="0xdeadbeef...",
    )
    print(result["tx_hash"])
"""

from .core import anchor_proof, execute_payment, get_anchors
from .exceptions import (
    AEPAdapterError,
    AEPAnchorError,
    AEPConfigurationError,
    AEPError,
    AEPValidationError,
    InvalidAddressError,
    InvalidAgentIDError,
    InvalidAmountError,
)
from .adapters import BasePaymentAdapter, EVMPaymentAdapter, MockPaymentAdapter

__all__ = [
    # Core API
    "execute_payment",
    "anchor_proof",
    "get_anchors",
    # Adapters
    "BasePaymentAdapter",
    "MockPaymentAdapter",
    "EVMPaymentAdapter",
    # Exceptions
    "AEPError",
    "AEPValidationError",
    "AEPAdapterError",
    "AEPAnchorError",
    "AEPConfigurationError",
    "InvalidAmountError",
    "InvalidAddressError",
    "InvalidAgentIDError",
]
