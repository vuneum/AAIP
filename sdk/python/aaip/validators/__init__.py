"""
AAIP Validator Simulation
==========================
Simulates a local panel of validators verifying a PoE object.

Used by `aaip demo` and the explorer — no network required.

Usage:
    from aaip.validators import ValidatorPanel

    panel = ValidatorPanel(n=3)
    result = panel.vote(poe_dict)

    print(result.consensus)   # "APPROVED" or "REJECTED"
    print(result.votes)       # [ValidatorVote, ...]
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from ..poe.deterministic import PoEVerifier

# ---------------------------------------------------------------------------
# Single Validator
# ---------------------------------------------------------------------------


@dataclass
class Validator:
    """A single simulated validator node."""

    validator_id: str
    stake: float = 100.0  # USDC equivalent
    reputation: float = 95.0

    def verify(self, poe_dict: dict) -> ValidatorVote:
        """Independently verify a PoE object and return a signed vote."""
        verifier = PoEVerifier()
        result = verifier.verify(poe_dict)

        vote = ValidatorVote(
            validator_id=self.validator_id,
            approved=result.approved,
            verdict=result.verdict,
            signals=result.signals,
            hash_verified=result.hash_verified,
            signature_verified=result.signature_verified,
            stake=self.stake,
            timestamp=int(time.time()),
        )
        # Sign the vote itself
        vote.vote_hash = hashlib.sha256(
            f"{self.validator_id}:{poe_dict.get('poe_hash', '')}:{vote.approved}".encode()
        ).hexdigest()[:16]

        return vote


@dataclass
class ValidatorVote:
    """Result from a single validator."""

    validator_id: str
    approved: bool
    verdict: str
    signals: list[str]
    hash_verified: bool
    signature_verified: bool
    stake: float
    timestamp: int
    vote_hash: str = ""


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


@dataclass
class ConsensusResult:
    """Aggregated result from the full validator panel."""

    consensus: str  # "APPROVED" | "REJECTED"
    approve_count: int
    reject_count: int
    total_validators: int
    threshold: float  # e.g. 0.667
    votes: list[ValidatorVote] = field(default_factory=list)
    poe_hash: str = ""

    @property
    def approve_ratio(self) -> float:
        if self.total_validators == 0:
            return 0.0
        return self.approve_count / self.total_validators

    @property
    def passed(self) -> bool:
        return self.consensus == "APPROVED"


class ValidatorPanel:
    """
    A panel of N local validators that independently verify a PoE.

    Consensus rule: ≥ threshold fraction must approve (default 2/3).
    """

    CONSENSUS_THRESHOLD = 2 / 3  # 67%

    def __init__(self, n: int = 3, threshold: float | None = None) -> None:
        """
        Parameters
        ----------
        n         : number of validators (default 3)
        threshold : fraction required for approval (default 2/3)
        """
        self.threshold = threshold or self.CONSENSUS_THRESHOLD
        self.validators = [
            Validator(
                validator_id=f"validator_{i + 1}",
                stake=100.0 + i * 25.0,
                reputation=90.0 + i * 2.0,
            )
            for i in range(n)
        ]

    def vote(self, poe_dict: dict) -> ConsensusResult:
        """
        Run all validators against the PoE and compute consensus.

        Parameters
        ----------
        poe_dict : the signed PoE object (from DeterministicPoE.to_dict())

        Returns
        -------
        ConsensusResult
        """
        votes = [v.verify(poe_dict) for v in self.validators]

        approve_count = sum(1 for v in votes if v.approved)
        reject_count = len(votes) - approve_count
        ratio = approve_count / len(votes) if votes else 0.0
        consensus = "APPROVED" if ratio >= self.threshold else "REJECTED"

        return ConsensusResult(
            consensus=consensus,
            approve_count=approve_count,
            reject_count=reject_count,
            total_validators=len(votes),
            threshold=self.threshold,
            votes=votes,
            poe_hash=poe_dict.get("poe_hash", ""),
        )
