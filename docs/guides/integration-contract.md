# Integration Contract — LiteMaaS Agent Assistant

API contract for the LiteMaaS backend and frontend teams to integrate with the agent assistant proxy.

## Backend Routes

The LiteMaaS backend should add a thin proxy at `/api/v1/assistant/*` that forwards to the agent container:

| Backend Route | Agent Route | Method | Notes |
|---|---|---|---|
| `POST /api/v1/assistant/chat` | `POST /v1/chat` | Forward | JSON request/response |
| `POST /api/v1/assistant/chat/stream` | `POST /v1/chat/stream` | Forward SSE | Stream `text/event-stream` response body |
| `GET /api/v1/assistant/health` | `GET /v1/health` | Forward | JSON response |

**Auth**: Forward the `Authorization: Bearer <jwt>` header as-is. The agent proxy validates the JWT independently using the same `JWT_SECRET`.

**Feature flag**: Routes should only be registered when `AGENT_URL` environment variable is configured.

## SSE Protocol

```
data: {"chunk": "Hello, how can I", "index": 0}
data: {"chunk": " help you today?", "index": 1}
data: {"retract_chunk": 2, "placeholder": "...removed..."}
data: {"done": true, "conversation_id": "conv-uuid", "safety_notice": "Part of this response has been removed for safety reasons."}
```

Blocked chunks are never emitted as text. Only a `retract_chunk` placeholder is sent — the client never sees the unsafe content.

If input rails block the message, no SSE stream is started. The response is a JSON body (`application/json`) with `{"message": "...", "conversation_id": null, "blocked": true}`, identical to `/v1/chat` blocked responses. Clients distinguish by content-type.

| Event | Fields | Description |
|---|---|---|
| `chunk` | `chunk: str`, `index: int` | Safe text chunk with sequential index |
| `retract_chunk` | `retract_chunk: int`, `placeholder: str` | A chunk at this index was withheld (unsafe content never sent) |
| `error` | `error: str`, `retryable: bool` | Agent or stream error; `retryable` hints whether the client should retry |
| `done` | `done: true`, `conversation_id: str`, `safety_notice: str\|null` | Stream complete. Always sent as the final event (even after errors). |

## Error Responses

| Status | Cause |
|---|---|
| `401` | Missing/invalid/expired JWT |
| `403` | Conversation doesn't belong to user |
| `422` | Invalid request body |
| `429` | Rate limit exceeded (check `Retry-After` header) |
| `502` | Agent/Letta unreachable |
| `503` | Guardrails not initialized |

## Frontend Widget

- Use `fetch()` + `ReadableStream` for POST-based SSE (not `EventSource`)
- Track chunk indices for retract UX (replace content at retracted index with placeholder)
- Show safety notice at end of message if `safety_notice` is non-null
- Disable input during streaming via `MessageBar.isDisabled`
- Health check: `GET /api/v1/assistant/health` on mount; disable floating button if unhealthy
