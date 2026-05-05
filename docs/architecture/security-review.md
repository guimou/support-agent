# Security Review — LiteMaaS Agent Assistant

**Review period**: Phase 1–3 implementation  
**Review date**: 2026-05-02  
**Status**: Living document — updated as testing is performed

---

## Scope

This review covers the Phase 1–3 implementation of the LiteMaaS Agent Assistant:

- **Proxy container** (port 8400): FastAPI application providing JWT authentication, NeMo Guardrails (input + output rails), SSE streaming, per-user rate limiting, and conversation ownership enforcement.
- **Letta container** (port 8283): Off-the-shelf Letta agent runtime providing reasoning, tool execution, and three-tier memory (core, recall, archival).

**Tested against**:
- Authentication bypass and token manipulation (`TestRedTeamProxyEndpoints`)
- User identity spoofing via JWT and message payload (`TestRedTeamUserIdSpoofing`)
- Admin privilege escalation via prompt engineering (`TestRedTeamAdminToolAccess`)
- Memory exfiltration via prompt injection (`TestRedTeamMemoryExfiltration`)
- Guardrail bypass via injection, jailbreak, encoding, cross-user probing, and multi-turn manipulation (`tests/guardrails/`)
- Source-level invariant verification (`tests/unit/test_security_invariants.py`)

**Out of scope**: Network-level attacks, Letta runtime internals, LiteLLM proxy security, infrastructure-level threats (cluster, container escape).

---

## Threat Model

### Threat Actors

| Actor | Capability | Entry Point |
|---|---|---|
| **Authenticated malicious user** | Valid JWT, knowledge of API surface, crafted prompts | `/v1/chat`, `/v1/chat/stream` |
| **Unauthenticated attacker** | No credentials; can probe public endpoints | `/v1/chat`, `/v1/chat/stream`, `/v1/health` |
| **Compromised regular token** | `LITELLM_USER_API_KEY` exposed | LiteLLM API (out-of-scope for proxy) |

### Attack Surface

| Surface | Description | Guard |
|---|---|---|
| **Proxy endpoints** | `/v1/chat`, `/v1/chat/stream` accept user messages and conversation IDs | JWT auth + input validation (Pydantic) |
| **JWT authentication** | HS256 token with userId, username, email, roles claims | Signature validation + expiry check in `validate_jwt()` |
| **Guardrails bypass** | Prompt injection, jailbreak, encoding tricks to reach LLM without filtering | NeMo input rails (Llama Guard + topic classifier + regex) |
| **Memory access** | Cross-user archival search, core memory dump, PII-loaded memory writes | PII pre-commit wrappers + output rails + rate limiting |
| **Admin tool access** | Prompt-based role escalation, claiming admin identity in message | Invariant #3 runtime role check in tool code |
| **Conversation spoofing** | Providing another user's conversation_id to access their history | Ownership check in `validate_conversation_ownership()` |

### Trust Boundaries

```
UNTRUSTED                      LLM-CONTROLLED              HARD ENFORCEMENT
─────────────                  ──────────────              ────────────────
User input (HTTP)    ──[input rails]──>  Agent reasoning  ──[code]──>  Tools (role check,
                                         Memory ops                    read-only, user_id
Agent response (HTTP) <──[output rails]──  LLM output                  from env)
```

**Key principle**: The LLM is never the last line of defense. Security-critical values (user_id, user_role, token scoping) are enforced in deterministic code outside the LLM's control.

---

## Security Invariant Verification

All six invariants from [SECURITY.md](../../SECURITY.md) are verified below.

| # | Invariant | Status | Evidence |
|---|---|---|---|
| 1 | **Tools are read-only** — external API tools use `httpx.get()` only; one POST exception for `get_global_usage_stats` (read-only analytics); memory wrappers use `httpx.post()` to Letta internal API only (PII-gated, invariant #5 enforcement) | **Verified** | `test_security_invariants.py::TestInvariant1ReadOnly` — source inspection of all tools; `TestInvariant1MemoryWrappers` verifies POST is gated by PII check |
| 2 | **`user_id` comes from JWT, never from LLM** — tools read `os.getenv("LETTA_USER_ID")`, never accept `user_id` as a parameter | **Verified** | `test_security_invariants.py::TestInvariant2UserIdFromEnv` — source inspection confirms no `user_id` parameter; red-team `TestRedTeamUserIdSpoofing::test_jwt_user_id_cannot_be_overridden_by_message` validates at runtime |
| 3 | **Admin tools are role-gated** — all tools on single shared agent; admin tools validate `LETTA_USER_ROLE == "admin"` at runtime | **Verified** | `test_security_invariants.py::TestInvariant3AdminRoleCheck` — source inspection of admin tools; red-team `TestRedTeamAdminToolAccess` validates at runtime |
| 4 | **Scoped tokens** — standard tools use `LITELLM_USER_API_KEY`; admin tools use `LITELLM_API_KEY` | **Verified** | `test_security_invariants.py::TestInvariant4ScopedTokens` — source inspection confirms correct token usage by tool category |
| 5 | **Memory writes are PII-audited** — custom `core_memory_append`, `core_memory_replace`, `archival_memory_insert` wrappers run PII regex before calling Letta memory API; blocked content never reaches storage | **Verified** | `test_memory_tools.py::TestMemoryToolPiiBlocking` — unit tests confirm PII in content returns BLOCKED without API call; `test_security_invariants.py::TestInvariant5MemoryWritePiiAudited` — source inspection confirms PII patterns inlined and BLOCKED string present |
| 6 | **Guardrails fail closed** — NeMo engine catches exceptions and returns blocked result; uncertain classifications refused not allowed | **Verified** | `test_guardrails_engine.py::TestGuardrailsEngineFailClosed` — engine returns blocked when LLM unavailable; `GuardrailsEngine.check_input/check_output` wrap all calls in try/except with fail-closed result |

---

## Red-Team Findings

The following findings were identified through the red-team test suite in `tests/integration/test_red_team.py`. All tests are `@pytest.mark.integration` and require a live stack to execute.

| # | Finding | Severity | Status | Mitigation |
|---|---|---|---|---|
| RT-01 | **Unauthenticated access to chat endpoints** | Critical | **Mitigated** | JWT `validate_jwt()` dependency on all `/v1/chat*` routes returns 401 for missing/invalid tokens. Verified by `TestRedTeamProxyEndpoints::test_no_auth_returns_401`. |
| RT-02 | **Expired JWT accepted** | High | **Mitigated** | `jwt.decode()` validates `exp` claim; `ExpiredSignatureError` → 401. Verified by `test_expired_jwt_returns_401`. |
| RT-03 | **Malformed JWT accepted** | High | **Mitigated** | `jwt.decode()` raises `DecodeError` for non-JWT tokens → 401. Verified by `test_malformed_jwt_returns_401`. |
| RT-04 | **Oversized message accepted** | Medium | **Mitigated** | `ChatRequest.message` has `max_length=4000` (Pydantic); longer payloads rejected with 422. Verified by `test_oversized_message_rejected`. |
| RT-05 | **SQL/injection in `conversation_id`** | Medium | **Mitigated** | `conversation_id` field has strict UUID regex pattern (Pydantic); non-UUID values rejected with 422. Verified by `test_sql_injection_in_conversation_id`. |
| RT-06 | **Cross-user conversation access via spoofed `conversation_id`** | High | **Mitigated** | `validate_conversation_ownership()` checks conversation summary against JWT `user_id` before forwarding; returns 403 on mismatch. Verified by `test_conversation_id_spoofing`. |
| RT-07 | **`user_id` override via message payload** | High | **Mitigated** | Tools read `os.getenv("LETTA_USER_ID")` (injected from JWT); message content cannot override it. Verified by `test_jwt_user_id_cannot_be_overridden_by_message`. |
| RT-08 | **Admin tool invocation by regular user via prompt** | High | **Mitigated** | Admin tools validate `LETTA_USER_ROLE == "admin"` at runtime from env (not from message). Either guardrails block the attempt or the tool returns "Access denied". Verified by `test_regular_user_admin_tool_via_prompt`. |
| RT-09 | **Role injection via message content** | High | **Mitigated** | Role comes from JWT, injected via `LETTA_USER_ROLE` env variable. Message-stated role has no effect on tool authorization. Verified by `test_role_injection_in_message`. |
| RT-10 | **PII leakage via archival memory search prompt** | High | **Mitigated** | Input rails may block direct archival dump requests; output PII rails strip emails/UUIDs/phone/IP from any response regardless. Verified by `test_archival_memory_search_via_prompt`. |
| RT-11 | **Core memory dump via prompt** | Medium | **Partially mitigated** | Agent persona instructs no verbatim memory block disclosure. Input rails may block explicit dump requests. No hard code-level prevention in current implementation — relies on persona + guardrails. See Residual Risks. |

---

## Residual Risks

### RR-01: Shared Archival Memory

**Description**: All users share a single archival memory store. Agent-written patterns are visible across users via `archival_memory_search`. If PII reaches archival memory (e.g., regex gap), it is accessible to all users.

**Severity**: Medium  
**Mitigation**: Custom memory tool wrappers (`src/tools/memory.py`) block PII before the write (invariant #5). Proxy post-commit audit provides defense-in-depth logging. Output rails scan any archival search results before they reach the user.  
**Accepted**: Yes (Phase 3). Split architecture deferred per architectural decision 22. See [Archival Memory Isolation Evaluation](archival-memory-evaluation.md) for full analysis.

---

### RR-02: LLM-Controlled Zone is Prompt-Injectable

**Description**: The agent's reasoning loop operates inside Letta's LLM-controlled zone. Prompt injection attacks that bypass input rails can influence agent behavior (tool selection, memory writes, response content). This zone is not a security boundary by design.

**Severity**: Medium  
**Mitigation**: Input rails (Llama Guard + topic classifier + privacy regex) provide a first layer. Admin tool runtime role checks, scoped tokens, and `user_id` from env (not LLM) enforce invariants outside LLM control. Output rails catch PII in responses.  
**Accepted**: Yes. The architecture explicitly acknowledges the LLM zone is prompt-injectable and places enforcement in deterministic code outside it.

---

### RR-03: PII Regex Coverage is Not Exhaustive

**Description**: `_PII_PATTERNS` in `src/guardrails/actions.py` covers email, API keys (sk- prefix), UUID-4, US phone numbers, IPv4, and standard credit card formats. Novel PII formats (e.g., non-standard phone formats, organization-specific ID schemes) may bypass detection.

**Severity**: Low  
**Mitigation**: Proxy post-commit PII audit provides defense-in-depth — if PII bypasses the tool wrapper regex, it is logged as a SECURITY warning for alerting. Patterns can be extended without code restructuring.  
**Accepted**: Yes. Exhaustive PII regex is impractical; layered defense with logging is the appropriate approach.

---

### RR-04: Memory Wrapper Upsert Dependency

**Description**: PII-audited memory enforcement depends on `client.tools.upsert_from_function()` correctly overwriting Letta's built-in `core_memory_append`, `core_memory_replace`, and `archival_memory_insert` tools. If Letta changes upsert semantics (e.g., name-collision behavior), the built-in unaudited tools could become active again.

**Severity**: Medium  
**Mitigation**: `tests/unit/test_security_invariants.py::TestInvariant5MemoryWritePiiAudited` verifies that registered tool source contains PII patterns and BLOCKED string — this test would fail if the wrapper was not registered. Integration test verifies the registered tool source at bootstrap.  
**Accepted**: Yes, with the mitigation. Any Letta upgrade should re-run the invariant test suite.

---

### RR-05: Invariant #1 Relaxation for Memory Wrappers

**Description**: Invariant #1 ("tools are read-only") is relaxed for `src/tools/memory.py` — these wrappers use `httpx.post()` to call Letta's internal memory API and do mutate state. The carve-out is intentional (plan decision D35) to enforce invariant #5, but it creates a pattern that future tool authors could follow incorrectly.

**Severity**: Low  
**Mitigation**: The carve-out is narrow and documented: only `src/tools/memory.py`, only POST to Letta internal API, only with PII gate. `TestInvariant1MemoryWrappers` in `test_security_invariants.py` verifies that memory tools use POST with PII gating. Any new tool following this pattern would need explicit security review.  
**Accepted**: Yes. The invariant has been updated in both `SECURITY.md` and this document to reflect the two-category distinction.

---

### RR-06: Core Memory Dump Lacks Hard Code-Level Prevention

**Description**: `TestRedTeamMemoryExfiltration::test_core_memory_dump_via_prompt` (RT-11 above) is partially mitigated. There is no code-level block on the agent returning its own core memory block contents. Prevention relies on: (a) input rails blocking the request, (b) agent persona instructing non-disclosure, and (c) output rails catching any PII in the response.

**Severity**: Low  
**Mitigation**: The agent's core memory blocks contain only anonymized platform patterns and agent persona — no user-specific data. Even if verbatim content were returned, it should not contain PII. Output rails provide a final check.  
**Accepted**: Yes for Phase 3. If persona content becomes more sensitive in future phases, consider adding explicit Colang rules to block memory-dump intent patterns.

---

### RR-07: JWT HS256 Signing Algorithm

**Description**: The current JWT implementation uses HS256 (shared secret). The same secret is used to sign and verify tokens. Compromise of the `JWT_SECRET` environment variable allows minting of arbitrary tokens with any user_id and role.

**Severity**: High (conditional on secret compromise)  
**Mitigation**: `JWT_SECRET` is managed as a Kubernetes Secret (not in code). `_MIN_JWT_SECRET_LENGTH = 16` enforces a minimum entropy floor. Production migration to RS256 (asymmetric signing) is recorded as architectural decision 11.  
**Accepted**: Yes for PoC/staging. Must be resolved before production deployment to RS256.

---

## Recommendations

Prioritized list of improvements:

| Priority | Recommendation | Category |
|---|---|---|
| **P0** | Migrate JWT signing from HS256 to RS256 for production deployment | Authentication |
| **P1** | Add integration test that verifies registered memory tool source contains PII patterns (post-bootstrap) | Memory safety |
| **P1** | Add Colang rules for explicit memory-dump intent (e.g., "print/dump/show your memory block") to make RT-11 a hard block rather than a persona-only mitigation | Guardrails |
| **P2** | Extend `_PII_PATTERNS` with organization-specific ID formats as they are discovered in production | PII detection |
| **P2** | Add alerting (not just logging) on the proxy post-commit PII audit SECURITY warnings | Observability |
| **P3** | Evaluate Letta SDK for passage metadata filtering support — re-examine archival memory split architecture if available | Memory isolation |
| **P3** | Add `@pytest.mark.flaky(reruns=2)` to red-team tests that involve LLM responses, which are non-deterministic | Test reliability |
| **P3** | Periodic archival memory review process: define admin workflow for reviewing and pruning stale/borderline entries | Operations |

---

## References

- [Security Policy (invariants)](../../SECURITY.md)
- [Security Architecture (trust boundaries, mechanisms)](security.md)
- [Memory and Learning Architecture](memory-and-learning.md)
- [Archival Memory Isolation Evaluation](archival-memory-evaluation.md)
- [Security Invariant Tests](../../tests/unit/test_security_invariants.py)
- [Red-Team Integration Tests](../../tests/integration/test_red_team.py)
- Phase 3 implementation plan: `docs/development/phase-3-hardening/PLAN.md`
