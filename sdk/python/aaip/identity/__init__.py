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
import secrets
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Optional fast path
# ---------------------------------------------------------------------------

def _has_cryptography() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return True
    except ImportError:
        return False

HAS_CRYPTOGRAPHY = _has_cryptography()


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
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat, PrivateFormat, NoEncryption,
            )
            priv = Ed25519PrivateKey.from_private_bytes(seed)
            pub  = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        else:
            pub = _ed25519_pubkey(seed)
        return cls(seed, pub)

    @classmethod
    def load_or_create(cls, path: str = IDENTITY_FILE) -> "AgentIdentity":
        p = Path(path)
        if p.exists():
            d    = json.loads(p.read_text())
            seed = bytes.fromhex(d["private_key_hex"])
            pub  = bytes.fromhex(d["public_key_hex"])
            return cls(seed, pub)
        identity = cls.generate()
        identity.save(path)
        return identity

    def save(self, path: str = IDENTITY_FILE) -> None:
        Path(path).write_text(json.dumps({
            "aaip_version":    "1.0",
            "created_at":      int(time.time()),
            "agent_id":        self.agent_id,
            "public_key_hex":  self.public_key_hex,
            "private_key_hex": self._seed.hex(),
        }, indent=2))

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
