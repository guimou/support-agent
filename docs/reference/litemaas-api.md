# LiteMaaS API Reference

These are the endpoints the agent's read-only tools call. All responses use JSON.

## Common Patterns

**Authentication header** (for authenticated endpoints):
```
Authorization: Bearer <JWT token>
```

**Pagination response format** (all list endpoints):
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 42,
    "totalPages": 3
  }
}
```

**Date format**: ISO 8601 (`2026-04-27T14:30:00Z`)

**Null handling**: Budget/limit fields can be `null` (meaning unlimited) or a number.

---

## Models API

### `GET /api/v1/models` — List All Models

**Authentication**: Not required (public endpoint)
**Agent tool**: `list_models()`

**Query Parameters**:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | number | 1 | Page number (min: 1) |
| `limit` | number | 20 | Results per page (1-1000) |
| `search` | string | -- | Filter by model name, provider, or description |
| `provider` | string | -- | Filter by provider (e.g., `openai`, `anthropic`) |
| `capability` | string | -- | Filter by capability (e.g., `vision`, `function_calling`) |
| `isActive` | boolean | -- | Filter by active status |

**Response** (key fields for the agent):

```json
{
  "data": [
    {
      "id": "string",
      "name": "gpt-4o",
      "provider": "openai",
      "description": "GPT-4o multimodal model",
      "isActive": true,
      "restrictedAccess": false,
      "inputCostPerToken": 0.0025,
      "outputCostPerToken": 0.01,
      "maxTokens": 128000,
      "tpm": 2000000,
      "rpm": 10000,
      "supportsVision": true,
      "supportsFunctionCalling": true,
      "supportsChat": true,
      "supportsEmbeddings": false,
      "backendModelName": "openai/gpt-4o"
    }
  ],
  "pagination": { ... }
}
```

- `restrictedAccess` — If `true`, users need admin approval to subscribe
- `isActive` — If `false`, the model is disabled

### `GET /api/v1/models/:id` — Get Model Details

**Authentication**: Not required

Same shape as a single item from the list endpoint, with additional `metadata` wrapper.

---

## Subscriptions API

### `GET /api/v1/subscriptions` — List User's Subscriptions

**Authentication**: Required (user JWT)
**Agent tool**: `check_subscription()`

**Query Parameters**:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | number | 1 | Page number |
| `limit` | number | 20 | Results per page (1-100) |
| `status` | string | -- | Filter: `active`, `suspended`, `cancelled`, `expired`, `inactive`, `pending`, `denied` |
| `modelId` | string | -- | Filter by model ID |

**Response**:

```json
{
  "data": [
    {
      "id": "uuid",
      "userId": "uuid",
      "modelId": "gpt-4o",
      "modelName": "GPT-4o",
      "provider": "openai",
      "status": "active",
      "quotaRequests": 10000,
      "quotaTokens": 1000000,
      "usedRequests": 2500,
      "usedTokens": 250000,
      "remainingRequests": 7500,
      "remainingTokens": 750000,
      "utilizationPercent": { "requests": 25, "tokens": 25 },
      "resetAt": "2026-05-01T00:00:00Z",
      "expiresAt": null
    }
  ],
  "pagination": { ... }
}
```

- `status` — `pending` / `denied` are for restricted models awaiting approval
- `utilizationPercent` — Quick read on quota usage
- `resetAt` — When quota resets (`null` = never)

### `GET /api/v1/subscriptions/stats` — Subscription Statistics

**Authentication**: Required (user JWT)

Returns aggregate stats: total count, by-status breakdown, by-provider breakdown, total quota usage.

---

## API Keys API

### `GET /api/v1/api-keys` — List User's API Keys

**Authentication**: Required (user JWT)
**Agent tool**: `get_user_api_keys()`

> **Security**: Returns key **prefixes** (`sk-...1234`), never full key values.

**Response** (key fields for the agent):

```json
{
  "data": [
    {
      "id": "uuid",
      "name": "My Production Key",
      "prefix": "sk-...a1b2",
      "models": ["gpt-4o", "claude-3-5-sonnet"],
      "isActive": true,
      "lastUsedAt": "2026-04-25T14:30:00Z",
      "expiresAt": "2027-03-01T10:00:00Z",
      "revokedAt": null,
      "maxBudget": 100.0,
      "currentSpend": 25.5,
      "budgetDuration": "monthly",
      "syncStatus": "synced",
      "syncError": null
    }
  ],
  "pagination": { ... }
}
```

- `maxBudget` / `currentSpend` — Budget usage (common cause of "key stopped working")
- `expiresAt` — Key expiration (`null` = no expiry)
- `revokedAt` — Non-null means key is revoked
- `syncStatus` — Whether synced with LiteLLM (`synced`, `pending`, `error`)

---

## Usage API

### `GET /api/v1/usage/budget` — User Budget Info

**Authentication**: Required (user JWT)
**Agent tool**: `get_usage_stats()`

```json
{
  "maxBudget": 1000.0,
  "currentSpend": 250.5,
  "budgetDuration": "monthly",
  "budgetResetAt": "2026-05-01T00:00:00Z"
}
```

`maxBudget` and `budgetResetAt` can be `null` (unlimited / no reset).

### `GET /api/v1/usage/summary` — Usage Summary

**Authentication**: Required (user JWT)
**Agent tool**: `get_usage_stats()`

**Query Parameters**: `startDate`, `endDate` (required, YYYY-MM-DD), `modelId` (optional), `granularity` (optional: `hour`, `day`, `week`, `month`)

```json
{
  "totals": {
    "requests": 5000,
    "tokens": 500000,
    "cost": 15.50,
    "successRate": 98.5,
    "averageLatency": 245
  },
  "byModel": [
    { "modelId": "gpt-4o", "modelName": "GPT-4o", "requests": 3000, "cost": 10.0 }
  ]
}
```

---

## Admin Endpoints

These require a JWT with the `admin` role.

### `GET /api/v1/admin/users/:id` — Get User Details

**Agent tool**: `lookup_user_subscriptions()`

Returns user profile with budget, limits, subscription/key counts, and last activity.

### `GET /api/v1/admin/users/:id/subscriptions` — User Subscriptions

**Agent tool**: `lookup_user_subscriptions()`

Same shape as `GET /api/v1/subscriptions` but for the target user.

### `POST /api/v1/admin/usage/analytics` — Global Usage Analytics

**Agent tool**: `get_global_usage_stats()`

> **Note**: POST because it accepts complex filter arrays in the body. No data is mutated.

**Request Body** (all fields optional):
```json
{
  "startDate": "2026-04-01",
  "endDate": "2026-04-27",
  "userIds": ["user-id-1"],
  "modelIds": ["gpt-4o"],
  "providerIds": ["openai"]
}
```

Returns totals (requests, tokens, cost, success rate), model breakdown, and provider breakdown.

### `GET /api/v1/admin/subscriptions/stats` — Approval Queue Statistics

Returns pending count, approved/denied today, and total requests.

---

## Data Models

### Model

Key fields: `id`, `name`, `provider`, `isActive`, `restrictedAccess`, capabilities (`supportsChat`, `supportsVision`, `supportsFunctionCalling`), pricing (`inputCostPerToken`, `outputCostPerToken`), limits (`maxTokens`, `tpm`, `rpm`), `backendModelName`.

### Subscription

Key fields: `userId`, `modelId`, `status` (7 possible values), quota (`quotaRequests`, `quotaTokens`, `usedRequests`, `usedTokens`, `remainingRequests`, `remainingTokens`, `utilizationPercent`), dates (`resetAt`, `expiresAt`).

### API Key

Key fields: `name`, `prefix` (never full key), `models`, `isActive`, `revokedAt`, budget (`maxBudget`, `currentSpend`, `budgetDuration`), rate limits (`tpmLimit`, `rpmLimit`), `syncStatus`.

### User (Admin View)

Key fields: `id`, `username`, `email`, `roles`, budget, limits, `subscriptionCount`, `apiKeyCount`, `lastActive`.
