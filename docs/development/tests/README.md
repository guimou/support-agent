# Manual Testing — Dev Environment Setup

How to set up a local dev environment and run the manual test suite
against a running LiteMaaS Agent Assistant.

## Prerequisites

- **Podman** with `podman-compose` (or Docker Compose)
- **Python 3.12+** with `PyJWT` installed (`pip install pyjwt`)
- **curl** and **jq**
- A running **LiteMaaS backend** (port 8081) and **LiteLLM proxy** (port 4000),
  or remote equivalents

## Environment File

```bash
cp .env.example .env
# Fill in all required values (see .env.example comments)
```

Key variables for local testing:

| Variable | Local value | Notes |
|---|---|---|
| `LITEMAAS_API_URL` | `http://host.containers.internal:8081` | LiteMaaS backend, NOT the Vite dev server (3000) |
| `LITELLM_API_URL` | `http://host.containers.internal:4000` | LiteLLM proxy |
| `JWT_SECRET` | must match LiteMaaS `JWT_SECRET` | HS256 shared secret, min 16 chars |
| `LETTA_SERVER_URL` | `http://letta:8283` | Container-to-container, keep as-is |

If you have multiple `.env` files (e.g., local vs. remote), rename the inactive
one (e.g., `.env.remote`) since compose always auto-loads `.env` in addition
to any `--env-file` flag.

## Container Networking

**From outside containers** (curl, tests, browser), reach services at
`host.containers.internal`, **not** `localhost`:

| Service | URL from host |
|---|---|
| Proxy | `http://host.containers.internal:8400` |
| Letta | `http://host.containers.internal:8283` |
| LiteMaaS backend | `http://localhost:8081` (runs on host) |
| LiteLLM | `http://localhost:4000` (runs on host) |

**From inside containers**, reach host services at `host.containers.internal`.
This is why `LITEMAAS_API_URL` and `LITELLM_API_URL` use that hostname.

**LiteMaaS backend must bind `0.0.0.0`** (not `127.0.0.1`) so containers
can reach it via `host.containers.internal`. Same for LiteLLM.

## Port Map

| Port | Service | Notes |
|---|---|---|
| 3000 | Vite dev server (LiteMaaS frontend) | Proxies `/api/` to backend on 8081 |
| 4000 | LiteLLM proxy | Model gateway |
| 8081 | LiteMaaS backend (Express/Node) | The real API — use this, not 3000 |
| 8283 | Letta agent runtime | Agent reasoning + tools |
| 8400 | Agent proxy (this project) | Auth, guardrails, streaming |

## Starting the Service

```bash
# First time or after code/dependency changes:
podman-compose up --build

# Subsequent starts (env-only changes don't need --build):
podman-compose up
```

### Dev overlay (live-reload + log files)

```bash
cp compose.override.yaml.example compose.override.yaml
chmod 777 logs/    # Container runs as UID 1001, needs write access
podman-compose up  # override applied automatically
```

Log files appear in `logs/agent.log` and `logs/letta.log`.

### Verifying the service is ready

```bash
curl -s http://host.containers.internal:8400/v1/health | jq .
# Expected: {"status": "healthy", ...}
```

Wait for Letta to finish bootstrapping (check `logs/letta.log` for
`Agent bootstrap complete` or similar).

## Running the Tests

```bash
# Make executable (once)
chmod +x docs/development/tests/manual_tests.sh

# Run all tests
./docs/development/tests/manual_tests.sh

# Override proxy URL if needed
PROXY_URL=http://localhost:8400 ./docs/development/tests/manual_tests.sh
```

The script reads `JWT_SECRET` from the environment or falls back to the
default dev secret. It generates short-lived JWT tokens on the fly.

## Test Categories

| Category | Tests | Deterministic? |
|---|---|---|
| Health check | 1 | Yes |
| Auth validation | 8–10, 15–16 | Yes |
| Input guardrails | 5–7 | LLM-dependent |
| On-topic chat | 2–4 | LLM-dependent |
| Streaming | 11 | LLM-dependent |
| Admin tools | 12–13 | LLM-dependent |
| Rate limiting | 14 | Yes |

**Deterministic** tests always produce the same result. **LLM-dependent**
tests rely on the guardrails model for classification — occasional
misclassifications are expected and should be investigated, not ignored.

## Troubleshooting

**"Connection refused" on port 8400**
→ Service isn't running. Check `podman-compose up` output.

**"Permission denied" writing log files**
→ Run `chmod 777 logs/` on the host.

**Tools return "LITEMAAS_API_URL not set"**
→ Env var not reaching the container. Check `.env` file and `compose.yaml`
  interpolation. Run `podman-compose config` to verify resolved values.

**LiteMaaS tools fail with connection errors**
→ Backend must bind `0.0.0.0`, not `127.0.0.1`. Verify with:
  `curl http://host.containers.internal:8081/api/v1/models?limit=1`

**JWT secret mismatch (401 on valid-looking tokens)**
→ `JWT_SECRET` in `.env` must match the LiteMaaS instance you're testing
  against. After changing it, restart the containers (the auth config is
  cached and survives live-reload).
