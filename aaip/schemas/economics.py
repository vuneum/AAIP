"""
AAIP — Shared Economics Constants
Common economic parameters used by both production and simulation code.
"""

import decimal
from enum import Enum

# Protocol fee constants
PROTOCOL_FEE_RATE = 0.01  # 1% of task value
VALIDATOR_REWARD_FRACTION = 0.002  # 0.2% of task value to validators
FRAUD_PENALTY_MULTIPLIER = 2.0  # fraud detected → lose 2× task value

# Decimal versions for precise calculations
_PROTOCOL_FEE_RATE_DECIMAL = decimal.Decimal(str(PROTOCOL_FEE_RATE))
_VALIDATOR_REWARD_FRACTION_DECIMAL = decimal.Decimal(str(VALIDATOR_REWARD_FRACTION))
_FRAUD_PENALTY_MULTIPLIER_DECIMAL = decimal.Decimal(str(FRAUD_PENALTY_MULTIPLIER))

# Currency defaults
DEFAULT_CURRENCY = "USDC"
SUPPORTED_CURRENCIES = ["USDC", "USDT"]

# Settlement statuses
class SettlementStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"
    DISPUTED = "disputed"
    FRAUD = "fraud"
    REFUNDED = "refunded"


# Ledger entry types
class LedgerEntryType(str, Enum):
    CHARGE = "charge"
    CREDIT = "credit"
    FEE = "fee"
    REFUND = "refund"
    PENALTY = "penalty"
    VALIDATOR_REWARD = "validator_reward"


def calculate_protocol_fee(task_value: float) -> float:
    """Calculate protocol fee for a given task value."""
    # Use Decimal for precise calculations
    task_value_decimal = decimal.Decimal(str(task_value))
    fee_decimal = task_value_decimal * _PROTOCOL_FEE_RATE_DECIMAL
    # Round to 6 decimal places and convert back to float
    return float(fee_decimal.quantize(decimal.Decimal('1e-6'), rounding=decimal.ROUND_HALF_UP))


def calculate_validator_reward(task_value: float) -> float:
    """Calculate validator reward for a given task value."""
    # Use Decimal for precise calculations
    task_value_decimal = decimal.Decimal(str(task_value))
    reward_decimal = task_value_decimal * _VALIDATOR_REWARD_FRACTION_DECIMAL
    # Round to 6 decimal places and convert back to float
    return float(reward_decimal.quantize(decimal.Decimal('1e-6'), rounding=decimal.ROUND_HALF_UP))


def calculate_fraud_penalty(task_value: float) -> float:
    """Calculate fraud penalty for a given task value."""
    # Use Decimal for precise calculations
    task_value_decimal = decimal.Decimal(str(task_value))
    penalty_decimal = task_value_decimal * _FRAUD_PENALTY_MULTIPLIER_DECIMAL
    # Round to 6 decimal places and convert back to float
    return float(penalty_decimal.quantize(decimal.Decimal('1e-6'), rounding=decimal.ROUND_HALF_UP))