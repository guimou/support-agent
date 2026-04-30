# Project Plan — LiteMaaS AI Agent Assistant

> **Status**: Active
> **Created**: 2026-04-27
> **Architecture**: [Architecture Overview](../architecture/overview.md) | [Security](../architecture/security.md) | [Memory](../architecture/memory-and-learning.md)
> **Reference**: [Modules](../reference/modules.md) | [Configuration](../reference/configuration.md) | [API](../reference/api.md) | [Tools](../reference/tools.md)

---

## Overview

Build a standalone AI agent that serves as a platform support assistant for LiteMaaS. Two-container architecture (FastAPI proxy + Letta runtime) with NeMo Guardrails, JWT auth, and SSE streaming.

This plan is organized into phases that build on each other. Each phase produces a working, testable increment.

---

## Phase 0 — Project Scaffolding ✅

**Status**: Complete (2026-04-28)

**Goal**: Bootable project with dev environment, CI, and empty module structure.

**Deliverables**:
- Python project setup (`pyproject.toml`, dependencies, linting/formatting config)
- Source tree matching the target structure (`src/agent/`, `src/tools/`, `src/guardrails/`, `src/proxy/`, `src/adapters/`)
- Test scaffolding (`tests/unit/`, `tests/integration/`, `tests/guardrails/`)
- `Containerfile` (multi-stage build for the proxy container)
- `compose.yaml` for local dev (proxy + Letta containers)
- `.env.example` with all required environment variables
- CI pipeline (lint, type check, unit tests)
- Scripts directory (`scripts/seed-knowledge.py`, `scripts/export-knowledge.py` — stubs)

**Validation**: `podman-compose up` starts both containers; proxy returns 200 on `/v1/health`.

---

## Phase 1 — Foundation ✅

**Status**: Complete (2026-04-28)

**Goal**: Agent answers questions using real tools, with auth and basic guardrails. End-to-end flow works via API (no UI yet).

### 1A — Letta Agent Setup
- Connect to Letta runtime via SDK
- Bootstrap agent with persona, knowledge, and patterns memory blocks
- Seed archival memory with initial LiteMaaS documentation
- Validate open questions: concurrent memory writes, tool dependencies (`httpx` availability), per-conversation tool sets, `conversation_search` isolation

### 1B — Read-Only Tools
- LiteMaaS tools: `list_models`, `check_subscription`, `get_user_api_keys`, `get_usage_stats`
- LiteLLM tools: `check_model_health`, `get_model_info`, `check_rate_limits`
- Documentation search tool: `search_docs`
- Trusted `user_id` injection — tools read `os.getenv("LETTA_USER_ID")`, never from LLM args
- Scoped service tokens: `LITELLM_USER_API_KEY` for standard tools

### 1C — Proxy Server
- FastAPI proxy with JWT validation (HS256)
- `/v1/chat` endpoint (non-streaming)
- `/v1/health` endpoint
- User context extraction and injection into Letta conversation environment
- Basic request/response logging (structured JSON, no message content)

### 1D — Basic Guardrails
- NeMo Guardrails embedded as Python library
- Input rails: topic control, basic prompt injection detection
- Output rails: basic safety check (non-streaming for now)
- Guardrails model configuration via LiteLLM

### 1E — Security Foundations
- Role-gated tool registration (admin tools only on admin conversations)
- Per-conversation secrets injection (`LETTA_USER_ID`, `LETTA_USER_ROLE`)
- Recall memory isolation integration tests
- PII audit hook on memory write operations

**Validation**: Send a JWT-authenticated request to `/v1/chat` asking "Why can't I access gpt-4o?" — agent calls `check_subscription`, returns a scoped answer. Off-topic questions are refused.

---

## Phase 2 — Streaming & Integration

**Goal**: SSE streaming works end-to-end. LiteMaaS backend proxies to agent. Frontend widget is functional.

### 2A — SSE Streaming
- `/v1/chat/stream` endpoint with POST-based SSE
- Two-layer output guardrails: regex pre-filter + NeMo chunked evaluation
- Retract mechanism for unsafe chunks
- Chunk indexing for retract UX

### 2B — LiteMaaS Backend Integration
- New proxy route in LiteMaaS backend (`/api/v1/assistant/*`)
- JWT pass-through to agent container
- Feature flag via `AGENT_URL` env var
- Health check proxy endpoint

### 2C — Frontend Widget
- PatternFly 6 floating panel using `@patternfly/chatbot`
- SSE streaming with custom protocol handling (chunk, retract_chunk, done)
- Offline/unavailable state (disabled button with message)
- Thumbs up/down feedback per response
- Internationalization keys

### 2D — Admin Tools & Rate Limiting
- Admin tools: `get_global_usage_stats`, `lookup_user_subscriptions`
- Tool-level role validation (defense-in-depth)
- Admin service token injection (`LITELLM_API_KEY` only in admin conversations)
- Per-user rate limiting at proxy (`RATE_LIMIT_RPM`)
- Memory write throttling (`RATE_LIMIT_MEMORY_WRITES_PER_HOUR`)

### 2E — Phase 1 Carryover (from implementation review)
- **Guardrails strictness enforcement**: When `guardrails_required=true`, the server must refuse to start (not fall back to no guardrails). Review the fail-open path for non-strict deployments and document the security implications.
- **`_is_blocked` heuristic robustness**: Replace the string-matching heuristic in `GuardrailsEngine._is_blocked()` with explicit policy result semantics from NeMo's response structure. The current short refusal-phrase list may produce false negatives.

**Validation**: User interacts with the assistant widget in the LiteMaaS UI. Streaming responses appear incrementally. Unsafe content is retracted in real-time. Admin-only tools are inaccessible to regular users.

---

## Phase 3 — Safety & Privacy Hardening

**Goal**: Guardrails are battle-tested. Privacy isolation is verified. System is ready for staging deployment.

### 3A — Privacy Rails
- Colang privacy rules for cross-user data isolation
- PII detection in output rails with deny-list patterns
- Fail-closed guardrail defaults (uncertain = refuse)
- Output rail chunk size and overlap tuning

### 3B — Guardrail Test Suite
- Adversarial prompt test scenarios (injection, jailbreak, encoding tricks)
- Cross-user probing scenarios
- Multi-turn manipulation scenarios
- Indirect probing patterns
- CI integration for guardrail tests

### 3C — Security Testing
- Red-team testing: `user_id` spoofing, admin tool invocation, memory exfiltration
- Penetration testing on proxy endpoints
- Evaluate archival memory isolation architecture (shared vs per-user tiers)
- Security review document

### 3D — Deployment
- Helm chart for Kubernetes/OpenShift deployment
- Kustomize overlay for environment-specific config
- Integration as subchart of LiteMaaS Helm chart
- Volume configuration for Letta data persistence

**Validation**: Guardrail test suite passes in CI. Red-team exercises produce no unmitigated vulnerabilities. Helm chart deploys successfully to staging.

---

## Phase 4 — Observability & Learning

**Goal**: Production-ready observability. Agent learning loop is monitored and manageable.

### 4A — Observability
- Structured logging across all components
- Prometheus metrics (requests, blocks, latency, tool calls, memory writes, token usage)
- Guardrail decision metrics (allow/block/retract by rail type)
- Health check enrichment (Letta status, guardrails status)

### 4B — Admin Dashboard
- Admin endpoints: `/admin/memory/core`, `/admin/memory/archival`, `/admin/memory/stats`
- Guardrail statistics endpoint: `/admin/guardrails/stats`
- Memory review workflow with periodic pruning prompts

### 4C — Knowledge Pipeline
- `seed-knowledge.py` — load documentation and FAQ into archival memory
- `export-knowledge.py` — export learned knowledge for human review
- Process for seeding release notes and known issues

### 4D — Agent Tuning
- Analyze thumbs up/down feedback patterns
- Tune agent persona based on real interactions
- Monitor memory evolution and shared knowledge quality
- Monitor guardrail block rate anomalies per user
- Review scoped service token permissions as tools are added

**Validation**: Grafana dashboard shows agent metrics. Admin can review and prune agent memory. Knowledge seeding pipeline runs successfully.

---

## Dependencies & Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Letta doesn't support per-conversation tool sets | Admin tool isolation relies on fallback (tool-level role check only) | Validate in Phase 1A; design fallback with per-role agent instances if needed |
| Letta doesn't support per-conversation secrets | `user_id` injection mechanism needs alternative approach | Validate in Phase 1A; fallback to tool-call interception or sandbox wrapper |
| `httpx` not in stock Letta image | Tools need alternative HTTP library or custom image | Check in Phase 1A; fallback to `urllib` or custom Letta image |
| NeMo Guardrails latency too high for streaming | Output rail evaluation may add unacceptable delay | Tune chunk size/overlap in Phase 3A; fast regex pre-filter absorbs most load |
| `conversation_search` not conversation-scoped | Cross-user data could leak via recall memory | Validate in Phase 1A with integration tests; escalate to Letta team if broken |

---

## External Dependencies

| System | What we need | Owner |
|---|---|---|
| **LiteMaaS Backend** | New `/api/v1/assistant/*` proxy route, `AGENT_URL` env var | LiteMaaS team (Phase 2B) |
| **LiteMaaS Frontend** | Assistant widget integration, floating panel | LiteMaaS team (Phase 2C) |
| **LiteLLM** | Reasoning model + guardrails model configured and accessible | Platform team |
| **Letta** | Stable API for conversations, tool registration, secrets | Upstream (off-the-shelf image) |
| **Container Registry** | Image hosting for agent proxy container | DevOps |

---

## Phase Summary

| Phase | Focus | Depends On |
|---|---|---|
| **0 — Scaffolding** ✅ | Project setup, dev environment | Nothing |
| **1 — Foundation** ✅ | Agent + tools + auth + basic guardrails | Phase 0, Letta image, LiteLLM models |
| **2 — Integration** | Streaming, frontend widget, admin tools | Phase 1, LiteMaaS backend/frontend changes |
| **3 — Hardening** | Privacy rails, security testing, deployment | Phase 2 |
| **4 — Observability** | Metrics, admin dashboard, learning pipeline | Phase 3 |
