# Architecture Decisions

## Decision Log

| Decision | Choice | Alternatives Considered | Rationale |
|---|---|---|---|
| Agent runtime | Letta | LangGraph, Mastra, Hermes, custom | Self-editing memory is the strongest learning mechanism; purpose-built for stateful agents |
| Guardrails | NeMo Guardrails (embedded library) | Guardrails AI, LlamaFirewall, custom | Colang provides dialog-level control beyond I/O filtering; embedding avoids external service dependency |
| Separate project | Yes (standalone repo) | Monorepo subdirectory | Different language (Python vs TypeScript), independent lifecycle, reusability |
| Communication | REST + SSE | gRPC, MCP, WebSocket | REST is simplest for LiteMaaS integration; SSE enables streaming without WebSocket infrastructure |
| Memory store | Letta's embedded PostgreSQL | External pgvector, dedicated vector DB | Letta manages its own state; embedded PG simplifies deployment |
| Memory isolation | Shared core + per-user recall | Per-user agent instances | Core holds anonymized shared knowledge; avoids resource cost of per-user instances |
| Model routing | Configurable: reasoning + guardrails | Single model | Different tasks have different requirements; reasoning needs depth, guardrails needs speed |
| Auth model | JWT pass-through (HS256 for PoC) | Service tokens, mTLS | Reusable across platforms — any JWT-issuing system can integrate |
| Streaming guardrails | Chunked output rails (200/50) + regex pre-filter | Per-chunk full rails, buffer-then-check | NeMo default (200/50) is industry baseline; regex pre-filter catches obvious violations cheaply |
| Admin tools | Role-gated (runtime validation) | Role-aware via persona instructions | Prompt-based enforcement is vulnerable to injection; code-level validation is deterministic |
| User_id injection | Trusted env (`os.getenv`) | LLM function argument, proxy interception | Removes LLM from the security-critical path entirely |
| Service token scoping | Two tokens: user + admin | Single master key | Least-privilege; compromised user token cannot access admin endpoints |
| Rate limiting | Per-user at proxy + memory throttling | No limiting, global limits | Per-user prevents individual abuse; memory throttling addresses poisoning |

## Resolved Design Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Agent identity | Configurable via Letta persona block. No hardcoded name. |
| 2 | Feedback loop | Thumbs up/down per response, stored for admin review. |
| 3 | Admin access | All tools on single agent; admin tools validate `LETTA_USER_ROLE == "admin"` at runtime (defense-in-depth). Admin conversations receive master key; standard conversations only have scoped token. |
| 4 | Memory retention | Persist indefinitely with admin-reviewed pruning. |
| 5 | Conversation history UI | Current session only visible. Past context used via recall memory but not displayed. |
| 6 | Offline mode | Button stays visible but disabled. Shows: "The assistant is currently unavailable." |
| 7 | Output rail chunk sizing | 200 tokens with 50-token sliding window overlap (NeMo default). |
| 8 | Retract UX | Replace unsafe chunks with `...removed...` placeholder. Safety notice at end. |
| 9 | User_id injection | Trusted environment injection. Tools read `os.getenv("LETTA_USER_ID")`. |
| 10 | Service token scoping | Two tokens: `LITELLM_USER_API_KEY` (scoped) + `LITELLM_API_KEY` (master, admin only). |
| 11 | JWT signing | HS256 for PoC. Production should migrate to RS256 asymmetric signing. |
| 12 | Rate limiting | `RATE_LIMIT_RPM` for chat, `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` for memory. |
| 13 | Privacy rule approach | Colang flow with regex + keyword detection, role-aware. Regex catches concrete patterns; intent-based flow catches rephrased attempts. Admin bypass: `user_role == "admin"` skips cross-user check. |
| 14 | Output PII deny-list expansion | Added UUID-4, phone numbers (US), IPv4 addresses, credit card patterns to `_PII_PATTERNS`. |
| 15 | Adversarial test framework | pytest parametrize with categories + conftest fixtures for guardrails engine. Tests organized by attack category. |
| 16 | Red-team test execution | Integration tests against live stack (`podman-compose up`). Marked `@pytest.mark.integration`. |
| 17 | Archival memory isolation | Defer split architecture; strengthen PII audit instead. Per-user tiers require significant Letta API changes. Revisit in Phase 4+. |
| 18 | Helm chart scope | Two-deployment chart with optional subchart mode. No HPA — single replica enforced for credential isolation. |
| 19 | Kustomize overlay strategy | Base + dev + staging overlays. |
| 20 | PII audit hook enforcement | Custom memory tool wrappers with pre-commit PII scan + proxy-side post-commit audit. Wrappers replace Letta's built-in tools via `upsert_from_function()`. |
| 21 | Fail-closed tuning | Output rail chunk overlap tuning via integration benchmarks. Defaults (200/50) kept pending live-stack validation. |
| 22 | Security review format | Markdown document in `docs/architecture/security-review.md`. Living document. |
| 23 | Invariant #1 ↔ #5 tension | Memory wrappers are a second documented POST exception to invariant #1. Distinguished from external API tools — internal memory wrappers POST to Letta API, gated by PII pre-check. |

## Open Questions

1. **Concurrent core memory writes**: Two simultaneous conversations could both trigger `core_memory_append()` on the same block. Does Letta serialize these writes? May require application-level locking.

2. **Tool dependencies in Letta container**: Tools use `httpx` for HTTP calls — verified available in the stock `letta/letta` image during Phase 1.

3. **Per-conversation tool registration**: The security model requires admin tools only on admin conversations. Letta supports per-conversation secrets but not per-conversation tool sets — so all tools are registered on the single shared agent, and admin tools validate role at runtime (defense-in-depth fallback).

4. **Archival memory isolation granularity**: Single shared store with PII-audited writes. Split architecture (shared-RO + per-user-RW) evaluated and deferred — see `docs/architecture/archival-memory-evaluation.md`.

5. **Letta `conversation_search` isolation**: Security depends on search respecting conversation boundaries. Integration tests validate this. Configuration options affecting search scope need investigation.
