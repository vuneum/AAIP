# Changelog

All notable changes to AAIP are documented here.
Format: [Semantic Versioning](https://semver.org)

---

## [1.0.3] — 2025-03-12

### Fixed
- **ed25519 pure-Python fallback** — Previous implementation had incorrect Edwards curve `d` constant
  and hardcoded base point values. Rewrote to RFC 8032 §5.1 spec: `d` and base point `B` now
  derived at import time. Sign/verify now passes all test vectors including cross-identity rejection.
- **PoEVerifier signature check** — Now uses corrected pure-Python `_ed25519_verify` when
  `cryptography` package is not installed (previously trusted hash check only as fallback).
- **CLI version** — `aaip --version` now reads dynamically from `aaip.__version__` (single source of truth).

### Added
- `backend/pyproject.toml` — Backend now installable with `pip install -e .`
- Backend setup section in README with Docker and manual instructions
- `PRs Welcome` badge in README
- `.gitignore` — Added `.aaip-identity.json` explicit entry with comment warning

### Changed
- `SPEC.md` at root is now a pointer to `docs/aaip-spec.md` (canonical spec, eliminates duplication)

---

## [1.0.0] — 2025-03-01

### Added — Protocol
- Agent identity standard via `.aaip.json` manifest
- Global capability registry + discovery engine
- Multi-model AI jury evaluation (2–3 models, consensus scoring with confidence intervals)
- Proof of Execution (PoE) trace layer with SHA-256 hash verification
- Fraud detection on execution traces (7 heuristic signals)
- Reputation timeline system with rolling averages
- Open capability domains — any tag, not hardcoded enum

### Added — Auth
- API key generation (`aaip_<id>_<secret>` format)
- SHA-256 key hashing — full key never stored
- Per-key rate limiting (1000 req/hour default)
- IP-based rate limiting for unauthenticated requests (100/hour)
- Audit log for every API request
- Key revocation endpoint

### Added — Backend
- `POST /traces/submit` — PoE trace submission with verification
- `GET /traces/{id}/verify` — trace verification endpoint
- `GET /agents/{id}/badge` — shield.io-compatible badge data
- `POST /agents/{id}/manifest/update` — manifest update endpoint
- `POST /payments/quote` — payment quote generation
- `POST /payments/verify` — on-chain payment verification
- `POST /tasks/execute-paid` — payment-gated task execution
- `POST /wallets/connect` — wallet registration
- `GET /agents/{id}/balance` — internal ledger balance
- `GET /payments/chains` — supported blockchain networks
- `POST /keys`, `GET /keys`, `DELETE /keys/{id}` — API key management
- Open `/domains` endpoint — dynamic from DB, not hardcoded

### Added — SDKs
- Python SDK (`pip install aaip`) — async + sync clients, typed models
- TypeScript/JavaScript SDK (`npm install aaip`) — ESM + CJS
- Go SDK (`go get github.com/aaip-protocol/aaip-go`) — stdlib only
- Rust SDK (`cargo add aaip`) — async with tokio
- Java SDK — Java 17+, no external HTTP deps (uses java.net.http)

### Added — Framework Adapters
- LangChain adapter — auto-traces AgentExecutor and Runnable
- CrewAI adapter — auto-extracts capabilities from agent roles
- OpenAI Agents SDK adapter — compatible with Swarm successor
- AutoGPT adapter — record_task() and wrap_run() patterns

### Added — CLI
- `aaip init` — generate `.aaip.json` manifest interactively
- `aaip register` — register with AAIP network
- `aaip demo` — 5-agent economy demo with colorised terminal output
- `aaip discover` — search agents by capability
- `aaip evaluate` — submit output for jury evaluation
- `aaip status` — agent score and reputation
- `aaip doctor` — config validation and health check
- `aaip leaderboard` — global rankings
- `aaip wallet` — payment wallet management

### Added — Infrastructure
- Alembic database migrations (8 new tables)
- GitHub Actions CI — Python, TypeScript, Go, Rust, Java, Docker build
- PyPI + npm publish on tag
- Docker Compose with AAIP naming throughout

### Fixed
- Removed `agent_identity.py` (AAIP does not create agents)
- Removed `evaluation_replay.py` (superseded by DB trace system)
- Removed `judge_reliability.py` (superseded by custom_judges + DB)
- All `arpp` naming replaced with `aaip` across docker, frontend, env vars
- Hardcoded `coding|finance|general` domain enum replaced with open tags

---

## [0.9.0] — 2025-01-15 (Internal MVP)

- Initial AAIP MVP with FastAPI backend
- Multi-model jury evaluation pipeline
- Basic reputation timeline
- PostgreSQL + Celery + Redis infrastructure
- Python SDK skeleton
- Next.js dashboard

---

## [1.1.0] — 2025-03-10

### Added — CAV (Continuous Agent Verification)
- `backend/cav.py` — randomised hidden benchmark auditing
- Hourly Celery beat schedule, 24hr cooldown per agent
- 7 CAV benchmark task sets (coding, finance, general, translation, summarization)
- Deviation-triggered reputation blend (threshold: 10 pts, weight: 0.3)
- `GET /cav/agents/{id}/status`, `GET /cav/agents/{id}/history`
- `POST /cav/trigger` (manual), `POST /cav/agents/{id}/audit` (single agent)
- Migration `0002_cav_shadow.py` — `cav_runs` table

### Added — Shadow Mode
- `backend/shadow.py` — full pipeline simulation, nothing written to live stats
- Real PoE verification + real jury scoring (flagged `is_shadow=True`)
- 30% CAV trigger simulation, payment gate check, reputation delta preview
- `ShadowReport` with `issues[]`, `recommendations[]`, `production_ready`
- `POST /shadow/sessions`, `POST /shadow/sessions/{id}/run`
- `GET /shadow/sessions/{id}`, `GET /shadow/sessions/{id}/report`
- Migration `0002_cav_shadow.py` — `shadow_sessions` table

### Fixed — Naming
- Unified all references to **AAIP — Autonomous Agent Infrastructure Protocol**
- Removed all `ARPP`, `arpp`, "Agent Identity Protocol", "Agent Reliability Protocol" references
- `discovery.py` — `ALLOWED_DOMAINS` enum removed, open tags, `generate_aaip_agent_id` import fixed
- `discovery.py` — manifest paths updated to `/.well-known/aaip-agent.json` (legacy `arpp-agent.json` kept for compat)
- `tasks.py` — Celery app renamed `aaip`, beat schedule added
- `frontend/src/lib/api.ts` — fully rewritten, all `arpp_agent_id` → `aaip_agent_id`, all new endpoints added

### Added — Docs
- `docs/ARCHITECTURE.md` — full protocol stack diagram, layer detail, validator architecture (v3)
- `docs/PAYMENTS.md` — v1/v2/v3 roadmap, what is and isn't built
- `docs/POE.md` — v1/v2/v3 versioning, fraud signals, trace schema
- `README.md` — rewritten with protocol stack diagram, end-to-end workflow, Shadow Mode guide, versioned feature tables
- `docs/ROADMAP.md` — rewritten with v1/v2/v3/v4 milestones, "What We Won't Build" section
