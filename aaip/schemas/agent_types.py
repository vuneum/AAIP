"""
AAIP — Shared Agent Types and Constants
Common definitions used by both production and simulation code.
"""

from enum import Enum
from typing import Tuple


class AgentBehavior(str, Enum):
    """Agent behavior types used across simulation and production."""
    HONEST          = "honest"           # performs genuinely, submits real PoE
    LAZY            = "lazy"             # real execution, minimal PoE
    DEGRADING       = "degrading"        # starts strong, quality falls over time
    GAMING          = "gaming"           # optimises for eval metrics, not real quality
    FABRICATOR      = "fabricator"       # fabricates PoE traces
    COLLUDING       = "colluding"        # coordinates with corrupt validators
    SYBIL           = "sybil"            # spins up many identities, thin capability


# Common domains used across the platform
DOMAINS = [
    "coding", "finance", "general", "translation", 
    "summarization", "data_analysis", "research"
]

# Quality profiles for different agent behaviors (mean, std)
# Used primarily in simulation but defined here for consistency
QUALITY_PROFILE: dict[AgentBehavior, Tuple[float, float]] = {
    AgentBehavior.HONEST:     (82.0, 8.0),   # mean, std of true quality
    AgentBehavior.LAZY:       (70.0, 12.0),
    AgentBehavior.DEGRADING:  (85.0, 5.0),   # degrades over time
    AgentBehavior.GAMING:     (75.0, 6.0),   # good on eval, weaker in CAV
    AgentBehavior.FABRICATOR: (40.0, 15.0),  # poor real quality, fakes PoE
    AgentBehavior.COLLUDING:  (55.0, 10.0),  # relies on corrupt validators
    AgentBehavior.SYBIL:      (50.0, 20.0),  # high variance, thin coverage
}


def is_malicious_behavior(behavior: AgentBehavior) -> bool:
    """Check if an agent behavior is considered malicious."""
    return behavior not in (AgentBehavior.HONEST, AgentBehavior.LAZY)


def get_behavior_display_name(behavior: AgentBehavior) -> str:
    """Get a human-readable display name for an agent behavior."""
    return {
        AgentBehavior.HONEST: "Honest",
        AgentBehavior.LAZY: "Lazy",
        AgentBehavior.DEGRADING: "Degrading",
        AgentBehavior.GAMING: "Gaming",
        AgentBehavior.FABRICATOR: "Fabricator",
        AgentBehavior.COLLUDING: "Colluding",
        AgentBehavior.SYBIL: "Sybil",
    }[behavior]