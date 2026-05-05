# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue
2. Email the maintainers with a description of the vulnerability
3. Include steps to reproduce if possible
4. Allow reasonable time for a fix before public disclosure

We aim to acknowledge reports within 48 hours and provide a fix timeline within 1 week.

## Security Model

The agent operates between untrusted zones (user input and LLM output) with deterministic code enforcement in between. The LLM enhances the user experience but is **never the last line of defense** for security-critical decisions.

For the full security architecture, see [Security Architecture](docs/architecture/security.md).

## Security Invariants

These six invariants are non-negotiable and enforced in code. Any PR that weakens them will be rejected.

### 1. Tools Are Read-Only (External APIs); Memory Wrappers Are PII-Gated (Internal API)

**External API tools** (`src/tools/litemaas.py`, `src/tools/litellm.py`, `src/tools/admin.py`) use `httpx.get()` exclusively. No HTTP methods that mutate data (`POST`, `PUT`, `DELETE`, `PATCH`) are used.

**One documented exception**: `get_global_usage_stats()` uses `POST` because the LiteMaaS admin analytics endpoint requires complex filter arrays in the request body. This endpoint does not mutate data.

**Internal memory wrappers** (`src/tools/memory.py`) use `httpx.post()` to call Letta's internal memory API. These wrappers *do* mutate state — they exist to enforce invariant #5 (PII-audited memory writes) by intercepting writes before they reach Letta. Each wrapper runs PII regex against the content and rejects the write with a `BLOCKED` response if PII is detected. These are not user-facing API tools; they are infrastructure that replaces Letta's built-in memory tools with PII-audited versions.

### 2. `user_id` Comes From JWT, Never From LLM

Tools read the authenticated user's identity from `os.getenv("LETTA_USER_ID")`, which is injected by the proxy from the validated JWT. Tools **never** accept `user_id` as a function parameter. This eliminates prompt injection as a vector for identity spoofing.

### 3. Admin Tools Are Role-Gated

All tools (standard + admin) are registered on a single shared agent. Admin tools validate `LETTA_USER_ROLE == "admin"` at runtime before executing. This is a defense-in-depth measure.

### 4. Scoped Tokens

Standard tools use `LITELLM_USER_API_KEY` (read-only, user-facing endpoints). Admin tools use `LITELLM_API_KEY` (master key), injected only for admin requests. If the user-scoped token is compromised, it cannot access admin endpoints.

### 5. Memory Writes Are PII-Audited (Pre-Commit)

Shared memory (core memory, archival memory) must never contain user-identifying information. Custom memory tool wrappers (`src/tools/memory.py`) replace Letta's built-in `core_memory_append`, `core_memory_replace`, and `archival_memory_insert` with PII-audited versions that run regex against content **before** the write is committed. If PII is detected (emails, API keys, UUIDs, phone numbers, IP addresses, credit card numbers), the write is rejected and the agent receives a `BLOCKED` error. A secondary proxy-side post-commit audit log provides defense-in-depth.

### 6. Guardrails Fail Closed

When NeMo Guardrails encounters an error or uncertain classification, the message is **refused**, not allowed. This applies to both input and output rails.

## Security Testing

- **`tests/unit/test_security_invariants.py`** — Validates security invariants through source code inspection (no `user_id` parameters, GET-only HTTP methods, admin role checks)
- **`tests/guardrails/`** — Adversarial prompt scenarios for injection, jailbreak, and cross-user probing
- **`tests/guardrails/test_*.py`** — Adversarial prompt scenarios for injection, jailbreak, encoding tricks, cross-user probing, multi-turn manipulation, and indirect probing (Phase 3)
- **`tests/integration/test_red_team.py`** — Full-stack red-team tests: user ID spoofing, admin tool access, memory exfiltration, proxy endpoint security (Phase 3)
- **Security review** — `docs/architecture/security-review.md` documents threat model, findings, and residual risks

## Responsible Disclosure

We follow a coordinated disclosure process. Security researchers who report vulnerabilities responsibly will be credited (with permission) in the changelog.
