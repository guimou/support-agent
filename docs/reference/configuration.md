# Configuration Reference

All configuration is via environment variables. The `Settings` class in `src/agent/config.py` is the ground truth — update it when adding new variables.

## Environment Variables

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `LETTA_SERVER_URL` | Yes | -- | Letta runtime URL (e.g., `http://letta:8283`) |
| `LITEMAAS_API_URL` | Yes | -- | LiteMaaS backend API base URL |
| `JWT_SECRET` | Yes | -- | Shared JWT signing secret (HS256, must match LiteMaaS) |

### LLM Providers

These power the agent's reasoning and guardrail evaluation. They are **independent** from the monitored platform — the agent can use any LLM provider.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AGENT_MODEL` | Yes | -- | Reasoning model name. Uses Letta provider prefix (e.g., `openai-proxy/MyModel`) |
| `AGENT_LLM_API_BASE` | Yes | -- | Agent model provider URL |
| `AGENT_LLM_API_KEY` | Yes | -- | Agent model provider API key |
| `GUARDRAILS_MODEL` | Yes | -- | Fast model for guardrail evaluation. Plain name, no prefix (e.g., `MyModel`) |
| `GUARDRAILS_LLM_API_BASE` | Yes | -- | Guardrails model provider URL |
| `GUARDRAILS_LLM_API_KEY` | Yes | -- | Guardrails model provider API key |

**Why two sets?** The agent's reasoning model and the guardrails classification model have different requirements. The reasoning model needs depth; the guardrails model needs speed and low cost.

**Naming convention**: Letta requires a provider prefix (`openai-proxy/MyModel`) because it routes through its own LLM abstraction. Guardrails call the LLM provider directly and use the plain model name (`MyModel`).

### Monitored Platform

These configure which LiteLLM instance the tools query (the platform being monitored, not the LLM provider powering the agent).

| Variable | Required | Default | Description |
|---|---|---|---|
| `LITELLM_API_URL` | Yes | -- | Monitored LiteLLM instance URL |
| `LITELLM_API_KEY` | Yes | -- | LiteLLM master key (admin tools only) |
| `LITELLM_USER_API_KEY` | Yes | -- | LiteLLM scoped read-only key (standard tools) |

**`LITELLM_API_KEY` vs `LITELLM_USER_API_KEY`**: Standard tools use the scoped key (read-only, user-facing endpoints). Admin tools use the master key, which is only injected into conversations with an admin JWT. This limits blast radius if the user-scoped key is compromised.

### Optional

| Variable | Required | Default | Description |
|---|---|---|---|
| `PROXY_PORT` | No | `8400` | Proxy server port |
| `LOG_LEVEL` | No | `info` | Logging level |
| `MEMORY_SEED_PATH` | No | -- | Path to initial knowledge docs for archival seeding |
| `CORS_ORIGINS` | No | `*` | Allowed CORS origins (restrict in production) |
| `OUTPUT_RAIL_CHUNK_SIZE` | No | `200` | Tokens per chunk for streaming output rail evaluation |
| `OUTPUT_RAIL_OVERLAP` | No | `50` | Token overlap between chunks (sliding window) |
| `GUARDRAILS_REQUIRED` | No | `true` | If `true`, proxy refuses to start when guardrails init fails |
| `RATE_LIMIT_RPM` | No | `30` | Per-user chat requests per minute |
| `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` | No | `20` | Per-user memory writes per hour |

## Configuration Files

| File | Purpose |
|---|---|
| `compose.yaml` | Two-service container orchestration (proxy + Letta) |
| `compose.override.yaml` | Development overrides: volume mount for live-reload, uvicorn `--reload`, log capture |
| `Containerfile` | Multi-stage build: builder (installs deps) + runtime (slim image, non-root user) |
| `pyproject.toml` | Python project metadata, dependencies, linting/typing config |
| `.env.example` | Template for all environment variables with comments |
| `src/guardrails/config/config.yml` | NeMo Guardrails model and rail flow configuration |
| `src/guardrails/config/*.co` | Colang rule definitions |
| `src/guardrails/config/prompts.yml` | Guardrails evaluation prompt templates |

## Settings Class

The `Settings` class (`src/agent/config.py`) uses pydantic-settings to load from environment:

```python
from agent.config import Settings
settings = Settings()  # Reads from environment
```

All env var names map to lowercase snake_case field names (e.g., `LETTA_SERVER_URL` -> `settings.letta_server_url`).
