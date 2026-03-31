"""
AAIP Simulation Lab — Economics
Escrow settlement, fee collection, ledger accounting, protocol revenue.
Mirrors backend/payments.py logic without real blockchain calls.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from aaip.schemas.economics import (
    VALIDATOR_REWARD_FRACTION, 
    FRAUD_PENALTY_MULTIPLIER,
    DEFAULT_CURRENCY,
    LedgerEntryType,
    calculate_validator_reward,
    calculate_fraud_penalty
)
from .core import SimState
from .agents import SimAgent
from .tasks import SimTask, TaskStatus
from .validation import ConsensusResult


@dataclass
class LedgerEntry:
    entry_id:   str
    agent_id:   str
    entry_type: LedgerEntryType   # charge|credit|fee|refund|penalty|validator_reward
    amount:     float
    currency:   str   = DEFAULT_CURRENCY
    task_id:    Optional[str] = None
    tick:       int   = 0


@dataclass
class SettlementResult:
    task_id:         str
    settled:         bool
    executor_credit: float
    requester_charge:float
    protocol_fee:    float
    validator_reward:float
    disputed:        bool
    fraud_penalty:   float = 0.0


class EscrowEngine:
    """
    Simulates the AAIP internal ledger and escrow settlement.

    Flow:
      1. Task created  → requester escrow charged
      2. Task validated → executor credited, fee taken, validators rewarded
      3. Fraud detected → executor penalised, requester refunded
      4. Dispute raised → delayed settlement, resolution applied
    """

    # Constants imported from aaip.schemas.economics
    VALIDATOR_REWARD_FRACTION = VALIDATOR_REWARD_FRACTION   # 0.2% of task value to validators
    FRAUD_PENALTY_MULTIPLIER  = FRAUD_PENALTY_MULTIPLIER    # fraud detected → lose 2× task value

    def charge_escrow(self, task: SimTask, agent: SimAgent, state: SimState) -> None:
        """Deduct task value from requester at task creation."""
        entry = LedgerEntry(
            entry_id   = f"ledger_{state.uid()}",
            agent_id   = task.requester_id,
            entry_type = LedgerEntryType.CHARGE,
            amount     = -task.value,
            task_id    = task.task_id,
            tick       = state.clock.ticks,
        )
        state.ledger[task.requester_id].append(entry)
        state.inc("total_escrow_charged", task.value)

    def settle_task(
        self,
        task:      SimTask,
        consensus: ConsensusResult,
        state:     SimState,
    ) -> SettlementResult:
        cfg       = state.config
        executor  = state.agents.get(task.executor_id)
        requester = state.agents.get(task.requester_id)

        protocol_fee     = round(task.escrow_fee, 6)
        validator_reward = calculate_validator_reward(task.value)
        fraud_penalty    = 0.0
        disputed         = False

        if consensus.fraud_detected:
            # Fraud: refund requester, penalise executor
            fraud_penalty = calculate_fraud_penalty(task.value)
            executor_credit = 0.0
            requester_refund = task.value

            self._add_entry(state, task.requester_id, LedgerEntryType.REFUND,
                            +requester_refund, task.task_id)
            self._add_entry(state, task.executor_id, LedgerEntryType.PENALTY,
                            -fraud_penalty, task.task_id)
            if executor:
                executor.earnings = max(0.0, executor.earnings - fraud_penalty * 0.1)
            state.inc("fraud_penalties_collected", fraud_penalty)
            state.inc("tasks_fraud_settled")
        else:
            # Clean settlement
            executor_credit  = round(task.value - protocol_fee - validator_reward, 6)
            requester_refund = 0.0

            # Check for dispute (random base probability)
            if state.bernoulli(cfg.dispute_probability_base):
                disputed = True
                task.disputed = True
                state.inc("disputes_raised")
                # Dispute delays settlement — credit after resolution
                executor_credit = round(executor_credit * 0.9, 6)  # 10% held in dispute

            self._add_entry(state, task.executor_id, LedgerEntryType.CREDIT,
                            +executor_credit, task.task_id)
            if executor:
                executor.earnings += executor_credit
            state.inc("tasks_clean_settled")

        # Protocol fee always collected
        self._add_entry(state, "protocol", LedgerEntryType.FEE, +protocol_fee, task.task_id)
        state.inc("protocol_fee_revenue", protocol_fee)

        # Distribute validator reward
        self._distribute_validator_rewards(validator_reward, consensus, state, task.task_id)

        task.settled  = True
        task.disputed = disputed
        task.status   = TaskStatus.COMPLETED

        return SettlementResult(
            task_id          = task.task_id,
            settled          = True,
            executor_credit  = executor_credit if not consensus.fraud_detected else 0.0,
            requester_charge = task.value,
            protocol_fee     = protocol_fee,
            validator_reward = validator_reward,
            disputed         = disputed,
            fraud_penalty    = fraud_penalty,
        )

    def _add_entry(self, state, agent_id, entry_type, amount, task_id):
        entry = LedgerEntry(
            entry_id   = f"ledger_{state.uid()}",
            agent_id   = agent_id,
            entry_type = entry_type,
            amount     = amount,
            task_id    = task_id,
            tick       = state.clock.ticks,
        )
        state.ledger[agent_id].append(entry)

    def _distribute_validator_rewards(self, total_reward, consensus, state, task_id):
        voters = list(consensus.validator_votes.keys())
        if not voters:
            return
        per_validator = round(total_reward / len(voters), 6)
        for vid in voters:
            validator = state.validators.get(vid)
            if validator:
                validator.rewards_earned += per_validator
            self._add_entry(state, vid, LedgerEntryType.VALIDATOR_REWARD, +per_validator, task_id)
        state.inc("validator_rewards_paid", total_reward)

    def protocol_balance(self, state: SimState) -> float:
        """Total protocol fee revenue accumulated."""
        return sum(
            e.amount for e in state.ledger.get("protocol", [])
            if e.entry_type == "fee"
        )

    def agent_balance(self, agent_id: str, state: SimState) -> float:
        return sum(e.amount for e in state.ledger.get(agent_id, []))

    def total_value_settled(self, state: SimState) -> float:
        return round(state.counters.get("total_escrow_charged", 0.0), 4)
