# Demo Output: AAIP + AEP Two-Agent Integration
Real anchor tx confirmed on Base Sepolia

Run command:
```bash
python demo_two_agent.py --mock --fast
```

Output:
```
03:37:53 INFO    demo: Agent[Requester] id=d2f0577fd7f0ba4f
03:37:53 INFO    demo: Agent[Worker] id=868254654cf9a741
03:37:55 INFO    aaip.aep: {"event": "payment_executed", "ts": 1774060675.9656274, "agent_id": "d2f0577fd7f0ba4f", "recipient": "0x000000000000000000000000000000000000dEaD", "amount": 0.0001, "poe_hash": "0x24eb1d12c166b0e9699435c5e37ee6c73d2c01c64b30a4fe473582caf17814f8", "tx_hash": "0x6c7e90948952240de656ed469fc0ce76efb78fc79eb1f25f402d413f49798120", "status": "success", "latency_ms": 0.06}
03:37:55 INFO    aaip.aep.anchor_chain: OnChainAnchorAdapter ready at 0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94
03:37:59 INFO    aaip.aep.anchor_chain: Anchor OK on-chain: https://sepolia.basescan.org/tx/0xb0db2c7da8fdd7952c0841ff3a727d3414e10a737cd0538570ae0348a44b843a
03:37:59 INFO    aaip.aep: {"event": "proof_anchored", "ts": 1774060679.2019837, "poe_hash": "0x24eb1d12c166b0e9699435c5e37ee6c73d2c01c64b30a4fe473582caf17814f8", "tx_hash": "0x6c7e90948952240de656ed469fc0ce76efb78fc79eb1f25f402d413f49798120", "backend": "base_sepolia", "status": "success"}

================================================================
  AAIP + AEP | Agent Economy Protocol | The Synthesis 2026
================================================================

================================================================
  STEP 1 — Spawn Agents
================================================================
  OK   Agent A (Requester)            d2f0577fd7f0ba4f
  OK   Agent B (Worker)               868254654cf9a741

================================================================
  STEP 2 — Agent B Executes Task
================================================================
  ..   Task                           Analyse Q1 2026 DeFi revenue on Base ecosystem
  OK   PoE hash                       0x24eb1d12c166b0e9699435c5e37ee6c73d...
  OK   Steps                          4
  OK   Signature                      6db507db4c064c8d98c01cc2...
  OK   Elapsed                        1ms

================================================================
  STEP 3 — Validator Consensus (3 validators, >=2/3)
================================================================
  OK  Validator 0  APPROVED
  OK  Validator 1  APPROVED
  OK  Validator 2  APPROVED

  OK   Consensus                      APPROVED (3/3)

================================================================
  STEP 4 — AEP Payment (MOCK)
================================================================
  OK   Payment                        SUCCESS
  OK   TX hash                        0x6c7e90948952240de656ed469fc0ce76efb78fc7
  OK   BaseScan TX                    https://sepolia.basescan.org/tx/0x6c7e90948952240de656ed469fc0ce76efb78fc79eb1f25f402d413f49798120

================================================================
  STEP 5 — PoE Anchored On-Chain
================================================================
  OK   Anchor status                  ON-CHAIN
  OK   BaseScan                       https://sepolia.basescan.org/tx/0x6c7e90948952240de656ed469fc0ce76efb78fc79eb1f25f402d413f49798120
  OK   Contract                       0xE96e10Ee9c7De591b21FdD7269C1739b0451Fe94

================================================================
  SUMMARY
================================================================
  OK   Agent B id                     868254654cf9a741
  OK   PoE hash                       0x24eb1d12c166b0e9699435c5e37ee6c73d...
  OK   Consensus                      APPROVED 3/3
  OK   Payment                        SUCCESS
  OK   On-chain                       YES

  LINK: https://sepolia.basescan.org/tx/0x6c7e90948952240de656ed469fc0ce76efb78fc79eb1f25f402d413f49798120

================================================================
  Demo complete. The agent economy works.
================================================================
```

