"""
AEP — Agent Economy Protocol
Base payment adapter interface.
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePaymentAdapter(ABC):
    """
    Abstract base class for all payment adapters.
    
    Implement this interface to support any blockchain,
    payment network, or mock backend.
    """

    @abstractmethod
    def send_payment(
        self,
        to: str,
        amount: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a payment to the given address.

        Args:
            to:       Recipient address (chain-specific format).
            amount:   Amount to send (in the adapter's native unit).
            metadata: Optional key-value payload attached to the tx.

        Returns:
            {
                "tx_hash":   str  — transaction identifier,
                "status":    str  — "success" | "failed",
                "block":     int | None,
                "gas_used":  int | None,
                "error":     str | None,
            }
        """
        ...

    @abstractmethod
    def is_valid_address(self, address: str) -> bool:
        """Return True if address is valid for this adapter."""
        ...
