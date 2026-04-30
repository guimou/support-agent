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

### 1. Tools Are Read-Only

All tool functions use `httpx.get()` exclusively. No HTTP methods that mutate data (`POST`, `PUT`, `DELETE`, `PATCH`) are used in tools.

**One documented exception**: `get_global_usage_stats()` uses `POST` because the LiteMaaS admin analytics endpoint requires complex filter arrays in the request body. This endpoint does not mutate data.

### 2. `user_id` Comes From JWT, Never From LLM

Tools read the authenticated user's identity from `os.getenv("LETTA_USER_ID")`, which is injected by the proxy from the validated JWT. Tools **never** accept `user_id` as a function parameter. This eliminates prompt injection as a vector for identity spoofing.

### 3. Admin Tools Are Role-Gated

All tools (standard + admin) are registered on a single shared agent. Admin tools validate `LETTA_USER_ROLE == "admin"` at runtime before executing. This is a defense-in-depth measure.

### 4. Scoped Tokens

Standard tools use `LITELLM_USER_API_KEY` (read-only, user-facing endpoints). Admin tools use `LITELLM_API_KEY` (master key), injected only for admin requests. If the user-scoped token is compromised, it cannot access admin endpoints.

### 5. Memory Writes Are PII-Audited

Shared memory (core memory, archival memory) must never contain user-identifying information. Output guardrails include regex-based PII detection for emails, API keys, and UUIDs.

### 6. Guardrails Fail Closed

When NeMo Guardrails encounters an error or uncertain classification, the message is **refused**, not allowed. This applies to both input and output rails.

## Security Testing

- **`tests/unit/test_security_invariants.py`** — Validates security invariants through source code inspection (no `user_id` parameters, GET-only HTTP methods, admin role checks)
- **`tests/guardrails/`** — Adversarial prompt scenarios for injection, jailbreak, and cross-user probing
- **Phase 3** (planned) — Red-team testing with multi-turn manipulation and encoding tricks

## Responsible Disclosure

We follow a coordinated disclosure process. Security researchers who report vulnerabilities responsibly will be credited (with permission) in the changelog.
