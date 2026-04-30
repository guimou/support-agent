# Frontend Integration

This guide covers integrating the agent assistant into the LiteMaaS frontend, including the widget component, SSE streaming, and backend proxy routes.

## Overview

The assistant is a **platform support agent** — separate from the Chat Playground (`/chatbot`). It appears as a floating panel on all pages.

| Aspect | Chat Playground (`/chatbot`) | Assistant Widget |
|---|---|---|
| **Purpose** | Direct model interaction | Platform support |
| **Model selection** | User selects model + API key | Fixed (agent backend) |
| **Backend** | LiteLLM directly | Agent proxy -> Letta |
| **SSE format** | OpenAI-compatible chunks | Custom: `chunk`, `retract_chunk`, `done` |
| **Guardrails** | None | Input/output rails with retract UX |
| **Position** | Full page (`/chatbot` route) | Floating panel (all pages) |
| **Feedback** | None | Thumbs up/down per response |

## PatternFly Chatbot Component

**Package**: `@patternfly/chatbot` (already installed in LiteMaaS)

**Import style**: Dynamic imports from `@patternfly/chatbot/dist/dynamic/*`:

```typescript
import Chatbot, { ChatbotDisplayMode } from '@patternfly/chatbot/dist/dynamic/Chatbot';
import ChatbotContent from '@patternfly/chatbot/dist/dynamic/ChatbotContent';
import ChatbotHeader from '@patternfly/chatbot/dist/dynamic/ChatbotHeader';
import ChatbotFooter from '@patternfly/chatbot/dist/dynamic/ChatbotFooter';
import MessageBar from '@patternfly/chatbot/dist/dynamic/MessageBar';
import MessageBox from '@patternfly/chatbot/dist/dynamic/MessageBox';
import Message from '@patternfly/chatbot/dist/dynamic/Message';
import ChatbotWelcomePrompt from '@patternfly/chatbot/dist/dynamic/ChatbotWelcomePrompt';
```

**Required CSS** (import once):
```typescript
import '@patternfly/chatbot/dist/css/main.css';
```

**Key patterns**:
- Role mapping: PF chatbot uses `"bot"` not `"assistant"` — map accordingly
- Loading state: Use `<Message isLoading />` for typing indicator
- Empty state: Use `<ChatbotWelcomePrompt>` when no messages
- Disable input during streaming via `MessageBar.isDisabled`

## Widget Layout

```
+-------------------------------------------+
|                 LiteMaaS UI               |
|                                           |
|   +-------------------------------+       |
|   |     Main Content Area         |       |
|   +-------------------------------+       |
|                                           |
|                            +------+       |
|                            |  Chat|       |  <-- Floating action button
|                            +--+---+       |
|                               |           |
|                  +------------v------+    |
|                  |  Chat Panel       |    |  <-- Slide-out panel
|                  |  Agent messages   |    |
|                  |  User messages    |    |
|                  |  [Type here]      |    |
|                  +-------------------+    |
+-------------------------------------------+
```

**Key UI behaviors:**
- **Feedback**: Thumbs up/down on each agent response
- **Conversation history**: Current session only (agent uses recall memory for past context)
- **Offline mode**: Floating button disabled/grayed out when agent is unreachable
- **Retract UX**: Unsafe chunks replaced with `...removed...`, safety notice at end

## SSE Streaming Protocol

The agent uses POST-based SSE (not EventSource). The client consumes via `fetch()` + `ReadableStream`:

```
data: {"chunk": "Hello, how can I", "index": 0}
data: {"chunk": " help you today?", "index": 1}
data: {"retract_chunk": 2, "placeholder": "...removed..."}
data: {"done": true, "safety_notice": null}
```

Key differences from OpenAI-compatible streaming:
- Chunks include an `index` field for retract UX
- `retract_chunk` events replace already-displayed chunks with a placeholder
- `done` event signals completion and may include a safety notice
- No `[DONE]` sentinel — instead a JSON object with `done: true`

### Streaming State

```typescript
interface StreamingState {
  isStreaming: boolean;
  streamingMessageId: string | null;
  streamingContent: string;
  abortController: AbortController | null;
}
```

When the user clicks "Stop", accumulated content is preserved (partial response stays visible).

## Message Structure

```typescript
interface ChatMessage {
  id: string;           // Format: "msg_<timestamp>_<random>"
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}
```

## API Client

**Non-streaming**: Use Axios with JWT interceptor (existing `apiClient`).

**Streaming**: Use raw `fetch()` (Axios doesn't support `ReadableStream`):

```typescript
const response = await fetch(`${baseUrl}/api/v1/assistant/chat/stream`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ message, conversation_id }),
  signal: abortController.signal,
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  // Parse SSE lines...
}
```

## Error Handling

```typescript
interface ChatError {
  type: 'api_error' | 'network_error' | 'validation_error'
      | 'rate_limit' | 'auth_error' | 'aborted';
  message: string;
  retryable: boolean;
}
```

Use the existing `useErrorHandler` hook for non-streaming errors. For `aborted` type, handle silently (user clicked stop).

## Internationalization

Use `useTranslation()` hook with keys under `pages.assistant`:

```json
{
  "pages": {
    "assistant": {
      "title": "Platform Assistant",
      "welcome": {
        "title": "Hi! I'm your LiteMaaS assistant",
        "description": "I can help with model subscriptions, API keys, usage, and troubleshooting."
      },
      "placeholder": "Ask me about LiteMaaS...",
      "unavailable": "The assistant is currently unavailable. Please try again later.",
      "safetyNotice": "Part of this response has been removed for safety reasons."
    }
  }
}
```

## LiteMaaS Backend Routes

### New Route: `/api/v1/assistant/*`

**File**: `backend/src/routes/assistant.ts`

A thin proxy that forwards requests to the agent container, passing through the user's JWT:

- `POST /api/v1/assistant/chat` — proxy to agent `/v1/chat`
- `POST /api/v1/assistant/chat/stream` — proxy SSE to agent `/v1/chat/stream`
- `GET /api/v1/assistant/health` — proxy to agent `/v1/health`

**Pattern**: Forward the `Authorization` header as-is. The agent proxy validates the JWT independently.

### Environment Variable

| Variable | Required | Default | Description |
|---|---|---|---|
| `AGENT_URL` | No | -- | Agent proxy base URL (e.g., `http://agent:8400`). If not set, assistant routes are not registered. |

### Feature Flag

Routes are only registered when `AGENT_URL` is configured:

```typescript
if (fastify.config.AGENT_URL) {
  fastify.register(assistantRoutes, { prefix: '/api/v1/assistant' });
}
```

### Frontend Health Check

The widget checks agent availability on mount:

```typescript
const checkAgentHealth = async () => {
  try {
    const response = await apiClient.get('/assistant/health');
    setAgentAvailable(response.status === 'healthy');
  } catch {
    setAgentAvailable(false);
  }
};
```

If unavailable, the floating button is disabled with tooltip: "The assistant is currently unavailable."
