# Proxy API Reference

The proxy server exposes the agent's functionality via a REST API. FastAPI auto-generates interactive docs at `/docs` (Swagger UI) and `/redoc` (ReDoc) when the server is running.

**Base URL**: `http://localhost:8400` (default)

## Endpoints

### `GET /v1/health`

Health check for container probes and frontend availability detection.

**Authentication**: Not required

**Response**:
```json
{
  "status": "healthy",
  "agent": "connected",
  "agent_id": "agent-uuid",
  "guardrails": "active"
}
```

| Field | Values | Description |
|---|---|---|
| `status` | `healthy`, `unhealthy` | Overall status |
| `agent` | `connected`, `disconnected` | Letta connection status |
| `agent_id` | UUID string or `null` | Bootstrapped agent identifier |
| `guardrails` | `active`, `disabled`, `failed` | Guardrails engine status |

### `POST /v1/chat`

Main chat endpoint. Processes a user message through input guardrails, the agent, and output guardrails.

**Authentication**: Required (JWT Bearer token)

**Request**:
```json
{
  "message": "Why can't I access the gpt-4o model?",
  "conversation_id": "optional-uuid"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | string | Yes | User message (max 4000 characters) |
| `conversation_id` | string | No | Existing conversation UUID. If omitted, creates new conversation |

**Response**:
```json
{
  "message": "Let me check your subscription status for gpt-4o...",
  "conversation_id": "conv-uuid",
  "blocked": false
}
```

| Field | Type | Description |
|---|---|---|
| `message` | string | Agent response (or refusal message if blocked) |
| `conversation_id` | string | Conversation UUID (use for follow-up messages) |
| `blocked` | boolean | `true` if guardrails blocked the message |

**Processing flow**:
1. Validate JWT and extract user context
2. Run input guardrails — if blocked, return refusal immediately
3. Inject user identity into Letta conversation secrets
4. Get or create conversation for this user
5. Send message to Letta agent
6. Extract assistant response
7. Run output guardrails — if blocked, return sanitized response

### `POST /v1/chat/stream` (Phase 2)

Streaming chat via SSE (Server-Sent Events) over POST.

Uses POST to avoid exposing message content in URLs/logs and to support messages up to 4000 characters. The client consumes via `fetch()` + `ReadableStream` (not `EventSource`).

**Authentication**: Required (JWT Bearer token)

**Request**: Same as `/v1/chat`

**Response**: `text/event-stream` with custom format:

```
data: {"chunk": "Hello, how can I", "index": 0}
data: {"chunk": " help you today?", "index": 1}
data: {"retract_chunk": 2, "placeholder": "...removed..."}
data: {"done": true, "conversation_id": "conv-uuid", "safety_notice": null}
```

If input rails block the message, no SSE stream is started. The response is a JSON body (`application/json`) with `{"message": "...", "conversation_id": null, "blocked": true}`, identical to `/v1/chat` blocked responses. Clients distinguish by content-type.

| Event | Fields | Description |
|---|---|---|
| `chunk` | `chunk: str`, `index: int` | Safe text chunk with sequential index |
| `retract_chunk` | `retract_chunk: int`, `placeholder: str` | A chunk at this index was withheld (unsafe content never sent) |
| `error` | `error: str`, `retryable: bool` | Agent or stream error; `retryable` hints whether the client should retry |
| `done` | `done: true`, `conversation_id: str`, `safety_notice: str\|null` | Stream complete. Always sent as the final event (even after errors). |

See [Frontend Integration](../guides/frontend-integration.md) for client implementation details.

## Error Responses

| Status | Cause |
|---|---|
| `401 Unauthorized` | Missing, invalid, or expired JWT |
| `403 Forbidden` | Conversation does not belong to this user |
| `422 Unprocessable Entity` | Invalid request body (missing `message`, etc.) |
| `429 Too Many Requests` | Rate limit exceeded (check `Retry-After` header) |
| `502 Bad Gateway` | Agent/Letta unreachable or failed to process |
| `503 Service Unavailable` | Guardrails not initialized |

## Rate Limiting

Per-user rate limiting at the proxy layer:
- `RATE_LIMIT_RPM` (default: 30) — max chat requests per user per minute
- `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` (default: 20) — max memory write operations per user per hour

## Auto-Generated Docs

When the server is running:
- **Swagger UI**: http://localhost:8400/docs
- **ReDoc**: http://localhost:8400/redoc
- **OpenAPI JSON**: http://localhost:8400/openapi.json
