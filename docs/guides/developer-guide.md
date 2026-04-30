# Developer Guide

Everything you need to set up, run, and develop the LiteMaaS Agent Assistant.

## Prerequisites

- **Python 3.12+** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager (replaces pip/pipenv)
- **[Podman](https://podman.io/) or [Docker](https://www.docker.com/)** with Compose support
- **A running LiteMaaS instance** — for integration testing (the tools call its API)
- **A running LiteLLM proxy** — with at least 2 models configured (reasoning + guardrails)

## Initial Setup

```bash
# Clone the repository
git clone <repository-url>
cd litemaas-agent

# Configure environment
cp .env.example .env
# Edit .env with your LiteMaaS, LiteLLM, and JWT settings

# Install dependencies (including dev tools)
uv sync --extra dev
```

See [Configuration Reference](../reference/configuration.md) for details on each environment variable.

## Daily Workflow

### Start the stack (live-reload)

```bash
podman-compose up     # or docker-compose up
```

This uses `compose.override.yaml` automatically, which:
- Mounts `src/` into the container for live-reload
- Enables uvicorn `--reload` (auto-restarts on file changes)
- Writes logs to `logs/agent.log` and `logs/letta.log` (truncated on restart)

### Edit code

Just edit files in `src/`. Uvicorn detects changes and restarts automatically.

### Tail logs

```bash
# In separate terminals:
tail -f logs/agent.log    # Proxy server logs
tail -f logs/letta.log    # Letta runtime logs
```

### Verify health

```bash
curl http://localhost:8400/v1/health
```

## When to Rebuild

Only rebuild when **dependencies change** (`pyproject.toml` or `uv.lock`):

```bash
podman-compose up --build
```

Code changes in `src/` do **not** require a rebuild — the volume mount and `--reload` flag handle it.

### Test production-like behavior

Skip the development overrides:

```bash
podman-compose -f compose.yaml up    # ignores compose.override.yaml
```

## Ports

| Service | URL |
|---|---|
| Proxy | http://localhost:8400 |
| Letta | http://localhost:8283 |
| Swagger UI (auto-generated) | http://localhost:8400/docs |
| ReDoc (auto-generated) | http://localhost:8400/redoc |

## Running Tests

```bash
# Unit tests
uv run pytest tests/unit/ -v

# Guardrail scenario tests
uv run pytest tests/guardrails/ -v -m guardrails

# Integration tests (requires running Letta container)
uv run pytest tests/integration/ -v -m integration

# All tests
uv run pytest

# With coverage
uv run pytest -v --cov=src tests/
```

## Linting and Type Checking

```bash
# Lint
uv run ruff check src/ tests/

# Format check
uv run ruff format --check src/ tests/

# Auto-format
uv run ruff format src/ tests/

# Type check (strict mode)
uv run mypy src/
```

CI runs all three checks. PRs must pass before merging.

## Project Layout

```
src/
├── agent/          # Agent config, bootstrap, persona, memory seeds
├── tools/          # Read-only tools (LiteMaaS, LiteLLM, admin, docs)
├── guardrails/     # NeMo Guardrails: engine, config/ (Colang rules), actions
├── proxy/          # FastAPI server, JWT auth, routes
└── adapters/       # Platform-specific adapters (placeholder)
tests/
├── unit/           # Unit tests for all modules
├── integration/    # Integration tests (require Letta)
└── guardrails/     # Adversarial prompt scenarios
```

**PYTHONPATH**: Set to `src/` in the container. Imports look like `from agent.config import Settings`.

**Build system**: Hatchling (`pyproject.toml`). The wheel packages `agent`, `tools`, `guardrails`, `proxy`, and `adapters`.

See [Module Reference](../reference/modules.md) for detailed module documentation.

## Key Concepts for New Contributors

### Two-Container Model

The proxy is our custom code. Letta is off-the-shelf — we don't modify its image. The proxy sits between the user and Letta, handling auth, guardrails, and streaming.

### Tools Run Inside Letta

Tool functions are registered with Letta at bootstrap. When the agent calls a tool, **Letta executes it** in its own process. Tools must be self-contained: inline all imports, use `os.getenv()` for config, cannot import from other `src/` modules.

### Security Invariants

Six non-negotiable rules. Read [SECURITY.md](../../SECURITY.md) before touching tools, auth, or guardrails.

### Guardrails Are a Library

NeMo Guardrails is embedded as a Python library inside the proxy container. It is not a separate service. It uses a configurable LLM for rail evaluation (typically a fast model).

## Debugging Tips

### Agent not responding

1. Check Letta health: `curl http://localhost:8283/v1/health`
2. Check `logs/letta.log` for errors
3. Verify `LETTA_SERVER_URL` points to the right address
4. Check if the agent was bootstrapped: look for "Agent bootstrapped" in `logs/agent.log`

### Guardrails blocking everything

1. Check `GUARDRAILS_MODEL` is a valid, reachable model
2. Check `GUARDRAILS_LLM_API_BASE` and `GUARDRAILS_LLM_API_KEY` are correct
3. Look for "Guardrails error" in `logs/agent.log`
4. Set `GUARDRAILS_REQUIRED=false` temporarily to bypass (development only)

### Tools failing

1. Verify target APIs are reachable from the Letta container
2. Check that `httpx` is available in Letta's Python environment
3. Verify env vars are injected: `LITEMAAS_API_URL`, `LITELLM_API_URL`, keys
4. Check Letta logs for tool execution errors

### JWT errors

1. Verify `JWT_SECRET` matches the LiteMaaS instance
2. Check token expiration (default: 24 hours)
3. Ensure the `Authorization: Bearer <token>` header is present
4. Check required claims: `userId`, `username`, `email`, `roles`

## Useful Commands

| Command | Description |
|---|---|
| `podman-compose up` | Start with live-reload |
| `podman-compose up --build` | Rebuild and start |
| `podman-compose -f compose.yaml up` | Start without dev overrides |
| `uv sync --extra dev` | Install/update dependencies |
| `uv run pytest tests/unit/ -v` | Run unit tests |
| `uv run ruff check src/ tests/` | Lint |
| `uv run ruff format src/ tests/` | Auto-format |
| `uv run mypy src/` | Type check |
| `curl localhost:8400/v1/health` | Check proxy health |
| `curl localhost:8283/v1/health` | Check Letta health |
