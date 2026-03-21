"""
AAIP Agent Identity
====================
Automatic keypair generation, deterministic agent IDs, and PoE signing.

Uses the `cryptography` package when available (fast, audited).
Falls back to a pure-Python RFC 8032 ed25519 (no external deps).

Usage:
    from aaip.identity import AgentIdentity

    identity = AgentIdentity.load_or_create()
    print(identity.agent_id)       # e.g. "8f21d3a4b7c91e2f"
    sig = identity.sign(some_bytes)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Optional fast path
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def _has_cryptography() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return True
    except ImportError:
        return False

HAS_CRYPTOGRAPHY = _has_cryptography()


# ---------------------------------------------------------------------------
# Atomic file operations and file locking
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    """
    Write content to path atomically using tempfile + os.replace.
    
    This ensures that concurrent processes never see a partially-written file.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".aaip-tmp-")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _acquire_lock(file_obj, exclusive: bool = True) -> None:
    """
    Acquire advisory file lock.
    
    Uses fcntl.flock on Unix and msvcrt.locking on Windows.
    """
    if sys.platform == "win32":
        import msvcrt
        pos = file_obj.tell()
        try:
            file_obj.seek(0)
            mode = msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK
            msvcrt.locking(file_obj.fileno(), mode, 1)
        finally:
            file_obj.seek(pos)
    else:
        import fcntl
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(file_obj.fileno(), mode)


def _release_lock(file_obj) -> None:
    """
    Release advisory file lock.
    """
    if sys.platform == "win32":
        import msvcrt
        pos = file_obj.tell()
        try:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            file_obj.seek(pos)
    else:
        import fcntl
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# AgentIdentity
# ---------------------------------------------------------------------------

class AgentIdentity:
    """
    ed25519 keypair + deterministic agent_id.

    Attributes
    ----------
    agent_id       : str   16-char hex = sha256(public_key)[:16]
    public_key_hex : str   32-byte public key as hex
    """

    IDENTITY_FILE = ".aaip-identity.json"

    def __init__(self, seed: bytes, public_key: bytes):
        self._seed      = seed          # 32-byte private seed
        self._pub       = public_key    # 32-byte public key
        self.public_key_hex = public_key.hex()
        self.agent_id   = hashlib.sha256(public_key).hexdigest()[:16]

    # ── factory ──────────────────────────────────────────────────────

    @classmethod
    def generate(cls) -> "AgentIdentity":
        seed = secrets.token_bytes(32)
        if HAS_CRYPTOGRAPHY:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: I001
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            priv = Ed25519PrivateKey.from_private_bytes(seed)
            pub  = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        else:
            pub = _ed25519_pubkey(seed)
        return cls(seed, pub)

    @classmethod
    def load_or_create(cls, path: str = IDENTITY_FILE) -> "AgentIdentity":
        # Check AAIP_IDENTITY_PATH env var for custom path
        env_path = os.environ.get("AAIP_IDENTITY_PATH")
        if env_path:
            path = env_path
        p = Path(path)
        if p.exists():
            # Use file locking for safe concurrent reads
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    _acquire_lock(f, exclusive=False)
                    try:
                        content = f.read()
                    finally:
                        _release_lock(f)
            except OSError as e:
                from ..exceptions import IdentityCorruptedError
                raise IdentityCorruptedError(
                    f"Cannot read identity file: {e}"
                ) from e
            try:
                d = json.loads(content)
            except json.JSONDecodeError as e:
                from ..exceptions import IdentityCorruptedError
                raise IdentityCorruptedError(
                    f"Identity file contains invalid JSON: {e}"
                ) from e
            # Check if identity is encrypted
            if "private_key_encrypted" in d:
                # Encrypted identity requires passphrase
                passphrase = os.environ.get("AAIP_IDENTITY_PASSPHRASE")
                if not passphrase or passphrase.strip() == "":
                    from ..exceptions import IdentityDecryptionError
                    raise IdentityDecryptionError(
                        "Identity is encrypted but AAIP_IDENTITY_PASSPHRASE is not set."
                    )
                # Validate required fields
                required: tuple[str, ...] = ("public_key_hex",)
                for field in required:
                    if field not in d:
                        from ..exceptions import IdentityCorruptedError
                        raise IdentityCorruptedError(
                            f"Encrypted identity missing required field: {field}"
                        )
                # Decrypt the seed
                from ._encryption import decrypt_seed
                try:
                    seed = decrypt_seed(d, passphrase)
                except Exception as e:
                    from ..exceptions import IdentityDecryptionError
                    raise IdentityDecryptionError(
                        f"Decryption failed: {e}"
                    ) from e
                try:
                    pub = bytes.fromhex(d["public_key_hex"])
                except ValueError as e:
                    from ..exceptions import IdentityCorruptedError
                    raise IdentityCorruptedError(
                        f"Invalid hex in public_key_hex: {e}"
                    ) from e
                identity = cls(seed, pub)
                logger.info("Loaded encrypted identity")
                return identity
            else:
                # Plaintext identity
                required = ("private_key_hex", "public_key_hex")
                for field in required:
                    if field not in d:
                        from ..exceptions import IdentityCorruptedError
                        raise IdentityCorruptedError(
                            f"Plaintext identity missing required field: {field}"
                        )
                try:
                    seed = bytes.fromhex(d["private_key_hex"])
                except ValueError as e:
                    from ..exceptions import IdentityCorruptedError
                    raise IdentityCorruptedError(
                        f"Invalid hex in private_key_hex: {e}"
                    ) from e
                try:
                    pub = bytes.fromhex(d["public_key_hex"])
                except ValueError as e:
                    from ..exceptions import IdentityCorruptedError
                    raise IdentityCorruptedError(
                        f"Invalid hex in public_key_hex: {e}"
                    ) from e
                identity = cls(seed, pub)
                # Warn if passphrase is set (should encrypt)
                passphrase = os.environ.get("AAIP_IDENTITY_PASSPHRASE")
                if passphrase and passphrase.strip() != "":
                    logger.info(
                        "Identity is plaintext; it will be encrypted on next save."
                    )
                else:
                    logger.warning(
                        "Private key stored without encryption. "
                        "Set AAIP_IDENTITY_PASSPHRASE for production security."
                    )
                return identity
        # Create new identity with exclusive lock to prevent race conditions
        # Double-check file existence after acquiring lock
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, 'a+') as f:
                _acquire_lock(f, exclusive=True)
                try:
                    f.seek(0)
                    content = f.read()
                    if content:
                        # File was created by another process while we waited
                        try:
                            d = json.loads(content)
                        except json.JSONDecodeError as e:
                            from ..exceptions import IdentityCorruptedError
                            raise IdentityCorruptedError(
                                f"Identity file contains invalid JSON: {e}"
                            ) from e
                        # Process the existing file
                        if "private_key_encrypted" in d:
                            passphrase = os.environ.get("AAIP_IDENTITY_PASSPHRASE")
                            if not passphrase or passphrase.strip() == "":
                                from ..exceptions import IdentityDecryptionError
                                raise IdentityDecryptionError(
                                    "Identity is encrypted but AAIP_IDENTITY_PASSPHRASE is not set."
                                )
                            required = ("public_key_hex",)
                            for field in required:
                                if field not in d:
                                    from ..exceptions import IdentityCorruptedError
                                    raise IdentityCorruptedError(
                                        f"Encrypted identity missing required field: {field}"
                                    )
                            from ._encryption import decrypt_seed
                            try:
                                seed = decrypt_seed(d, passphrase)
                            except Exception as e:
                                from ..exceptions import IdentityDecryptionError
                                raise IdentityDecryptionError(
                                    f"Decryption failed: {e}"
                                ) from e
                            try:
                                pub = bytes.fromhex(d["public_key_hex"])
                            except ValueError as e:
                                from ..exceptions import IdentityCorruptedError
                                raise IdentityCorruptedError(
                                    f"Invalid hex in public_key_hex: {e}"
                                ) from e
                            return cls(seed, pub)
                        else:
                            required = ("private_key_hex", "public_key_hex")
                            for field in required:
                                if field not in d:
                                    from ..exceptions import IdentityCorruptedError
                                    raise IdentityCorruptedError(
                                        f"Plaintext identity missing required field: {field}"
                                    )
                            try:
                                seed = bytes.fromhex(d["private_key_hex"])
                            except ValueError as e:
                                from ..exceptions import IdentityCorruptedError
                                raise IdentityCorruptedError(
                                    f"Invalid hex in private_key_hex: {e}"
                                ) from e
                            try:
                                pub = bytes.fromhex(d["public_key_hex"])
                            except ValueError as e:
                                from ..exceptions import IdentityCorruptedError
                                raise IdentityCorruptedError(
                                    f"Invalid hex in public_key_hex: {e}"
                                ) from e
                            return cls(seed, pub)
                    else:
                        # File is empty, create new identity
                        identity = cls.generate()
                        identity.save(path)
                        return identity
                finally:
                    _release_lock(f)
        except OSError as e:
            from ..exceptions import IdentityCorruptedError
            raise IdentityCorruptedError(
                f"Cannot create identity file: {e}"
            ) from e

    def save(self, path: str = IDENTITY_FILE) -> None:
        passphrase = os.environ.get("AAIP_IDENTITY_PASSPHRASE")
        if passphrase is not None:
            stripped = passphrase.strip()
            if stripped and len(stripped) < 8:
                raise ValueError("Passphrase must be at least 8 characters")
        data = {
            "aaip_version":    "1.0",
            "created_at":      int(time.time()),
            "agent_id":        self.agent_id,
            "public_key_hex":  self.public_key_hex,
        }
        if passphrase and passphrase.strip() != "":
            # Encrypt the seed
            from ._encryption import encrypt_seed
            encrypted = encrypt_seed(self._seed, passphrase)
            data.update(encrypted)
            # Keep private_key_hex empty to avoid confusion
            data["private_key_hex"] = ""
            logger.info("Saved encrypted identity")
        else:
            # Plaintext storage (backward compatibility)
            data["private_key_hex"] = self._seed.hex()
            logger.warning(
                "Private key stored without encryption. "
                "Set AAIP_IDENTITY_PASSPHRASE for production security."
            )
        _atomic_write(Path(path), json.dumps(data, indent=2))

    # ── sign / verify ────────────────────────────────────────────────

    def sign(self, data: bytes) -> bytes:
        """Return 64-byte ed25519 signature."""
        if HAS_CRYPTOGRAPHY:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            return Ed25519PrivateKey.from_private_bytes(self._seed).sign(data)
        return _ed25519_sign(self._seed, data)

    def sign_hex(self, data: bytes) -> str:
        return self.sign(data).hex()

    def verify(self, data: bytes, signature: bytes) -> bool:
        if HAS_CRYPTOGRAPHY:
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                Ed25519PublicKey.from_public_bytes(self._pub).verify(signature, data)
                return True
            except Exception:
                return False
        return _ed25519_verify(self._pub, data, signature)

    def __repr__(self) -> str:
        return f"<AgentIdentity id={self.agent_id} key={self.public_key_hex[:12]}...>"


# ---------------------------------------------------------------------------
# Pure-Python ed25519 — RFC 8032 §5.1
# Based on the DJB/SUPERCOP reference (public domain).
# B, d, I are derived at import time — no hardcoded curve constants.
# ---------------------------------------------------------------------------

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493

def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)

_D = (-121665 * _inv(121666)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    y2 = y * y % _P
    x2 = (y2 - 1) * _inv(_D * y2 + 1) % _P
    if x2 == 0:
        return 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if x % 2 != 0:
        x = _P - x
    return x


# Derive base point (no hardcoding)
_By = 4 * _inv(5) % _P
_Bx = _xrecover(_By)
_B  = [_Bx % _P, _By % _P]


def _eadd(P: list, Q: list) -> list:
    """Twisted Edwards addition (a = -1)."""
    x1, y1 = P; x2, y2 = Q
    dxy = _D * x1 * x2 * y1 * y2 % _P
    x3  = (x1 * y2 + x2 * y1) * _inv((1 + dxy) % _P) % _P
    y3  = (y1 * y2 + x1 * x2) * _inv((1 - dxy) % _P) % _P
    return [x3 % _P, y3 % _P]


def _smul(P: list, e: int) -> list:
    """Iterative double-and-add scalar multiplication."""
    Q = [0, 1]   # identity
    while e > 0:
        if e & 1:
            Q = _eadd(Q, P)
        P = _eadd(P, P)
        e >>= 1
    return Q


def _enc(P: list) -> bytes:
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _dec(s: bytes) -> list:
    y = sum(((s[i // 8] >> (i % 8)) & 1) << i for i in range(255))
    x = _xrecover(y)
    if x & 1 != (s[31] >> 7) & 1:
        x = _P - x
    return [x, y]


def _hint(m: bytes) -> int:
    h = hashlib.sha512(m).digest()
    return sum(((h[i // 8] >> (i % 8)) & 1) << i for i in range(512))


def _scalar(seed: bytes) -> int:
    """RFC 8032 §5.1.5 — clamp and derive scalar from seed."""
    h = hashlib.sha512(seed).digest()
    # Clamp per spec: clear bits 0,1,2,255; set bit 254
    a = int.from_bytes(h[:32], "little")
    a &= ~7           # clear low 3 bits
    a &= ~(1 << 255)  # clear bit 255
    a |=  (1 << 254)  # set bit 254
    return a


def _ed25519_pubkey(seed: bytes) -> bytes:
    return _enc(_smul(_B, _scalar(seed)))


def _ed25519_sign(seed: bytes, message: bytes) -> bytes:
    h      = hashlib.sha512(seed).digest()
    a      = _scalar(seed)
    pub    = _enc(_smul(_B, a))
    r      = _hint(h[32:] + message)
    R      = _enc(_smul(_B, r))
    k      = _hint(R + pub + message)
    S      = (r + k * a) % _L
    return R + S.to_bytes(32, "little")


def _ed25519_verify(public_key: bytes, message: bytes, sig: bytes) -> bool:
    try:
        if len(sig) != 64 or len(public_key) != 32:
            return False
        R = _dec(sig[:32])
        A = _dec(public_key)
        S = int.from_bytes(sig[32:], "little")
        if S >= _L:
            return False
        k   = _hint(sig[:32] + public_key + message)
        lhs = _smul(_B, S)
        rhs = _eadd(R, _smul(A, k))
        return lhs == rhs
    except Exception:
        return False
