# CLAUDE.md — LiteMaaS Agent Assistant

## Project Overview

Standalone AI agent that acts as an intelligent **platform support assistant** for LiteMaaS users. Helps with platform questions, troubleshooting, and guidance — **not** the model playground (that's `/chatbot`).

**Status**: Design phase — architecture docs in `docs/architecture/`, no implementation yet.

Key documents:
- `docs/architecture/ai-agent-assistant.md` — Full architecture & scenarios
- `docs/architecture/ai-agent-assistant-integration-reference.md` — LiteMaaS/LiteLLM API schemas, JWT structure, frontend patterns

## Architecture

**Two-container model** communicating via REST:

| Container | Role | Port |
|---|---|---|
| **Proxy** (`agent`) | FastAPI: JWT auth, NeMo Guardrails (embedded Python lib), SSE streaming | 8400 |
| **Letta** (`letta`) | Off-the-shelf agent runtime: reasoning, memory, tool execution, embedded PostgreSQL + pgvector | 8283 |

Request flow: `LiteMaaS Backend → Proxy (auth + input rails) → Letta (reasoning + tools) → Proxy (output rails) → LiteMaaS Backend`

## Tech Stack

- **Language**: Python (agent), TypeScript (LiteMaaS integration)
- **Agent runtime**: Letta (formerly MemGPT) — stateful agent with self-editing memory
- **Guardrails**: NVIDIA NeMo Guardrails — embedded as Python library, uses Colang rules
- **Proxy**: FastAPI with SSE streaming
- **Frontend widget**: PatternFly 6, `@patternfly/chatbot` component
- **Auth**: JWT (HS256 for PoC, RS256 for production)
- **Models**: Multi-model via LiteLLM — `AGENT_MODEL` (reasoning) + `GUARDRAILS_MODEL` (fast classification)

## Project Structure (Target)

```
src/
├── agent/              # Agent config, bootstrap, persona, memory seeds
├── tools/              # Read-only tools (LiteMaaS, LiteLLM, admin, docs)
├── guardrails/         # NeMo Guardrails: rails.py, config/ (Colang .co files), actions.py
├── proxy/              # FastAPI server, JWT auth, routes
└── adapters/           # Platform-specific adapters (reusability layer)
tests/
├── unit/
├── integration/
└── guardrails/         # Adversarial prompt + privacy test scenarios
deployment/
├── helm/
└── kustomize/
scripts/
├── seed-knowledge.py
└── export-knowledge.py
```

## Security Invariants (Non-Negotiable)

These MUST be enforced in all code. Never compromise on these:

1. **Tools are read-only** — only `GET` requests, no mutations
2. **`user_id` comes from JWT, never from LLM** — tools read `os.getenv("LETTA_USER_ID")`, never accept `user_id` as a function parameter
3. **Admin tools are role-gated** — all tools (standard + admin) registered on a single shared agent; admin tools validate `LETTA_USER_ROLE == "admin"` at runtime (defense-in-depth, since Letta cannot do per-conversation tool registration)
4. **Scoped tokens** — standard tools use `LITELLM_USER_API_KEY` (read-only); admin tools use `LITELLM_API_KEY` (master key, injected only for admin requests)
5. **Memory writes are PII-audited** — hook inspects every `core_memory_append` / `archival_memory_insert` for PII before commit
6. **Guardrails fail closed** — uncertain classifications are refused, not allowed

## Key Patterns

### Tool Development

Tools are plain Python functions with `@tool` decorator, executed inside Letta's process (not the proxy):

```python
from letta import tool

@tool
def my_tool(param: str) -> str:
    user_id = os.getenv("LETTA_USER_ID")  # NEVER accept as function arg
    base_url = os.getenv("LITEMAAS_API_URL")
    token = os.getenv("LITELLM_USER_API_KEY")
    response = httpx.get(...)  # GET only
    return format_result(response.json())
```

Tool dependencies must be available in Letta's Python environment. Prefer stdlib or libraries already in `letta/letta` image.

### Memory Architecture

- **Core Memory** (in-context, SHARED) — persona, knowledge, patterns blocks. Never store user-specific info here.
- **Recall Memory** (searchable, PER-USER) — conversation history scoped by conversation ID.
- **Archival Memory** (vector store, SHARED) — documentation, resolution summaries, FAQ.

### Guardrails

Colang rules in `src/guardrails/config/`:
- `topics.co` — topic control (on-topic enforcement)
- `privacy.co` — cross-user data isolation
- `safety.co` — content safety

Output rails: two-layer evaluation — fast regex pre-filter per chunk + full NeMo rail evaluation per ~200-token chunk (50-token sliding window overlap). Unsafe chunks replaced with `...removed...`.

### JWT Claims

```json
{
  "userId": "UUID",
  "username": "string",
  "email": "string",
  "roles": ["user"] or ["admin", "user"],
  "iat": number,
  "exp": number
}
```

Admin check: `"admin" in roles`. Algorithm: HS256 with `JWT_SECRET`.

### SSE Streaming Protocol

POST-based SSE (not EventSource). Custom format:
```
data: {"chunk": "text", "index": 0}
data: {"retract_chunk": 2, "placeholder": "...removed..."}
data: {"done": true, "safety_notice": null}
```

### Frontend Widget

Floating panel using `@patternfly/chatbot` (already installed in LiteMaaS). Imports from `@patternfly/chatbot/dist/dynamic/*`. Role mapping: PF uses `"bot"` not `"assistant"`.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `LETTA_SERVER_URL` | Yes | Letta runtime URL |
| `LITEMAAS_API_URL` | Yes | LiteMaaS backend API |
| `LITELLM_API_URL` | Yes | LiteLLM proxy URL |
| `LITELLM_API_KEY` | Yes | Master key (admin tools only) |
| `LITELLM_USER_API_KEY` | Yes | Scoped read-only key (standard tools) |
| `AGENT_MODEL` | Yes | Reasoning model name (via LiteLLM) |
| `GUARDRAILS_MODEL` | Yes | Fast model for NeMo rail evaluation |
| `JWT_SECRET` | Yes | Shared JWT signing secret (HS256) |
| `RATE_LIMIT_RPM` | No | Per-user chat requests/min (default: 30) |
| `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` | No | Per-user memory writes/hr (default: 20) |

## LiteLLM API Quirks

- Auth header is `x-litellm-api-key` (not `Authorization: Bearer`)
- Sentinel value `2147483647` means "unlimited" for TPM/RPM
- `/key/info` response can be nested (`data.info.*`) or flat — normalize with `data.get("info", data)`
- `/health/liveness` may return JSON or plain text `I'm alive!`

## Open Questions (Validate in Phase 1)

- Concurrent core memory writes — does Letta serialize them?
- Tool dependencies — is `httpx` available in stock `letta/letta` image?
- Per-conversation tool registration — does Letta support different tool sets per conversation?
- `conversation_search` isolation — does Letta enforce conversation-scoped search?

## Development

```bash
# Local dev (when compose.yaml exists)
podman-compose up        # or docker-compose up

# Ports
# Proxy: http://localhost:8400
# Letta:  http://localhost:8283
```

## Commands

```bash
# Seed knowledge into agent
python scripts/seed-knowledge.py

# Export learned knowledge for review
python scripts/export-knowledge.py
```
