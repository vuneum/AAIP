"""
AEP — Structured Exception Hierarchy

All AEP exceptions inherit from AEPError so callers can catch
the entire family with a single except clause, or target specific
sub-types for fine-grained handling.
"""


class AEPError(Exception):
    """Base class for all Agent Economy Protocol errors."""

    def __init__(self, message: str, error_code: str = "AEP_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.error_code!r}: {self})"


# ── Input / validation ────────────────────────────────────────────────────────

class AEPValidationError(AEPError):
    """Raised when payment inputs fail validation."""


class InvalidAmountError(AEPValidationError):
    def __init__(self, amount: object) -> None:
        super().__init__(
            f"Amount must be a positive number, got {amount!r}",
            "INVALID_AMOUNT",
        )


class InvalidAddressError(AEPValidationError):
    def __init__(self, address: str) -> None:
        super().__init__(
            f"Recipient address is invalid: {address!r}",
            "INVALID_ADDRESS",
        )


class InvalidAgentIDError(AEPValidationError):
    def __init__(self, agent_id: object) -> None:
        super().__init__(
            f"agent_id must be a non-empty string, got {agent_id!r}",
            "INVALID_AGENT_ID",
        )


# ── Adapter / infrastructure ──────────────────────────────────────────────────

class AEPAdapterError(AEPError):
    """Raised when the payment adapter encounters an error."""


class AEPConfigurationError(AEPError):
    """Raised when AEP is misconfigured (missing env vars, etc.)."""


# ── Anchoring ─────────────────────────────────────────────────────────────────

class AEPAnchorError(AEPError):
    """Raised when proof anchoring fails."""
