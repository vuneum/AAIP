"""
AAIP (Autonomous Agent Interaction Protocol) - Core package.

This package provides the core functionality for autonomous agent interactions,
including payment processing, proof-of-execution, and agent coordination.

Note: This package coexists with the SDK aaip package. When both are in sys.path,
this package takes precedence for submodules (aep, schemas, engine, storage),
while the SDK package provides AAIPClient and related SDK functionality.
"""

import sys

__version__ = "0.1.0"
__author__ = "AAIP Team"

# Import submodules to make them available
from . import aep
from . import schemas
from . import engine
from . import storage

# Re-export commonly used classes from submodules
from .schemas.models import (
    PaymentRequest, ExecutionReceipt, AgentWallet,
    AgentTask, UsageRecord, PoEReference, ValidationResult,
    PaymentStatus, ValidationOutcome, AdapterType
)

# Try to import SDK classes if available (for compatibility)
# These will only be available if sdk/python is in sys.path
try:
    from sdk.python.aaip import (
        AAIPClient, AsyncAAIPClient, AgentManifest, 
        ProofOfExecution, PoETrace, PoETraceStep
    )
    from sdk.python.aaip.models import EvaluationResponse, DiscoveryResult
    __all_sdk__ = [
        "AAIPClient", "AsyncAAIPClient", "AgentManifest",
        "ProofOfExecution", "PoETrace", "PoETraceStep",
        "EvaluationResponse", "DiscoveryResult"
    ]
except ImportError:
    # SDK not available
    __all_sdk__ = []

# Try to import SDK submodules and re-export them
# This allows tests to import aaip.identity, aaip.poe, aaip.validators
try:
    import sdk.python.aaip.identity as identity
    import sdk.python.aaip.poe as poe
    import sdk.python.aaip.validators as validators
    # Make them available as submodules
    sys.modules['aaip.identity'] = identity
    sys.modules['aaip.poe'] = poe
    sys.modules['aaip.validators'] = validators
    # Re-export key classes from these modules
    from sdk.python.aaip.identity import AgentIdentity
    from sdk.python.aaip.poe.deterministic import DeterministicPoE, PoEVerifier
    from sdk.python.aaip.validators import ValidatorPanel
    __all_sdk_submodules__ = ["identity", "poe", "validators", "AgentIdentity", "DeterministicPoE", "PoEVerifier", "ValidatorPanel"]
except ImportError:
    __all_sdk_submodules__ = []

__all__ = [
    "aep",
    "schemas", 
    "engine",
    "storage",
    "PaymentRequest",
    "ExecutionReceipt", 
    "AgentWallet",
    "AgentTask",
    "UsageRecord",
    "PoEReference",
    "ValidationResult",
    "PaymentStatus",
    "ValidationOutcome",
    "AdapterType",
] + __all_sdk__ + __all_sdk_submodules__