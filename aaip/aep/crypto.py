"""
Cryptographic utilities for AEP.

Provides encryption/decryption functions for secrets management.
Uses AES-256-GCM with PBKDF2 key derivation when cryptography is available.
"""

import base64
import secrets
from typing import Dict, Any, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

from .exceptions import AEPConfigurationError


class CryptoUnavailableError(AEPConfigurationError):
    """Raised when cryptography is required but not available."""
    pass


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """
    Derive a 32-byte AES‑256 key from a passphrase using PBKDF2‑HMAC‑SHA256.

    Args:
        passphrase: The passphrase as a string.
        salt: 16‑byte random salt.

    Returns:
        32‑byte key suitable for AES‑256.
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        raise CryptoUnavailableError(
            "cryptography library is required for key derivation. "
            "Install it with: pip install cryptography"
        )
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def decrypt_seed(data: Dict[str, Any], passphrase: str) -> bytes:
    """
    Decrypt a seed from the encrypted‑fields dictionary.

    Args:
        data: Dictionary as returned by `encrypt_seed`.
        passphrase: The same passphrase used for encryption.

    Returns:
        The original 32‑byte seed.

    Raises:
        AEPConfigurationError: If decryption fails (wrong passphrase,
            corrupted data, missing fields, or cryptography unavailable).
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        raise CryptoUnavailableError(
            "cryptography library is required for encrypted file backend. "
            "Install it with: pip install cryptography"
        )
    
    try:
        # Validate required fields
        required = (
            "private_key_encrypted",
            "encryption_salt",
            "encryption_iv",
            "encryption_tag",
            "encryption_method",
            "encryption_version",
        )
        for field in required:
            if field not in data:
                raise ValueError(f"Missing field: {field}")

        if data["encryption_method"] != "AES-256-GCM-PBKDF2":
            raise ValueError(f"Unsupported method: {data['encryption_method']}")
        if int(data["encryption_version"]) != 1:
            raise ValueError(f"Unsupported version: {data['encryption_version']}")

        # Decode base64
        ciphertext = base64.b64decode(data["private_key_encrypted"])
        salt = base64.b64decode(data["encryption_salt"])
        iv = base64.b64decode(data["encryption_iv"])
        tag = base64.b64decode(data["encryption_tag"])

        # Reconstruct ciphertext + tag
        ciphertext_with_tag = ciphertext + tag

        # Derive key
        key = derive_key(passphrase, salt)

        # Decrypt
        aesgcm = AESGCM(key)
        seed = aesgcm.decrypt(iv, ciphertext_with_tag, None)

        if len(seed) != 32:
            raise ValueError("Decrypted seed length mismatch")

        return seed

    except Exception as e:
        # Re‑raise as AEPConfigurationError
        raise AEPConfigurationError(f"Decryption failed: {e}") from e


def encrypt_seed(seed: bytes, passphrase: str) -> Dict[str, Any]:
    """
    Encrypt a 32‑byte ed25519 seed with AES‑256‑GCM.

    Args:
        seed: The 32‑byte private seed.
        passphrase: Passphrase for key derivation.

    Returns:
        Dictionary with base64‑encoded encrypted fields.
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        raise CryptoUnavailableError(
            "cryptography library is required for encryption. "
            "Install it with: pip install cryptography"
        )
    
    if len(seed) != 32:
        raise ValueError("Seed must be 32 bytes")

    # Generate random salt (16 bytes) and nonce (12 bytes for AES‑GCM)
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)

    # Derive key
    key = derive_key(passphrase, salt)

    # Encrypt
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, seed, None)

    # Split ciphertext and tag (GCM tag is last 16 bytes)
    ciphertext = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]

    return {
        "private_key_encrypted": base64.b64encode(ciphertext).decode("ascii"),
        "encryption_salt": base64.b64encode(salt).decode("ascii"),
        "encryption_iv": base64.b64encode(iv).decode("ascii"),
        "encryption_tag": base64.b64encode(tag).decode("ascii"),
        "encryption_method": "AES-256-GCM-PBKDF2",
        "encryption_version": 1,
    }