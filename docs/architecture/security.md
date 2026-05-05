# Security Architecture

This document describes the agent's security model, trust boundaries, and the mechanisms that enforce them.

For the six non-negotiable invariants and vulnerability reporting, see [Security Policy](../../SECURITY.md).

## Trust Boundaries

The system has three zones with hard enforcement between them:

```
+----------------------------------------------------------+
|                    UNTRUSTED ZONE                         |
|                                                          |
|  User input (potential prompt injection, PII, malicious  |
|  queries, cross-user probing, privilege escalation)      |
+------------------------+---------------------------------+
                         |
            NeMo Guardrails: Input Rails
                         |
+------------------------v---------------------------------+
|               LLM-CONTROLLED ZONE                        |
|               (prompt-injectable -- not a security boundary)
|                                                          |
|  Agent reasoning (Letta inner monologue + tool selection)|
|  Memory operations (core, recall, archival)              |
|                                                          |
|  The LLM decides WHAT to do -- but security-critical     |
|  values (user_id, user_role, tool availability) are      |
|  enforced outside the LLM's control.                     |
+------------------------+---------------------------------+
                         |
+------------------------v---------------------------------+
|               HARD ENFORCEMENT ZONE                      |
|               (deterministic code -- not LLM-controlled) |
|                                                          |
|  Invariants enforced in code:                            |
|  - user_id injected from JWT into tool environment       |
|  - user_role injected from JWT into tool environment     |
|  - Admin tools validate role before execution            |
|  - External tool calls are GET-only (no mutations)       |
|  - Memory wrappers POST to Letta API with PII gate       |
|  - Scoped service tokens (user token != admin token)     |
|  - Per-user rate limiting at proxy layer                 |
|  - Memory write throttling per user                      |
+------------------------+---------------------------------+
                         |
            NeMo Guardrails: Output Rails
                         |
+------------------------v---------------------------------+
|                    UNTRUSTED ZONE                         |
|                                                          |
|  Agent response (potential PII leakage, hallucination,   |
|  cross-user data in learned memories)                    |
+----------------------------------------------------------+
```

**Design principle**: The LLM is never the last line of defense for security-critical decisions. It enhances the user experience (choosing the right tool, formatting responses), but access control decisions are made in deterministic code.

## Security Mechanisms

| Mechanism | What it prevents | How |
|---|---|---|
| **JWT validation in proxy** | Impersonation | User identity from cryptographically signed token (HS256 for PoC; RS256 for production) |
| **NeMo input rails** | Prompt injection, jailbreaks, cross-user probing | Llama Guard safety check + intent-based and regex-based cross-user isolation flows + topic classifier. Fail-closed on uncertainty |
| **Trusted user_id injection** | Cross-user data access | `user_id` injected into tool environment by proxy (from JWT). Tools read `os.getenv("LETTA_USER_ID")` — never accept it as an LLM argument |
| **Role-gated admin tools** | Privilege escalation | Admin tools validate `LETTA_USER_ROLE == "admin"` from environment before executing (defense-in-depth) |
| **Scoped service tokens** | Blast radius of token compromise | Standard tools use `LITELLM_USER_API_KEY` (read-only). Admin tools use `LITELLM_API_KEY` (master key), injected only for admin requests |
| **Read-only enforcement** | Unauthorized mutations | External API tools use `httpx.get()` exclusively. Internal memory wrappers use `httpx.post()` to Letta API, gated by PII pre-check |
| **Per-user rate limiting** | Resource exhaustion, info extraction | Proxy enforces per-user request limits. Separate throttle on memory writes |
| **NeMo output rails** | PII leakage, unsafe content | Two-layer: fast regex pre-filter (emails, API keys, UUIDs, phone numbers, IPv4, credit cards) + full NeMo rail evaluation per ~200-token chunk |
| **Memory isolation** | Cross-user leakage | Per-conversation recall memory; shared archival contains only anonymized patterns |
| **Guardrail test suite** | Regression in safety | Automated injection, jailbreak, and cross-user scenario tests in CI |

## Memory Safety

The agent's shared memory (core memory blocks and archival memory) presents multiple risks:

### Threat 1: Cross-User Data Leakage

If the agent stores user-specific details as "general knowledge" in shared memory, those details could surface for other users.

### Threat 2: Memory Poisoning

A malicious user can feed the agent false patterns through repeated interactions. These get stored in shared core memory and affect advice given to all future users.

### Threat 3: Memory Exfiltration

A prompt injection can trick the agent into broadly searching archival memory and surfacing stored patterns that contain residual PII.

### Mitigations

1. **Persona instructions** explicitly tell the agent to anonymize before storing — no user names, emails, API keys, or identifying information in shared memory
2. **Pre-commit PII audit on memory writes** — custom memory tool wrappers (`src/tools/memory.py`) replace Letta's built-in tools and run PII regex against content before calling the Letta memory API. If PII is detected, the write is rejected (agent receives `BLOCKED` error, write never committed). A secondary proxy-side post-commit audit provides defense-in-depth
3. **Memory write throttling** — a single user cannot trigger more than N core memory updates per time window (`RATE_LIMIT_MEMORY_WRITES_PER_HOUR`)
4. **Output rails PII scanning** — every response is checked for PII patterns against a deny-list of known identifiers
5. **Periodic memory audit** — admins review and prune stale or PII-containing entries via the memory dashboard
6. **Memory export** — `export-knowledge.py` dumps all learned knowledge for human review

### Future: Archival Memory Isolation

The current design uses a single shared archival memory store. A more secure architecture would split into:
- **Shared read-only tier**: Documentation, FAQ, release notes — seeded by admins, not writable by the agent
- **Per-user writable tier**: Agent-learned patterns from individual conversations — isolated per user

Agent-learned patterns could be promoted to the shared tier after admin review.
