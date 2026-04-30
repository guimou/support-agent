# CLAUDE.md — LiteMaaS Agent Assistant

## Project Overview

Standalone AI agent that acts as an intelligent **platform support assistant** for LiteMaaS users. Helps with platform questions, troubleshooting, and guidance — **not** the model playground (that's `/chatbot`).

**Status**: Phase 1 (Foundation) complete — proxy, guardrails, tools, and agent bootstrap implemented.

**Documentation**: `docs/index.md` is the navigation hub. Start there for architecture, reference, and guides.

## Architecture

**Two-container model** communicating via REST:

| Container | Role | Port |
|---|---|---|
| **Proxy** (`agent`) | FastAPI: JWT auth, NeMo Guardrails (embedded Python lib), SSE streaming | 8400 |
| **Letta** (`letta`) | Off-the-shelf agent runtime: reasoning, memory, tool execution, embedded PostgreSQL + pgvector | 8283 |

Request flow: `LiteMaaS Backend → Proxy (auth + input rails) → Letta (reasoning + tools) → Proxy (output rails) → LiteMaaS Backend`

Details: `docs/architecture/overview.md`

## Security Invariants (Non-Negotiable)

These MUST be enforced in all code. Never compromise on these:

1. **Tools are read-only** — only `GET` requests, no mutations
2. **`user_id` comes from JWT, never from LLM** — tools read `os.getenv("LETTA_USER_ID")`, never accept `user_id` as a function parameter
3. **Admin tools are role-gated** — all tools registered on a single shared agent; admin tools validate `LETTA_USER_ROLE == "admin"` at runtime (defense-in-depth)
4. **Scoped tokens** — standard tools use `LITELLM_USER_API_KEY` (read-only); admin tools use `LITELLM_API_KEY` (master key, injected only for admin requests)
5. **Memory writes are PII-audited** — hook inspects every `core_memory_append` / `archival_memory_insert` for PII before commit
6. **Guardrails fail closed** — uncertain classifications are refused, not allowed

Details: `docs/architecture/security.md`

## Key Patterns

### Tool Development

Tools are plain Python functions registered via `client.tools.upsert_from_function()` at bootstrap, executed inside Letta's process (not the proxy). Do NOT use the `@tool` decorator — it breaks source extraction:

```python
def my_tool(param: str) -> str:
    import os, httpx
    user_id = os.getenv("LETTA_USER_ID")  # NEVER accept as function arg
    base_url = os.getenv("LITEMAAS_API_URL")
    token = os.getenv("LITELLM_USER_API_KEY")
    response = httpx.get(...)  # GET only
    return format_result(response.json())
```

Details: `docs/reference/tools.md`

### Model Naming

Letta requires a provider prefix (`provider/model-name` for `AGENT_MODEL`), but guardrails call the LLM provider directly and use the plain model name (`GUARDRAILS_MODEL`).

## LiteLLM API Quirks

- Auth header is `x-litellm-api-key` (not `Authorization: Bearer`)
- Sentinel value `2147483647` means "unlimited" for TPM/RPM
- `/key/info` response can be nested (`data.info.*`) or flat — normalize with `data.get("info", data)`
- `/health/liveness` may return JSON or plain text `I'm alive!`

## Development

```bash
podman-compose up                  # live-reload (compose.override.yaml applied automatically)
podman-compose up --build          # rebuild after dependency changes (pyproject.toml / uv.lock)
tail -f logs/agent.log             # proxy logs (separate terminal)
tail -f logs/letta.log             # Letta logs (separate terminal)
```

| Service | URL |
|---|---|
| Proxy | http://localhost:8400 |
| Letta | http://localhost:8283 |
| Swagger UI | http://localhost:8400/docs |
| ReDoc | http://localhost:8400/redoc |

**Podman networking**: from the dev environment (outside containers), services are reachable at `host.containers.internal`, not `localhost`. Use `http://host.containers.internal:8400` for the proxy and `:8283` for Letta when testing with `curl`, integration tests, etc.

Full workflow, testing, linting, debugging: `docs/guides/developer-guide.md`

## Configuration

All configuration is via environment variables. See `docs/reference/configuration.md` for the full table with rationale, and `.env.example` for a ready-to-fill template.

## Reference Pointers

| Topic | Document |
|---|---|
| Memory architecture | `docs/architecture/memory-and-learning.md` |
| Guardrails & Colang rules | `docs/reference/guardrails.md` |
| JWT auth & token claims | `docs/reference/authentication.md` |
| SSE streaming protocol | `docs/reference/api.md` |
| Frontend widget | `docs/guides/frontend-integration.md` |
| Architecture decisions & open questions | `docs/architecture/decisions.md` |
| Module structure | `docs/reference/modules.md` |
| Platform adaptation | `docs/guides/adapting-to-another-platform.md` |
