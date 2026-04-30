# Tool Catalog

The agent has 10 registered tools: 7 standard (any user), 2 admin (role-gated), and 1 placeholder.

## Security Properties

All tools enforce these invariants:

- **Read-only** — `GET` requests only (one [documented exception](#get_global_usage_stats))
- **User identity from JWT** — tools read `os.getenv("LETTA_USER_ID")`, never accept `user_id` as a function parameter
- **Scoped tokens** — standard tools use `LITELLM_USER_API_KEY` (read-only); admin tools use `LITELLM_API_KEY` (master key, injected only for admin requests)
- **Admin role validation** — admin tools check `os.getenv("LETTA_USER_ROLE") == "admin"` before executing

## Execution Model

Tools are plain Python functions registered with Letta via `client.tools.upsert_from_function()` at bootstrap. They **execute inside Letta's process**, not the proxy. This means:

- Functions must be **self-contained** — all imports inline, no cross-module imports
- Configuration via `os.getenv()` — API URLs, keys, user identity from environment
- Dependencies must exist in Letta's image (`httpx` is available in the stock `letta/letta` image)
- Secrets are injected via Letta's per-conversation secrets mechanism

---

## Standard Tools

### `list_models(search="")`

List models available on the platform.

| | |
|---|---|
| **API** | `GET {LITEMAAS_API_URL}/api/v1/models` |
| **Auth** | None (public endpoint) |
| **Parameters** | `search` — optional filter string |
| **Returns** | Model name, provider, status, restricted flag |

### `check_subscription(model_name)`

Check the user's subscription status for a specific model.

| | |
|---|---|
| **API** | `GET {LITEMAAS_API_URL}/api/v1/subscriptions` |
| **Auth** | Bearer `LITELLM_USER_API_KEY` |
| **Parameters** | `model_name` — case-insensitive partial match |
| **Returns** | Status, quota usage, reset date |
| **User scoped** | Filters by `LETTA_USER_ID` |

### `get_user_api_keys()`

List the user's API keys (names and status, never full key values).

| | |
|---|---|
| **API** | `GET {LITEMAAS_API_URL}/api/v1/api-keys` |
| **Auth** | Bearer `LITELLM_USER_API_KEY` |
| **Returns** | Key names, prefixes, status, budget, sync status, models, expiration |
| **User scoped** | Filters by `LETTA_USER_ID` |

### `get_usage_stats()`

Get the user's usage statistics.

| | |
|---|---|
| **API** | `GET {LITEMAAS_API_URL}/api/v1/usage/budget` + `GET /api/v1/usage/summary` |
| **Auth** | Bearer `LITELLM_USER_API_KEY` |
| **Returns** | Total spend, budget, 30-day usage, per-model breakdown |
| **User scoped** | Filters by `LETTA_USER_ID` |

### `check_model_health()`

Check if LiteLLM is healthy and responding.

| | |
|---|---|
| **API** | `GET {LITELLM_API_URL}/health/liveness` |
| **Auth** | `x-litellm-api-key` header |
| **Returns** | LiteLLM status and version |
| **Quirk** | Handles both JSON and plain text `I'm alive!` responses |

### `get_model_info(model_name="")`

Get model configuration details.

| | |
|---|---|
| **API** | `GET {LITELLM_API_URL}/model/info` |
| **Auth** | `x-litellm-api-key` header |
| **Parameters** | `model_name` — optional filter |
| **Returns** | Provider, backend model, max_tokens, TPM/RPM limits, capabilities |
| **Quirk** | Sentinel `2147483647` means "unlimited" for TPM/RPM |

### `check_rate_limits()`

Check rate limit status for the user's API key.

| | |
|---|---|
| **API** | `GET {LITELLM_API_URL}/key/info` |
| **Auth** | `x-litellm-api-key` header |
| **Returns** | Budget, spend, TPM/RPM limits, per-model spend breakdown |
| **Quirk** | Response can be nested (`data.info.*`) or flat — normalized with `data.get("info", data)` |

---

## Admin Tools

### `get_global_usage_stats()`

Get system-wide usage statistics.

| | |
|---|---|
| **API** | `POST {LITEMAAS_API_URL}/api/v1/admin/usage/analytics` |
| **Auth** | Bearer `LITELLM_API_KEY` (master key) |
| **Role check** | `LETTA_USER_ROLE == "admin"` |
| **Returns** | Global request count, tokens, cost, success rate, top models |
| **Note** | POST is required for complex filter body — **no data is mutated** |

### `lookup_user_subscriptions(target_user_id)`

Look up any user's subscriptions.

| | |
|---|---|
| **API** | `GET {LITEMAAS_API_URL}/api/v1/admin/users/{id}/subscriptions` |
| **Auth** | Bearer `LITELLM_API_KEY` (master key) |
| **Role check** | `LETTA_USER_ROLE == "admin"` |
| **Parameters** | `target_user_id` — UUID, validated with regex |
| **Returns** | All subscriptions for the specified user |

---

## Placeholder

### `search_docs(query)`

Currently returns a suggestion to use Letta's built-in `archival_memory_search` tool. Will be enhanced in Phase 4 with external documentation search.

---

## Adding a New Tool

1. Create a plain Python function in `src/tools/`
2. Make it **self-contained**: inline all imports (`import os`, `import httpx`)
3. Read user identity from `os.getenv("LETTA_USER_ID")` — never as a parameter
4. Use only `GET` requests (document exceptions)
5. If admin-only, add inline `LETTA_USER_ROLE == "admin"` check (see `src/tools/admin.py` for pattern)
6. Register in `src/agent/bootstrap.py` (add to the `all_tools` list in `_register_tools()`)
7. Write unit tests in `tests/unit/`
8. Update this document

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full checklist.
