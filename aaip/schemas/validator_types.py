"""
AAIP — Shared Validator Types and Constants
Common definitions used by both production and simulation code.
"""

from enum import Enum


class ValidatorBehavior(str, Enum):
    """Validator behavior types used across simulation and production."""
    HONEST      = "honest"
    COLLUDING   = "colluding"   # coordinates with malicious agents for kickback
    LAZY        = "lazy"        # rubber-stamps without checking
    FAULTY      = "faulty"      # offline / intermittent failures


def is_malicious_validator(behavior: ValidatorBehavior) -> bool:
    """Check if a validator behavior is considered malicious."""
    return behavior in (ValidatorBehavior.COLLUDING, ValidatorBehavior.LAZY)


def get_validator_behavior_display_name(behavior: ValidatorBehavior) -> str:
    """Get a human-readable display name for a validator behavior."""
    return {
        ValidatorBehavior.HONEST: "Honest",
        ValidatorBehavior.COLLUDING: "Colluding",
        ValidatorBehavior.LAZY: "Lazy",
        ValidatorBehavior.FAULTY: "Faulty",
    }[behavior]