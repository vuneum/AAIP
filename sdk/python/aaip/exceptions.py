"""
AAIP exception hierarchy.
"""


class AAIPError(Exception):
    """Base exception for all AAIP-specific errors."""
    pass


class IdentityDecryptionError(AAIPError):
    """Raised when identity decryption fails (e.g., wrong passphrase)."""
    pass