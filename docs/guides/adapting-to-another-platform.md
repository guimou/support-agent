# Adapting to Another Platform

The agent is designed as a reusable project. This guide walks through what to change to adapt it for a platform other than LiteMaaS.

## What Stays the Same

These components are platform-independent and require no changes:

- **Proxy server** (`src/proxy/`) — FastAPI, JWT auth, SSE streaming, rate limiting
- **Guardrails engine** (`src/guardrails/rails.py`) — NeMo Guardrails integration
- **Agent bootstrap logic** (`src/agent/bootstrap.py`) — Letta agent creation, tool registration, memory seeding
- **Memory architecture** — core, recall, archival tiers
- **Container setup** — Containerfile, compose.yaml, health checks
- **Security invariants** — read-only tools, user_id from JWT, scoped tokens

## What You Change

### 1. Platform Adapter (`src/adapters/`)

Implement the adapter interface for your platform. This is the reusability layer that maps platform-specific concepts to the agent's abstractions.

**Files**: `src/adapters/base.py` (interface), `src/adapters/yourplatform.py` (implementation)

> **Current status**: The adapter layer is a placeholder. For LiteMaaS, tools call APIs directly without an adapter. When implementing for a second platform, define the adapter interface based on common patterns.

### 2. Tools (`src/tools/`)

Replace the LiteMaaS and LiteLLM tools with your platform's API calls.

**Files to modify**: `src/tools/litemaas.py`, `src/tools/litellm.py`, `src/tools/admin.py`, `src/tools/docs.py`

**What to keep**:
- Plain function pattern (registered via `client.tools.upsert_from_function()`)
- Self-contained functions (inline imports, `os.getenv()` for config)
- `user_id` from `os.getenv("LETTA_USER_ID")` — never as a function parameter
- `GET`-only HTTP requests
- Admin tools with inline `LETTA_USER_ROLE == "admin"` check

**Security checklist for new tools**:
- [ ] Uses only `GET` requests (document any exceptions)
- [ ] Reads `user_id` from `os.getenv("LETTA_USER_ID")`
- [ ] Does not accept `user_id` as a function parameter
- [ ] Admin tools check `LETTA_USER_ROLE == "admin"`
- [ ] Uses scoped token (not master key) for standard tools
- [ ] All imports are inline within the function body
- [ ] Dependencies are available in the Letta image

**Update tool registration**: Edit the `all_tools` list in `_register_tools()` in `src/agent/bootstrap.py`.

### 3. Agent Persona (`src/agent/persona.py`)

Rewrite the three core memory blocks for your domain:

- **`PERSONA_BLOCK`** — agent identity, capabilities, behavior rules, PII prohibition
- **`KNOWLEDGE_BLOCK`** — domain-specific knowledge (your platform's concepts, common patterns, terminology)
- **`PATTERNS_BLOCK`** — initially empty (the agent will populate this through interactions)

Keep the PII prohibition rules in the persona — they are security-critical.

### 4. Memory Seeds (`src/agent/memory_seeds.py`)

Replace `ARCHIVAL_SEEDS` with FAQ entries and documentation relevant to your platform.

- Update `SEED_VERSION_MARKER` to trigger re-seeding
- Each seed should be a focused piece of knowledge (one topic per entry)
- Seeds are inserted into archival memory at bootstrap (idempotent via version tracking)

### 5. Guardrail Rules (`src/guardrails/config/`)

Update Colang rules for your domain:

**`topics.co`** — rewrite the intent examples:
- `user ask about yourplatform` — example utterances for on-topic questions
- `user ask about unrelated topic` — examples for off-topic questions
- Update the refusal response to reference your platform

**`safety.co`** — likely stays similar (generic safety rules)

**`privacy.co`** — likely stays similar (cross-user isolation is platform-independent)

**`prompts.yml`** — update the system instruction to describe your platform's scope

**`config.yml`** — no changes needed (model config is from environment variables)

### 6. Integration Reference Doc

Create your own version of the integration reference (`docs/reference/`) documenting:
- Your platform's API schemas (endpoints, request/response shapes)
- Authentication mechanism
- Data models (the entities your tools work with)
- Frontend integration patterns (if applicable)

### 7. Environment Variables

Update `.env.example` with your platform's variables:
- Replace `LITEMAAS_API_URL` with your platform's API URL
- Replace `LITELLM_*` variables with your platform's monitoring endpoints
- Keep the LLM provider variables (`AGENT_MODEL`, `GUARDRAILS_MODEL`, etc.) — they're platform-independent

Update `src/agent/config.py` `Settings` class accordingly.

## Step-by-Step Walkthrough

1. Fork the repository
2. Replace tool implementations in `src/tools/`
3. Update persona and memory seeds in `src/agent/`
4. Update Colang topic rules in `src/guardrails/config/topics.co`
5. Update `src/agent/config.py` with your platform's env vars
6. Update `.env.example`
7. Update tests in `tests/unit/` for your new tools
8. Update tests in `tests/guardrails/` for your topic rules
9. Run full test suite: `uv run pytest`
10. Update documentation in `docs/reference/`

## Example: Minimal Adaptation

For a platform with just two API endpoints (list items, get user status):

```python
# src/tools/myplatform.py
# Plain functions — registered at bootstrap via client.tools.upsert_from_function()
# Do NOT use @tool decorator (it would break source extraction)

def list_items(search: str = "") -> str:
    """List items available on the platform."""
    import os, httpx
    base_url = os.getenv("MYPLATFORM_API_URL")
    token = os.getenv("MYPLATFORM_USER_TOKEN")
    response = httpx.get(
        f"{base_url}/api/items",
        params={"search": search} if search else {},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    items = response.json().get("data", [])
    return "\n".join(f"- {i['name']}: {i['status']}" for i in items) or "No items found."

def get_my_status() -> str:
    """Get the current user's account status."""
    import os, httpx
    user_id = os.getenv("LETTA_USER_ID")
    base_url = os.getenv("MYPLATFORM_API_URL")
    token = os.getenv("MYPLATFORM_USER_TOKEN")
    response = httpx.get(
        f"{base_url}/api/users/{user_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    data = response.json()
    return f"Account: {data['status']}, Plan: {data['plan']}, Usage: {data['usage']}%"
```
