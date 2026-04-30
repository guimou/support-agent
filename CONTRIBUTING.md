# Contributing to LiteMaaS Agent Assistant

Thank you for your interest in contributing! This guide covers the essentials for getting started.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Podman](https://podman.io/) or [Docker](https://www.docker.com/) with Compose
- A running LiteMaaS instance (for integration testing)
- A running LiteLLM proxy with at least two models configured

## Getting Started

1. Fork and clone the repository
2. Follow the [Developer Guide](docs/guides/developer-guide.md) for full setup instructions
3. Copy `.env.example` to `.env` and fill in your values
4. Install dependencies: `uv sync --extra dev`
5. Start the stack: `podman-compose up`

## Development Workflow

### Branching

- `feature/*` — new functionality
- `fix/*` — bug fixes
- `docs/*` — documentation changes

### Commit Messages

Use imperative mood, ~50 character subject line:

```
Add rate limiting to chat endpoint
Fix JWT validation for expired tokens
Update guardrails configuration reference
```

### Pull Requests

- Keep PRs focused — one logical change per PR
- Include a clear description of what changed and why
- Ensure all checks pass (lint, type check, tests)
- Link to related issues if applicable

## Code Standards

### Linting and Formatting

```bash
uv run ruff check src/ tests/       # Lint
uv run ruff format --check src/ tests/  # Format check
uv run mypy src/                     # Type check
```

All three must pass before merging. CI runs them automatically.

### Testing

```bash
uv run pytest tests/unit/ -v                         # Unit tests
uv run pytest tests/guardrails/ -v -m guardrails     # Guardrail scenarios
uv run pytest tests/integration/ -v -m integration   # Integration (requires Letta)
```

PRs that add or modify functionality should include tests.

## Security Invariants

Before contributing code that touches tools, auth, or guardrails, read the [Security Policy](SECURITY.md). The six non-negotiable invariants are:

1. **Tools are read-only** — only `GET` requests, no mutations
2. **`user_id` comes from JWT, never from LLM** — tools read `os.getenv("LETTA_USER_ID")`
3. **Admin tools are role-gated** — runtime `LETTA_USER_ROLE == "admin"` check
4. **Scoped tokens** — standard tools use `LITELLM_USER_API_KEY`; admin tools use `LITELLM_API_KEY`
5. **Memory writes are PII-audited** — no user-identifying data in shared memory
6. **Guardrails fail closed** — uncertain classifications are refused

## Adding a New Tool

1. Create a plain Python function in `src/tools/` (no decorator — tools are registered via `client.tools.upsert_from_function()`)
2. Ensure the function is **self-contained** (inline all imports — tools run inside Letta)
3. Use `os.getenv("LETTA_USER_ID")` for user identity (never as a function parameter)
4. Use only `GET` requests (document any exceptions)
5. Register the tool in `src/agent/bootstrap.py`
6. Add unit tests in `tests/unit/`
7. Update `docs/reference/tools.md`

## Adding a Guardrail Rule

1. Write Colang rules in `src/guardrails/config/`
2. Add test scenarios in `tests/guardrails/`
3. Test with adversarial variants (rephrasing, encoding tricks)
4. Update `docs/reference/guardrails.md`

## Documentation

When your change affects behavior:

- **New tool** → update `docs/reference/tools.md`
- **New guardrail rule** → update `docs/reference/guardrails.md`
- **Config changes** → update `docs/reference/configuration.md`
- **API changes** → update `docs/reference/api.md`
- **Architecture changes** → update relevant doc in `docs/architecture/`

## Questions?

Open an issue for questions, bug reports, or feature suggestions.
