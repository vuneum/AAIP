"""
AAIP Deterministic Proof of Execution (PoE v2)
================================================
Deterministic, signed execution traces.

Key properties:
  - Fixed JSON structure with no non-deterministic fields
  - SHA-256 of canonical JSON → poe_hash
  - Agent signs the hash with ed25519
  - Validators independently recompute the same hash to verify

PoE object schema:
  {
    "aaip_version": "2.0",
    "agent_id":     "<16-char hex>",
    "task":         "<task description>",
    "tools_used":   ["tool_a", "tool_b"],
    "model_used":   "<model name or null>",
    "output_hash":  "<sha256 of raw output>",
    "step_count":   <int>,
    "timestamp":    <unix seconds int>,
    "poe_hash":     "<sha256 of canonical fields above>",
    "signature":    "<ed25519 sig of poe_hash, hex>"
  }

Usage:
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE

    identity = AgentIdentity.load_or_create()
    poe = DeterministicPoE(identity)

    poe.begin("Summarise the Q3 earnings report")
    poe.record_tool("web_search")
    poe.record_tool("read_pdf")
    poe.record_model("gpt-4o")
    poe.set_output("The Q3 revenue was $4.2B, up 18% YoY...")
    poe.finish()

    print(poe.poe_hash)     # deterministic hash
    print(poe.to_dict())    # full signed object
"""

from __future__ import annotations

import hashlib
import json
import time


class DeterministicPoE:
    """
    Build and sign a deterministic Proof of Execution.

    All fields that feed into the hash are deterministic:
      - agent_id, task, tools_used, model_used, output_hash, step_count, timestamp
    The timestamp is fixed when finish() is called and rounded to whole seconds.
    """

    AAIP_VERSION = "2.0"

    def __init__(self, identity: AgentIdentity) -> None:  # noqa: F821
        """
        Parameters
        ----------
        identity : AgentIdentity
        """
        self._identity = identity
        self._task = ""
        self._tools: list[str] = []
        self._model: str | None = None
        self._output_raw: str | None = None
        self._step_count = 0
        self._timestamp: int | None = None
        self._poe_hash: str | None = None
        self._signature: str | None = None
        self._finished = False

    # ------------------------------------------------------------------
    # Building the trace
    # ------------------------------------------------------------------

    def begin(self, task: str) -> DeterministicPoE:
        """Set the task description."""
        self._task = task
        return self

    def record_tool(self, tool_name: str) -> DeterministicPoE:
        """Record that a tool was used."""
        if tool_name not in self._tools:
            self._tools.append(tool_name)
        self._step_count += 1
        return self

    def record_model(self, model_name: str) -> DeterministicPoE:
        """Record which model was used (last one wins)."""
        self._model = model_name
        self._step_count += 1
        return self

    def record_step(self) -> DeterministicPoE:
        """Increment step counter for any other significant step."""
        self._step_count += 1
        return self

    def set_output(self, output: str) -> DeterministicPoE:
        """Set the final agent output (stored as hash only)."""
        self._output_raw = output
        return self

    def finish(self) -> DeterministicPoE:
        """
        Finalise the PoE: set timestamp, compute hash, sign.
        Call this once after all tools/model/output are recorded.
        """
        if self._finished:
            return self

        self._timestamp = int(time.time())

        # Compute output hash
        output_hash = hashlib.sha256((self._output_raw or "").encode()).hexdigest()

        # Build deterministic canonical dict (alphabetical key order)
        canonical = {
            "aaip_version": self.AAIP_VERSION,
            "agent_id": self._identity.agent_id,
            "model_used": self._model,
            "output_hash": output_hash,
            "step_count": self._step_count,
            "task": self._task,
            "timestamp": self._timestamp,
            "tools_used": sorted(self._tools),  # sorted = deterministic
        }

        # Canonical JSON (sorted keys, no whitespace)
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))

        # Hash
        self._poe_hash = hashlib.sha256(canonical_json.encode()).hexdigest()

        # Sign hash
        self._signature = self._identity.sign_hex(bytes.fromhex(self._poe_hash))

        self._canonical = canonical
        self._finished = True
        return self

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    @property
    def poe_hash(self) -> str:
        if not self._finished:
            raise RuntimeError("Call finish() before accessing poe_hash")
        return self._poe_hash

    @property
    def signature(self) -> str:
        if not self._finished:
            raise RuntimeError("Call finish() before accessing signature")
        return self._signature

    def to_dict(self) -> dict:
        """Return the full signed PoE object."""
        if not self._finished:
            raise RuntimeError("Call finish() first")
        return {
            **self._canonical,
            "poe_hash": self._poe_hash,
            "signature": self._signature,
            "public_key": self._identity.public_key_hex,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> DeterministicPoE:
        return self

    def __exit__(self, *_) -> bool:
        if not self._finished:
            self.finish()
        return False


# ---------------------------------------------------------------------------
# Standalone verification (no identity object needed)
# ---------------------------------------------------------------------------


class PoEVerifier:
    """
    Verify a signed PoE object.
    Can be used by validators without any agent context.
    """

    FRAUD_SIGNALS = [
        "NO_TASK",
        "NO_TOOLS_AND_NO_MODEL",
        "FUTURE_TIMESTAMP",
        "NEGATIVE_STEP_COUNT",
        "HASH_MISMATCH",
        "SIGNATURE_INVALID",
    ]

    def verify(self, poe_dict: dict) -> VerificationResult:
        """
        Verify a PoE dictionary.

        Returns
        -------
        VerificationResult with verdict and triggered signals.
        """
        signals = []

        # 1. Required fields present
        required = [
            "agent_id",
            "task",
            "tools_used",
            "model_used",
            "output_hash",
            "step_count",
            "timestamp",
            "poe_hash",
            "signature",
            "public_key",
        ]
        missing = [k for k in required if k not in poe_dict]
        if missing:
            return VerificationResult(
                verdict="invalid",
                signals=[f"MISSING_FIELDS:{','.join(missing)}"],
                hash_verified=False,
                signature_verified=False,
            )

        # 2. Task not empty
        if not poe_dict.get("task", "").strip():
            signals.append("NO_TASK")

        # 3. Tools or model required
        if not poe_dict.get("tools_used") and not poe_dict.get("model_used"):
            signals.append("NO_TOOLS_AND_NO_MODEL")

        # 4. Timestamp not in future (allow 60s clock drift)
        now = int(time.time())
        ts = poe_dict.get("timestamp", 0)
        if ts > now + 60:
            signals.append("FUTURE_TIMESTAMP")

        # 5. Step count non-negative
        if poe_dict.get("step_count", 0) < 0:
            signals.append("NEGATIVE_STEP_COUNT")

        # 6. Recompute hash
        canonical = {
            "aaip_version": poe_dict.get("aaip_version", "2.0"),
            "agent_id": poe_dict["agent_id"],
            "model_used": poe_dict["model_used"],
            "output_hash": poe_dict["output_hash"],
            "step_count": poe_dict["step_count"],
            "task": poe_dict["task"],
            "timestamp": poe_dict["timestamp"],
            "tools_used": sorted(poe_dict["tools_used"]),
        }
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(canonical_json.encode()).hexdigest()
        hash_ok = expected_hash == poe_dict["poe_hash"]
        if not hash_ok:
            signals.append("HASH_MISMATCH")

        # 7. Verify signature — works with both cryptography and pure-python fallback
        sig_ok = False
        try:
            pub_bytes = bytes.fromhex(poe_dict["public_key"])
            sig_bytes = bytes.fromhex(poe_dict["signature"])
            hash_bytes = bytes.fromhex(poe_dict["poe_hash"])
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

                pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
                pub.verify(sig_bytes, hash_bytes)
                sig_ok = True
            except ImportError:
                from ..identity import _ed25519_verify

                sig_ok = _ed25519_verify(pub_bytes, hash_bytes, sig_bytes)
        except Exception:
            pass
        if not sig_ok:
            signals.append("SIGNATURE_INVALID")

        # Verdict
        if signals:
            verdict = (
                "invalid"
                if (
                    "HASH_MISMATCH" in signals
                    or "SIGNATURE_INVALID" in signals
                    or "MISSING_FIELDS" in str(signals)
                )
                else "suspicious"
            )
        else:
            verdict = "verified"

        return VerificationResult(
            verdict=verdict,
            signals=signals,
            hash_verified=hash_ok,
            signature_verified=sig_ok,
        )


class VerificationResult:
    def __init__(
        self, verdict: str, signals: list[str], hash_verified: bool, signature_verified: bool
    ) -> None:
        self.verdict = verdict
        self.signals = signals
        self.hash_verified = hash_verified
        self.signature_verified = signature_verified
        self.approved = verdict == "verified"

    def __repr__(self) -> str:
        return (
            f"<VerificationResult verdict={self.verdict} "
            f"hash={self.hash_verified} sig={self.signature_verified} "
            f"signals={self.signals}>"
        )
