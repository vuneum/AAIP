# AAIP Protocol Roadmap
## Autonomous Agent Infrastructure Protocol

---

## Protocol Vision

AAIP does not build AI agents.

AAIP provides the infrastructure layer that makes agents composable, trustworthy, and economically viable — the same way TCP/IP made computers interoperable without owning them.

**What AAIP enables:**
- Agents discovering each other across frameworks and providers
- Cryptographic proof that an agent genuinely performed work
- Independent multi-model scoring of agent output quality
- Rolling reputation built from verified task completions
- Stablecoin settlement between agents with escrow protection

---

## AAIP v1 — Foundation ✅ Current

**Identity & Registry**
- [x] `.aaip.json` manifest standard — open capability tags, no hardcoded enum
- [x] Global agent registry + discovery engine
- [x] Capability search by domain, tag, min_reputation
- [x] Auto-crawl via `/.well-known/aaip-agent.json`

**Proof of Execution — v1**
- [x] Structured execution traces (tool calls, reasoning, LLM calls, API calls)
- [x] SHA-256 hash chain — tamper-evident, privacy-preserving
- [x] 7-signal fraud detection (invalid timestamps, out-of-order steps, count mismatch...)
- [x] Server-side hash recomputation and verification

**AI Jury**
- [x] 2–3 independent model evaluation with consensus scoring
- [x] Confidence intervals + agreement level
- [x] Custom judge support
- [x] Async job queue for large evaluations

**Continuous Agent Verification (CAV) — v1**
- [x] Random hidden benchmark tasks dispatched hourly
- [x] Expected vs observed score comparison
- [x] Deviation threshold — reputation adjusted when drift exceeds 10 pts
- [x] 24-hour cooldown per agent, weighted toward inactive agents
- [x] Per-agent CAV history and pass rate

**Reputation System**
- [x] Rolling score from verified task completions
- [x] 30-day timeline with trend detection
- [x] Shield.io-compatible badge embed

**Shadow Mode**
- [x] Full pipeline simulation — PoE, jury, CAV, payment, reputation delta
- [x] Nothing written to live agent stats
- [x] Detailed developer report with `issues[]`, `recommendations[]`, `production_ready`
- [x] Session expiry + cleanup

**Payments — v1**
- [x] Internal ledger (quote / verify / charge / credit / refund)
- [x] Wallet registration (external wallets — Base, Ethereum, Tron, Solana)
- [x] Quote API with 15-minute expiry
- [x] On-chain payment verification (hash format validation; RPC integration in v2)
- [x] Payment-gated task execution
- [x] Shadow mode payment simulation

**SDKs**
- [x] Python (pip install aaip) — async + sync, typed models, CLI
- [x] TypeScript/JavaScript (npm install aaip) — ESM + CJS
- [x] Go (stdlib only)
- [x] Rust (tokio async)
- [x] Java 17+ (java.net.http, no external deps)

**Framework Adapters**
- [x] LangChain (AgentExecutor, Chain, Runnable)
- [x] CrewAI
- [x] OpenAI Agents SDK
- [x] AutoGPT

**Infrastructure**
- [x] API key auth + SHA-256 hashing (full key never stored)
- [x] Per-key rate limiting + IP-based fallback
- [x] Audit log for every request
- [x] Alembic database migrations (2 migration files, 10 tables)
- [x] GitHub Actions CI — Python, TS, Go, Rust, Java, Docker
- [x] Auto-publish to PyPI + npm on git tag

---

## AAIP v2 — Trust Layer 🔜 Planned

**Proof of Execution — v2**
- [ ] Signed execution receipts — agent signs trace with private key
- [ ] API call receipts — third-party API responses included as evidence
- [ ] Receipt chaining — each step references previous step hash
- [ ] Selective disclosure — share proof without revealing raw inputs
- [ ] Stronger audit trail for dispute resolution

**CAV — v2**
- [ ] Risk-based audit frequency — higher-value agents audited more often
- [ ] Adaptive benchmarking — difficulty scales with agent reputation
- [ ] Domain-specific test sets per capability (not just coding/finance/general)
- [ ] CAV score included as signal in jury evaluation
- [ ] Flagged agent quarantine (auto-derank on repeated CAV failures)

**Reputation — v2**
- [ ] Stake-weighted reputation (agents can stake tokens on their score)
- [ ] Time-decay weighting (recent evals weighted higher)
- [ ] Cross-domain reputation profiles
- [ ] Reputation portability (agent moves frameworks, keeps score)

**Payments — v2**
- [ ] Decentralised escrow smart contract (Base chain first)
- [ ] Dispute resolution state machine (open → evidence → resolved)
- [ ] Validator-triggered settlement
- [ ] Stablecoin finality confirmation via chain RPC
- [ ] `aaip wallet` CLI full flow

**Infrastructure**
- [ ] Webhook support (score change, CAV fail, payment confirmed)
- [ ] Role-based access control (admin / evaluator / readonly)
- [ ] Public leaderboard UI (standalone page)
- [ ] Manifest validator endpoint
- [ ] LlamaIndex, Haystack, Autogen, DSPy adapters
- [ ] Java SDK on Maven Central

---

## AAIP v3 — Decentralised Validation 📋 Planned

**Validator Network**
- [ ] Permissioned validator set — run deterministic PoE checks
- [ ] Validators sign validation results with threshold signatures
- [ ] Validator staking — stake required to join set
- [ ] Slashing — provably incorrect validation loses stake
- [ ] VRF-based validator selection per evaluation

**Watcher Network**
- [ ] Watchers monitor validator behaviour
- [ ] Fraud proof submission
- [ ] Watcher rewards for catching misbehaving validators

**Payments — v3**
- [ ] Cross-chain escrow (bridge integration)
- [ ] Batch settlement — aggregate micro-payments into single on-chain tx
- [ ] Validator fee distribution from payment flow

**PoE — v3**
- [ ] TEE-backed execution attestation (Intel TDX / AWS Nitro)
- [ ] Privacy-preserving proofs — prove work without revealing inputs
- [ ] Optional ZK verification (zkVM integration research)

---

## AAIP v4 — Agent Economy 🔭 Future

- [ ] Validator marketplace — open competition for validation slots
- [ ] Agent bidding — agents compete on price + reputation for tasks
- [ ] Privacy-preserving execution proofs at scale
- [ ] Autonomous agent hiring pipelines (agent hires agents hires agents)
- [ ] Protocol governance — AAIP improvement proposals (AIPs)
- [ ] Global agent economy infrastructure — protocol-level composability

---

## What We Won't Build

AAIP is infrastructure. We will not build:

- AI agents (we give them identity, not cognition)
- Agent hosting or compute (use any cloud)
- Proprietary judge models (all jury models are third-party, declared)
- Walled gardens (all SDKs open source, all specs public)

---

*Last updated: v1.0.0*
