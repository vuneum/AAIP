"""
AEP — Secrets Management Layer

Provides secure retrieval of private keys and sensitive configuration.
Supports multiple backends: environment variables, files, encrypted files.

Usage:
    from aaip.aep.secrets import get_secret
    
    # Get EVM private key
    evm_key = get_secret("evm_private_key")
    
    # Get Solana keypair path or encrypted key
    solana_key = get_secret("solana_keypair")

Configuration environment variables:
    AEP_SECRETS_BACKEND      - "env", "file", "encrypted_file" (default: "env")
    AEP_SECRETS_PASSPHRASE   - Passphrase for encrypted files (if using encrypted_file backend)
    AEP_SECRETS_PATH         - Path to secrets file or directory (for file backends)
"""

import os
import json
import logging
from typing import Any, Optional
from pathlib import Path

from .exceptions import AEPConfigurationError

log = logging.getLogger("aaip.aep.secrets")

# Backend types
BACKEND_ENV = "env"
BACKEND_FILE = "file"
BACKEND_ENCRYPTED_FILE = "encrypted_file"

# Secret names
SECRET_EVM_PRIVATE_KEY = "evm_private_key"
SECRET_SOLANA_KEYPAIR = "solana_keypair"
SECRET_SOLANA_PRIVATE_KEY = "solana_private_key"


def get_backend() -> str:
    """Get the configured secrets backend."""
    return os.environ.get("AEP_SECRETS_BACKEND", BACKEND_ENV).lower()


def get_secret(secret_name: str, default: Optional[str] = None) -> str:
    """
    Retrieve a secret by name.
    
    Args:
        secret_name: Name of the secret to retrieve
        default: Default value if secret is not found
        
    Returns:
        The secret value as a string
        
    Raises:
        AEPConfigurationError: If secret is required and not found
    """
    backend = get_backend()
    
    if backend == BACKEND_ENV:
        return _get_from_env(secret_name, default)
    elif backend == BACKEND_FILE:
        return _get_from_file(secret_name, default)
    elif backend == BACKEND_ENCRYPTED_FILE:
        return _get_from_encrypted_file(secret_name, default)
    else:
        raise AEPConfigurationError(f"Unknown secrets backend: {backend}")


def _get_from_env(secret_name: str, default: Optional[str]) -> str:
    """Get secret from environment variable."""
    # Map secret names to environment variable names
    env_map = {
        SECRET_EVM_PRIVATE_KEY: "AEP_PRIVATE_KEY",
        SECRET_SOLANA_KEYPAIR: "AEP_SOLANA_KEYPAIR",
        SECRET_SOLANA_PRIVATE_KEY: "AEP_SOLANA_PRIVATE_KEY",
    }
    
    env_var = env_map.get(secret_name, secret_name.upper())
    value = os.environ.get(env_var)
    
    if value is not None:
        log.debug(f"Retrieved secret '{secret_name}' from environment variable {env_var}")
        return value
    
    if default is not None:
        log.debug(f"Using default value for secret '{secret_name}'")
        return default
    
    raise AEPConfigurationError(
        f"Secret '{secret_name}' not found in environment variable {env_var}"
    )


def _get_from_file(secret_name: str, default: Optional[str]) -> str:
    """Get secret from a JSON or text file."""
    secrets_path = os.environ.get("AEP_SECRETS_PATH", "")
    if not secrets_path:
        raise AEPConfigurationError(
            "AEP_SECRETS_PATH must be set when using file backend"
        )
    
    path = Path(secrets_path)
    
    # If it's a directory, look for <secret_name>.txt or <secret_name>.json
    if path.is_dir():
        txt_file = path / f"{secret_name}.txt"
        json_file = path / f"{secret_name}.json"
        
        if txt_file.exists():
            value = txt_file.read_text().strip()
            log.debug(f"Retrieved secret '{secret_name}' from {txt_file}")
            return value
        elif json_file.exists():
            data = json.loads(json_file.read_text())
            if isinstance(data, dict) and "value" in data:
                value = data["value"]
            else:
                value = str(data)
            log.debug(f"Retrieved secret '{secret_name}' from {json_file}")
            return value
    else:
        # Single file containing all secrets as JSON
        if path.exists():
            data = json.loads(path.read_text())
            if secret_name in data:
                value = data[secret_name]
                log.debug(f"Retrieved secret '{secret_name}' from {path}")
                return str(value)
    
    if default is not None:
        log.debug(f"Using default value for secret '{secret_name}'")
        return default
    
    raise AEPConfigurationError(
        f"Secret '{secret_name}' not found in file {secrets_path}"
    )


def _get_from_encrypted_file(secret_name: str, default: Optional[str]) -> str:
    """Get secret from an encrypted file."""
    from .crypto import decrypt_seed
    
    secrets_path = os.environ.get("AEP_SECRETS_PATH", "")
    passphrase = os.environ.get("AEP_SECRETS_PASSPHRASE", "")
    
    if not secrets_path:
        raise AEPConfigurationError(
            "AEP_SECRETS_PATH must be set when using encrypted_file backend"
        )
    if not passphrase:
        raise AEPConfigurationError(
            "AEP_SECRETS_PASSPHRASE must be set when using encrypted_file backend"
        )
    
    path = Path(secrets_path)
    if not path.exists():
        if default is not None:
            log.debug(f"Using default value for secret '{secret_name}' (encrypted file not found)")
            return default
        raise AEPConfigurationError(f"Encrypted secrets file not found: {path}")
    
    # Load encrypted data
    try:
        encrypted_data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise AEPConfigurationError(f"Invalid JSON in encrypted secrets file: {e}")
    
    # Check if we have a single encrypted secret or a dictionary of encrypted secrets
    if isinstance(encrypted_data, dict) and "private_key_encrypted" in encrypted_data:
        # Single encrypted secret file
        if secret_name not in ["evm_private_key", "solana_private_key"]:
            raise AEPConfigurationError(
                f"Encrypted file contains a single private key, not '{secret_name}'"
            )
        
        try:
            # Decrypt the seed/private key
            seed_bytes = decrypt_seed(encrypted_data, passphrase)
            # Convert to hex string (for EVM) or keep as bytes (for Solana)
            if secret_name == SECRET_EVM_PRIVATE_KEY:
                return "0x" + seed_bytes.hex()
            else:
                # For Solana, we need to handle the keypair format
                # This is simplified - actual implementation would need to match Solana's format
                return seed_bytes.hex()
        except Exception as e:
            raise AEPConfigurationError(f"Failed to decrypt secret: {e}")
    
    elif isinstance(encrypted_data, dict):
        # Dictionary of encrypted secrets
        if secret_name not in encrypted_data:
            if default is not None:
                return default
            raise AEPConfigurationError(f"Secret '{secret_name}' not found in encrypted file")
        
        secret_data = encrypted_data[secret_name]
        if not isinstance(secret_data, dict) or "private_key_encrypted" not in secret_data:
            # Not encrypted, just stored as plain text in the JSON
            return str(secret_data)
        
        try:
            seed_bytes = decrypt_seed(secret_data, passphrase)
            return seed_bytes.hex()
        except Exception as e:
            raise AEPConfigurationError(f"Failed to decrypt secret '{secret_name}': {e}")
    
    else:
        raise AEPConfigurationError("Invalid encrypted secrets file format")


# Convenience functions for common secrets
def get_evm_private_key() -> str:
    """Get EVM private key from configured secrets backend."""
    return get_secret(SECRET_EVM_PRIVATE_KEY)


def get_solana_keypair_path() -> str:
    """Get Solana keypair file path from configured secrets backend."""
    return get_secret(SECRET_SOLANA_KEYPAIR, 
                     default=os.path.expanduser("~/.config/solana/id.json"))


def get_solana_private_key() -> Optional[str]:
    """Get Solana private key directly (if using encrypted backend)."""
    try:
        return get_secret(SECRET_SOLANA_PRIVATE_KEY)
    except AEPConfigurationError:
        return None