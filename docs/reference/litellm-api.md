# LiteLLM API Reference

The agent calls LiteLLM directly for model health checks, model configuration, and rate limit status. These endpoints are served by the monitored LiteLLM proxy (separate from LiteMaaS backend).

## Common Patterns

**Authentication header**: LiteLLM uses a custom header (not the standard `Authorization: Bearer`):
```
x-litellm-api-key: <API key>
```

**Base URL**: Configured via `LITELLM_API_URL` environment variable.

**Important quirks**:
- The sentinel value `2147483647` (max int32) means "unlimited" for TPM/RPM fields
- Response shapes can differ between LiteLLM versions — the agent handles both formats where noted
- Some error responses return HTTP 200 with error details in the body

---

## Health Check

### `GET /health/liveness`

**Agent tool**: `check_model_health()`
**Headers**: `x-litellm-api-key` (optional for the endpoint, but the agent always sends it)

**Response** (JSON format):
```json
{
  "status": "healthy",
  "db": "connected",
  "redis": "connected",
  "litellm_version": "1.81.0"
}
```

**Alternative response** (plain text, v1.81.0+): Some versions return just `I'm alive!` as plain text.

> **Implementation note**: The agent tool handles both JSON and plain text responses. A plain text "I'm alive!" response is treated as `healthy`.

**Status values**: `healthy`, `unhealthy`, `degraded`

---

## Model Information

### `GET /model/info`

**Agent tool**: `get_model_info()`
**Headers**: `x-litellm-api-key: <API key>`

**Response**:
```json
{
  "data": [
    {
      "model_name": "gpt-4o",
      "litellm_params": {
        "model": "openai/gpt-4o",
        "api_base": "https://api.openai.com",
        "custom_llm_provider": "openai",
        "input_cost_per_token": 0.0025,
        "output_cost_per_token": 0.01,
        "tpm": 2000000,
        "rpm": 10000
      },
      "model_info": {
        "id": "unique-model-id",
        "max_tokens": 128000,
        "supports_vision": true,
        "supports_function_calling": true
      }
    }
  ]
}
```

**Key fields**:
- `model_name` — The name users reference when subscribing
- `litellm_params.model` — The actual model identifier sent to the provider
- `litellm_params.tpm` / `rpm` — Configured rate limits (sentinel `2147483647` = unlimited)
- `model_info.max_tokens` — Maximum context length

> **Cache note**: LiteMaaS caches this endpoint for 5 minutes. The agent may see stale data if models were just added/removed.

---

## API Key Information

### `GET /key/info`

**Agent tool**: `check_rate_limits()`
**Headers**: `x-litellm-api-key: <the specific API key to query>`

**Response** (v1.81.0+ — nested format):
```json
{
  "key": "sk-litellm-xxxxx",
  "info": {
    "key_name": "sk-...xxxx",
    "spend": 25.50,
    "max_budget": 100.00,
    "models": ["gpt-4o", "claude-3-5-sonnet"],
    "tpm_limit": 10000,
    "rpm_limit": 100,
    "budget_duration": "monthly",
    "budget_reset_at": "2026-05-01T00:00:00Z",
    "model_spend": { "gpt-4o": 15.00 },
    "blocked": false
  }
}
```

**Response** (older versions — flat format):
```json
{
  "key_name": "sk-...xxxx",
  "spend": 25.50,
  "max_budget": 100.00,
  "tpm_limit": 10000,
  "rpm_limit": 100
}
```

> **Version handling**: The agent normalizes with `data.get("info", data)` to handle both formats.

**Key fields**:
- `spend` / `max_budget` — Budget utilization (common cause of key failures)
- `tpm_limit` / `rpm_limit` — Rate limits (sentinel `2147483647` = unlimited)
- `blocked` — Whether the key is blocked
- `budget_reset_at` — When the budget resets
- `model_spend` — Per-model spend breakdown

---

## User Information

### `GET /user/info`

**Headers**: `x-litellm-api-key: <API key>`
**Query Parameters**: `user_id=<user-id>`

```json
{
  "user_id": "user-123",
  "user_alias": "alice",
  "user_email": "alice@example.com",
  "max_budget": 500.00,
  "spend": 125.50,
  "models": ["gpt-4o", "claude-3-5-sonnet"],
  "tpm_limit": 10000,
  "rpm_limit": 500
}
```

> **Detection quirk**: For non-existent users, older LiteLLM versions return HTTP 200 with an empty `teams` array. v1.81.0+ returns HTTP 404.
