# Phase 0 — Project Scaffolding: Detailed Implementation Plan

> **Goal**: Bootable project with dev environment, CI, and empty module structure.
> **Validation**: `podman-compose up` starts both containers; proxy returns 200 on `/v1/health`.
> **Parent plan**: [PROJECT_PLAN.md](../PROJECT_PLAN.md)
> **Architecture**: [ai-agent-assistant.md](../../architecture/ai-agent-assistant.md)

---

## Background

This project is a standalone AI agent that acts as a platform support assistant for LiteMaaS. It uses a two-container architecture:

| Container | Image | Role | Port |
|---|---|---|---|
| **Proxy** (`agent`) | Custom (this project) | FastAPI: JWT auth, NeMo Guardrails, SSE streaming | 8400 |
| **Letta** (`letta`) | `letta/letta:latest` (off-the-shelf) | Agent runtime: reasoning, memory, tool execution | 8283 |

Phase 0 creates the project scaffolding — no business logic, just the skeleton that later phases fill in. The only real code is a `/v1/health` endpoint that returns `{"status": "healthy"}`.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Python version | 3.12 (`>=3.12,<3.14`) | Intersection of Letta SDK (3.11-3.13), NeMo Guardrails (3.10-3.12), FastAPI (3.10+) |
| Package manager | `uv` | Fast, lockfiles, clean pyproject.toml integration |
| Build backend | `hatchling` | Lightweight, modern, src-layout native |
| Linting/formatting | `ruff` | Replaces black + flake8 + isort in one fast tool |
| Type checking | `mypy` (strict) | Catches bugs early; all stubs include type annotations |
| Letta SDK package | `letta-client` (not `letta`) | Proxy needs the HTTP client SDK, not the full server package |
| Container base | `python:3.12-slim` | Matches target Python version, small image size |
| CI | GitHub Actions | Three parallel jobs: lint, type-check, unit tests |
| CI triggers | Push to `main` + PRs to `main` | Standard workflow |

---

## Steps

### Step 1 — `pyproject.toml`

**Create**: `/workspace/pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent", "src/tools", "src/guardrails", "src/proxy", "src/adapters"]

[project]
name = "litemaas-agent"
version = "0.1.0"
description = "AI platform support assistant for LiteMaaS"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12,<3.14"
dependencies = [
    "fastapi>=0.136,<1",
    "uvicorn[standard]>=0.46,<1",
    "httpx>=0.28,<1",
    "pyjwt>=2.12,<3",
    "pydantic>=2.11,<3",
    "pydantic-settings>=2.14,<3",
    "letta-client>=1.10,<2",
    "nemoguardrails>=0.17,<1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3,<9",
    "pytest-asyncio>=0.25,<1",
    "pytest-cov>=6,<7",
    "httpx",
    "mypy>=1.15,<2",
    "ruff>=0.15,<1",
    "types-pyjwt",
]

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # pyflakes
    "I",      # isort
    "N",      # pep8-naming
    "UP",     # pyupgrade
    "B",      # flake8-bugbear
    "A",      # flake8-builtins
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "RUF",    # ruff-specific rules
]

[tool.ruff.lint.isort]
known-first-party = ["agent", "tools", "guardrails", "proxy", "adapters"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
mypy_path = "src"
namespace_packages = true
explicit_package_bases = true

[[tool.mypy.overrides]]
module = [
    "letta_client.*",
    "nemoguardrails.*",
]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    "guardrails: marks tests as guardrail scenario tests",
]
```

**Notes**:
- `[tool.hatch.build.targets.wheel] packages` explicitly lists all top-level packages under `src/`. Without this, hatchling's default discovery would look for a package matching the project name (`litemaas_agent`) and find nothing.
- `httpx` appears in both main and dev dependencies — production uses it for HTTP calls; dev needs it for `FastAPI.TestClient`.
- `letta-client` is the Python SDK for Letta's HTTP API. The `letta` package is the full server — we don't need that in the proxy container.
- `mypy` overrides silence missing import errors for `letta_client` and `nemoguardrails` which may lack complete type stubs.
- `ruff.lint.isort.known-first-party` matches the package names under `src/`.

---

### Step 2 — `.python-version`

**Create**: `/workspace/.python-version`

```
3.12
```

Pins the dev Python version for `uv` and other tools.

---

### Step 3 — `.envrc` (direnv)

**Create**: `/workspace/.envrc`

```bash
# Activate Python venv managed by uv.
# Requires direnv: https://direnv.net
#
# First-time setup:
#   direnv allow

# Create venv if it doesn't exist
if [ ! -d .venv ]; then
    echo "direnv: creating venv with uv..."
    uv venv
fi

# Activate the venv
source .venv/bin/activate

# Load .env if present
dotenv_if_exists
```

**Notes**:
- [direnv](https://direnv.net) automatically activates the venv on `cd` into the project and deactivates on `cd` out.
- If `.venv/` doesn't exist yet, it creates one via `uv venv` on first entry.
- `dotenv_if_exists` loads `.env` variables into the shell (useful for local dev without compose).
- `.envrc` is committed; `.direnv/` is gitignored.
- First-time setup requires `direnv allow` to trust the file.

---

### Step 4 — Source Tree

Create all directories and files below. All `__init__.py` files are **empty** (no imports, no `__all__`).

#### `src/agent/`

**Create**: `src/agent/__init__.py` — Empty file.

**Create**: `src/agent/config.py`

```python
"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent proxy configuration.

    All values are read from environment variables.
    Defaults are provided for optional settings.
    """

    letta_server_url: str
    litemaas_api_url: str
    litellm_api_url: str
    litellm_api_key: str
    litellm_user_api_key: str
    agent_model: str
    guardrails_model: str
    jwt_secret: str

    proxy_port: int = 8400
    log_level: str = "info"
    memory_seed_path: str | None = None
    cors_origins: str = "*"
    output_rail_chunk_size: int = 200
    output_rail_overlap: int = 50
    rate_limit_rpm: int = 30
    rate_limit_memory_writes_per_hour: int = 20
```

**Create**: `src/agent/bootstrap.py`

```python
"""Agent bootstrap: create or connect to Letta agent instance."""
```

**Create**: `src/agent/persona.py`

```python
"""Agent persona and core memory block definitions."""
```

**Create**: `src/agent/memory_seeds.py`

```python
"""Initial knowledge seeds for archival memory."""
```

#### `src/tools/`

**Create**: `src/tools/__init__.py` — Empty file.

**Create**: `src/tools/litemaas.py`

```python
"""Read-only tools for querying the LiteMaaS API."""
```

**Create**: `src/tools/litellm.py`

```python
"""Read-only tools for querying the LiteLLM API."""
```

**Create**: `src/tools/admin.py`

```python
"""Admin-only tools (role-gated). Only registered on admin conversations."""
```

**Create**: `src/tools/docs.py`

```python
"""Documentation search tools."""
```

#### `src/guardrails/`

**Create**: `src/guardrails/__init__.py` — Empty file.

**Create**: `src/guardrails/rails.py`

```python
"""NeMo Guardrails integration (embedded library)."""
```

**Create**: `src/guardrails/actions.py`

```python
"""Custom guardrail actions for NeMo Guardrails."""
```

**Create**: `src/guardrails/config/config.yml`

```yaml
# NeMo Guardrails configuration
# See: https://docs.nvidia.com/nemo/guardrails/
models: []
rails:
  input:
    flows: []
  output:
    flows: []
```

**Create**: `src/guardrails/config/topics.co`

```colang
# Topic control rails (Colang)
# Implemented in Phase 1D
```

**Create**: `src/guardrails/config/privacy.co`

```colang
# Cross-user data isolation rails (Colang)
# Implemented in Phase 3A
```

**Create**: `src/guardrails/config/safety.co`

```colang
# Content safety rails (Colang)
# Implemented in Phase 1D
```

**Create**: `src/guardrails/config/prompts.yml`

```yaml
# Custom prompts for rail evaluation
# Implemented in Phase 1D
```

Note: `src/guardrails/config/` does **not** get an `__init__.py` — it contains config files, not Python code.

#### `src/proxy/`

**Create**: `src/proxy/__init__.py` — Empty file.

**Create**: `src/proxy/server.py`

```python
"""FastAPI proxy server for the LiteMaaS Agent Assistant."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="LiteMaaS Agent Proxy",
    description="Proxy server for the LiteMaaS AI Agent Assistant",
    version="0.1.0",
)


@app.get("/v1/health")
async def health() -> dict[str, str]:
    """Health check endpoint for container probes."""
    return {"status": "healthy"}
```

**Important**: This file deliberately does NOT import `Settings` or connect to Letta. The health endpoint must work without any environment variables set. Full wiring happens in Phase 1C.

**Create**: `src/proxy/auth.py`

```python
"""JWT validation and user context extraction."""
```

**Create**: `src/proxy/routes.py`

```python
"""API route definitions for /v1/chat and /v1/chat/stream."""
```

#### `src/adapters/`

**Create**: `src/adapters/__init__.py` — Empty file.

**Create**: `src/adapters/base.py`

```python
"""Abstract base adapter interface for platform-specific integrations."""
```

**Create**: `src/adapters/litemaas.py`

```python
"""LiteMaaS-specific adapter implementation."""
```

---

### Step 5 — Test Scaffolding

**Create**: `tests/__init__.py` — Empty file.

**Create**: `tests/unit/__init__.py` — Empty file.

**Create**: `tests/unit/conftest.py`

```python
"""Shared fixtures for unit tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from proxy.server import app


@pytest.fixture
def client() -> TestClient:
    """Create a FastAPI test client."""
    return TestClient(app)
```

**Create**: `tests/unit/test_health.py`

```python
"""Tests for the /v1/health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_health_response_shape(client: TestClient) -> None:
    response = client.get("/v1/health")
    data = response.json()
    assert "status" in data
```

**Create**: `tests/integration/__init__.py` — Empty file.

**Create**: `tests/integration/conftest.py`

```python
"""Shared fixtures for integration tests.

Integration tests require running services (Letta, LiteMaaS, LiteLLM).
Mark all tests in this directory with @pytest.mark.integration.
"""
```

**Create**: `tests/guardrails/__init__.py` — Empty file.

**Create**: `tests/guardrails/conftest.py`

```python
"""Shared fixtures for guardrail scenario tests.

Mark all tests in this directory with @pytest.mark.guardrails.
"""
```

---

### Step 6 — `.env.example`

**Create**: `/workspace/.env.example`

```bash
# LiteMaaS Agent Assistant — Environment Variables
# Copy to .env and fill in values: cp .env.example .env

# === Required ===

# Letta agent runtime URL
LETTA_SERVER_URL=http://letta:8283

# LiteMaaS backend API base URL
LITEMAAS_API_URL=http://host.containers.internal:8081

# LiteLLM proxy base URL
LITELLM_API_URL=http://host.containers.internal:4000

# LiteLLM master key (admin tools only + agent model config)
LITELLM_API_KEY=

# LiteLLM scoped read-only key (standard user tools)
LITELLM_USER_API_KEY=

# Reasoning model name (as configured in LiteLLM)
AGENT_MODEL=

# Fast model for NeMo Guardrails rail evaluation (as configured in LiteLLM)
GUARDRAILS_MODEL=

# JWT shared secret (must match LiteMaaS JWT_SECRET, HS256)
JWT_SECRET=

# === Optional ===

# Proxy server port (default: 8400)
# PROXY_PORT=8400

# Logging level (default: info)
# LOG_LEVEL=info

# Path to initial knowledge docs for archival memory seeding
# MEMORY_SEED_PATH=

# CORS allowed origins (default: * — restrict in production)
# CORS_ORIGINS=*

# Output rail chunk size in tokens for streaming evaluation (default: 200)
# OUTPUT_RAIL_CHUNK_SIZE=200

# Token overlap between chunks for context continuity (default: 50)
# OUTPUT_RAIL_OVERLAP=50

# Per-user chat requests per minute (default: 30)
# RATE_LIMIT_RPM=30

# Per-user memory write operations per hour (default: 20)
# RATE_LIMIT_MEMORY_WRITES_PER_HOUR=20
```

---

### Step 7 — `Containerfile`

**Create**: `/workspace/Containerfile`

```dockerfile
# Stage 1: Build — install dependencies in a venv
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

# C++ compiler needed for nemoguardrails -> annoy
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
COPY src/ ./src/

RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache .

# Stage 2: Runtime — slim image with only what's needed
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1001 agent && \
    useradd --uid 1001 --gid agent --shell /bin/bash --create-home agent

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src/ ./src/

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8400

USER agent

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8400/v1/health')"]

CMD ["uvicorn", "proxy.server:app", "--host", "0.0.0.0", "--port", "8400"]
```

**Notes**:
- Multi-stage build: builder installs deps (including C++ compilation), runtime copies only the venv and source.
- `build-essential` is only in the builder stage — runtime stays slim.
- `src/` is copied before `uv pip install .` because hatchling needs it to discover packages.
- `uv.lock*` glob: works whether or not the lockfile exists yet.
- Non-root `agent` user (UID 1001) for security.
- `PYTHONPATH=/app/src` is required for src-layout package discovery.
- Healthcheck uses stdlib `urllib` (no need for `curl` in slim image).

---

### Step 8 — `compose.yaml`

**Create**: `/workspace/compose.yaml`

```yaml
# Local development: podman-compose up
# Production: use Helm chart in deployment/helm/

services:
  agent:
    build:
      context: .
      dockerfile: Containerfile
    ports:
      - "8400:8400"
    environment:
      - LETTA_SERVER_URL=http://letta:8283
      - LITEMAAS_API_URL=http://host.containers.internal:8081
      - LITELLM_API_URL=http://host.containers.internal:4000
      - LITELLM_API_KEY=${LITELLM_API_KEY}
      - LITELLM_USER_API_KEY=${LITELLM_USER_API_KEY}
      - AGENT_MODEL=${AGENT_MODEL}
      - GUARDRAILS_MODEL=${GUARDRAILS_MODEL}
      - JWT_SECRET=${JWT_SECRET}
      - PROXY_PORT=8400
      - LOG_LEVEL=debug
      - RATE_LIMIT_RPM=30
      - RATE_LIMIT_MEMORY_WRITES_PER_HOUR=20
    depends_on:
      letta:
        condition: service_started
    restart: unless-stopped

  letta:
    image: letta/letta:latest
    ports:
      - "8283:8283"
    environment:
      - OPENAI_API_BASE=http://host.containers.internal:4000
      - OPENAI_API_KEY=${LITELLM_API_KEY}
    volumes:
      - letta-data:/data
    restart: unless-stopped

volumes:
  letta-data:
```

**Notes**:
- `host.containers.internal` is Podman's equivalent of Docker's `host.docker.internal`.
- `${VAR}` references are read from `.env` file (standard compose behavior).
- `LOG_LEVEL=debug` for local development.

---

### Step 9 — Deployment Stubs

**Create**: `/workspace/deployment/helm/.gitkeep` — Empty file.
**Create**: `/workspace/deployment/kustomize/.gitkeep` — Empty file.

These directories are populated in Phase 3D.

---

### Step 10 — Script Stubs

**Create**: `/workspace/scripts/seed-knowledge.py`

```python
#!/usr/bin/env python3
"""Seed archival memory with initial documentation and FAQ content.

Usage:
    python scripts/seed-knowledge.py [--path PATH]

Loads documentation files from the specified path (or MEMORY_SEED_PATH
environment variable) and inserts them into the agent's archival memory
via the Letta API.

Implemented in Phase 4C.
"""


def main() -> None:
    """Entry point for knowledge seeding."""
    raise NotImplementedError("Knowledge seeding will be implemented in Phase 4C.")


if __name__ == "__main__":
    main()
```

**Create**: `/workspace/scripts/export-knowledge.py`

```python
#!/usr/bin/env python3
"""Export learned knowledge from agent memory for human review.

Usage:
    python scripts/export-knowledge.py [--output PATH]

Exports the agent's core memory blocks and archival memory entries
to files for admin review and auditing.

Implemented in Phase 4C.
"""


def main() -> None:
    """Entry point for knowledge export."""
    raise NotImplementedError("Knowledge export will be implemented in Phase 4C.")


if __name__ == "__main__":
    main()
```

---

### Step 11 — CI Pipeline

**Create**: `/workspace/.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

permissions:
  contents: read

jobs:
  lint:
    name: Lint & Format
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Ruff check
        run: uv run ruff check src/ tests/

      - name: Ruff format check
        run: uv run ruff format --check src/ tests/

  type-check:
    name: Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Mypy
        run: uv run mypy src/

  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Run unit tests
        run: uv run pytest tests/unit/ -v --tb=short
```

**Notes**:
- Three parallel jobs for fast feedback.
- `astral-sh/setup-uv@v5` is the official action with built-in caching.
- `uv sync --extra dev` installs all deps including dev tools.
- Only `tests/unit/` runs in CI — integration and guardrail tests need live services.

---

### Step 12 — Update `.gitignore`

**Modify**: `/workspace/.gitignore` — Add these entries:

```
# Ruff
.ruff_cache/

# direnv
.direnv/
```

---

### Step 13 — Generate Lock File

After all files are created, run:

```bash
uv sync --extra dev
```

This generates `uv.lock` which should be committed to the repository for reproducible builds.

---

## File Manifest

| # | File | Type | Content |
|---|---|---|---|
| 1 | `pyproject.toml` | Config | Full project config (see Step 1) |
| 2 | `.python-version` | Config | `3.12` |
| 3 | `.envrc` | Config | direnv venv auto-activation |
| 4 | `src/agent/__init__.py` | Python | Empty |
| 5 | `src/agent/config.py` | Python | `Settings` class (pydantic-settings) |
| 6 | `src/agent/bootstrap.py` | Python | Docstring stub |
| 7 | `src/agent/persona.py` | Python | Docstring stub |
| 8 | `src/agent/memory_seeds.py` | Python | Docstring stub |
| 9 | `src/tools/__init__.py` | Python | Empty |
| 10 | `src/tools/litemaas.py` | Python | Docstring stub |
| 11 | `src/tools/litellm.py` | Python | Docstring stub |
| 12 | `src/tools/admin.py` | Python | Docstring stub |
| 13 | `src/tools/docs.py` | Python | Docstring stub |
| 14 | `src/guardrails/__init__.py` | Python | Empty |
| 15 | `src/guardrails/rails.py` | Python | Docstring stub |
| 16 | `src/guardrails/actions.py` | Python | Docstring stub |
| 17 | `src/guardrails/config/config.yml` | YAML | Minimal NeMo config |
| 18 | `src/guardrails/config/topics.co` | Colang | Comment stub |
| 19 | `src/guardrails/config/privacy.co` | Colang | Comment stub |
| 20 | `src/guardrails/config/safety.co` | Colang | Comment stub |
| 21 | `src/guardrails/config/prompts.yml` | YAML | Comment stub |
| 22 | `src/proxy/__init__.py` | Python | Empty |
| 23 | `src/proxy/server.py` | Python | FastAPI app + `/v1/health` |
| 24 | `src/proxy/auth.py` | Python | Docstring stub |
| 25 | `src/proxy/routes.py` | Python | Docstring stub |
| 26 | `src/adapters/__init__.py` | Python | Empty |
| 27 | `src/adapters/base.py` | Python | Docstring stub |
| 28 | `src/adapters/litemaas.py` | Python | Docstring stub |
| 29 | `tests/__init__.py` | Python | Empty |
| 30 | `tests/unit/__init__.py` | Python | Empty |
| 31 | `tests/unit/conftest.py` | Python | `client` fixture |
| 32 | `tests/unit/test_health.py` | Python | Health endpoint tests |
| 33 | `tests/integration/__init__.py` | Python | Empty |
| 34 | `tests/integration/conftest.py` | Python | Placeholder with docstring |
| 35 | `tests/guardrails/__init__.py` | Python | Empty |
| 36 | `tests/guardrails/conftest.py` | Python | Placeholder with docstring |
| 37 | `.env.example` | Config | All env vars documented |
| 38 | `Containerfile` | Container | Multi-stage build |
| 39 | `compose.yaml` | Config | proxy + Letta services |
| 40 | `deployment/helm/.gitkeep` | Marker | Empty |
| 41 | `deployment/kustomize/.gitkeep` | Marker | Empty |
| 42 | `scripts/seed-knowledge.py` | Python | Stub with `NotImplementedError` |
| 43 | `scripts/export-knowledge.py` | Python | Stub with `NotImplementedError` |
| 44 | `.github/workflows/ci.yml` | YAML | CI pipeline |

**Modified**: `.gitignore` — add `.ruff_cache/` and `.direnv/` entries.

**Generated**: `uv.lock` — created by `uv sync`, committed to repo.

---

## Implementation Notes

### NeMo Guardrails C++ dependency

`nemoguardrails` depends on `annoy` which requires a C++ compiler. The Containerfile builder stage includes `apt-get install build-essential` to handle this. The runtime stage does NOT need it — only the compiled `.so` files are carried over in the venv.

### `uv.lock` must be committed

The lockfile is generated on first `uv sync --extra dev` and must be committed. It ensures CI and container builds get exactly the same dependency versions.

### `PYTHONPATH` in development vs. container

- **Container**: `ENV PYTHONPATH="/app/src"` in the Containerfile.
- **Local dev**: `uv` handles this automatically — `pyproject.toml` uses src-layout and hatchling discovers packages in `src/`.

### Mypy strict mode

Python files with functions must include:
- `from __future__ import annotations` at the top
- Type annotations on all function signatures

Files with only a module docstring and no functions need neither the import nor annotations.

### Health endpoint independence

`src/proxy/server.py` does NOT import `Settings` or attempt to connect to Letta. This is intentional — the health endpoint must work without environment variables set, making container startup and probe validation simpler. Full `Settings` wiring happens in Phase 1C.

### Podman networking

`host.containers.internal` in `compose.yaml` is Podman's equivalent of Docker's `host.docker.internal`. It resolves to the host machine, allowing containers to reach LiteMaaS and LiteLLM services running on the host.

---

## Verification

Run these checks in order after implementation:

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Lint
uv run ruff check src/ tests/

# 3. Format
uv run ruff format --check src/ tests/

# 4. Type check
uv run mypy src/

# 5. Unit tests
uv run pytest tests/unit/ -v

# 6. Container build
podman build -t litemaas-agent -f Containerfile .

# 7. Container run + health check
podman run --rm -d -p 8400:8400 --name agent-test litemaas-agent
curl -s http://localhost:8400/v1/health
# Expected: {"status":"healthy"}
podman stop agent-test

# 8. Full stack
podman-compose up -d
curl -s http://localhost:8400/v1/health
# Expected: {"status":"healthy"}
podman-compose down
```

All eight checks must pass for Phase 0 to be considered complete.
