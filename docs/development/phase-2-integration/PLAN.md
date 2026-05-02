# Phase 2 — Streaming & Integration: Detailed Implementation Plan

> **Goal**: SSE streaming works end-to-end. Admin tools are role-gated with rate limiting. Phase 1 carryover items are resolved.
> **Validation**: User interacts via `/v1/chat/stream` and receives incremental SSE chunks. Unsafe chunks are retracted in real-time. Admin-only tools are inaccessible to regular users. Rate-limited users receive 429 responses.
> **Parent plan**: [PROJECT_PLAN.md](../PROJECT_PLAN.md)
> **Architecture**: [Architecture Overview](../../architecture/overview.md) | [Security](../../architecture/security.md)
> **Reference**: [API](../../reference/api.md) | [Guardrails](../../reference/guardrails.md) | [Configuration](../../reference/configuration.md)

---

## Background

Phase 1 delivered the end-to-end agent flow: JWT auth, 10 tools (7 standard + 2 admin + 1 placeholder), NeMo Guardrails (input + output rails), and the `/v1/chat` non-streaming endpoint. All production code lives in `src/` (~1,400 lines across 5 packages). The test suite has 23 test files covering unit, integration, and guardrail scenarios.

**Two-container architecture** (unchanged):

| Container | Image | Role | Port |
|---|---|---|---|
| **Proxy** (`agent`) | Custom (this project) | FastAPI: JWT auth, NeMo Guardrails (embedded), SSE streaming, rate limiting | 8400 |
| **Letta** (`letta`) | `letta/letta:latest` (off-the-shelf) | Agent runtime: reasoning, memory, tool execution | 8283 |

**Current limitations addressed by Phase 2**:
- No streaming endpoint -- `/v1/chat/stream` is documented but not implemented
- Output guardrails evaluate full response, not chunked for streaming
- Rate limiting configured in `Settings` but not enforced
- `_is_blocked()` heuristic uses brittle string matching
- `guardrails_required=true` enforcement already works (refuse to start), but documentation implies it doesn't

**Installed SDK versions** (from `uv.lock`):

| Package | Version | Notes |
|---|---|---|
| `letta-client` | 1.10.x | `Stream[LettaStreamingResponse]` supports `streaming=True` + `stream_tokens=True` |
| `nemoguardrails` | 0.17+ | Embedded guardrails library |
| `fastapi` | >= 0.136 | `StreamingResponse` for SSE |
| `starlette` | 1.0.0 | Available via FastAPI -- `StreamingResponse` for SSE |

---

## Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D15 | **Streaming mode** | `streaming=True, stream_tokens=True` | Token-level streaming to Letta for responsive UX. Chunks are buffered in the proxy to ~200-token segments before guardrail evaluation (architecture doc specifies 200/50 chunking). |
| D16 | **SSE implementation** | Raw `StreamingResponse` from Starlette | `sse-starlette` is not installed and `StreamingResponse` with `text/event-stream` media type is sufficient. Avoids adding a dependency for a simple protocol. |
| D17 | **Chunked output rails** | Regex pre-filter per chunk + NeMo LLM evaluation per ~200-token chunk | Two-layer approach from architecture doc. Regex is fast enough per-chunk; NeMo evaluation batched per chunk. |
| D23 | **Blocked chunk emission** | Never emit blocked chunk content to the client | Security takes precedence over retract transparency. Blocked chunks are withheld entirely; only a `retract_chunk` placeholder event is sent so the client knows a chunk was removed without ever seeing the unsafe text. |
| D24 | **Blocked input on stream route** | Return JSON response (not SSE) | When input rails block a message on `/v1/chat/stream`, the response is a normal JSON body (same shape as `/v1/chat` blocked response, `application/json`). The stream never starts. Clients can distinguish by content-type: `application/json` = block/error, `text/event-stream` = stream. |
| D18 | **Rate limiting store** | In-memory `dict[str, deque[float]]` with sliding window | Same pattern as conversation cache -- in-memory, single-worker. Acceptable for Phase 2 scale. |
| D19 | **Rate limiting layer** | FastAPI dependency (applies to chat routes) | Dependency runs before route logic, allowing early rejection. Only applies to chat routes (health endpoint exempt). |
| D20 | **`_is_blocked()` replacement** | Compare response content against known Colang refusal text + content divergence check | Direct semantic check instead of heuristic prefix matching. Exact match against Colang-defined refusal strings, plus a divergence heuristic for output rails. |
| D21 | **Memory write throttling** | Proxy-side counting via Letta streaming response analysis | Letta emits `ToolCallMessage` and `ToolReturnMessage` in the stream. The proxy counts `core_memory_append` / `archival_memory_insert` calls per user per hour. Cannot prevent the write (it already happened in Letta), but can refuse subsequent requests from the user after threshold is exceeded. |
| D22 | **Scope of 2B/2C** | Interface contract only | LiteMaaS backend routes and frontend widget are in a separate repo. This plan documents the API contract they need to integrate with. |

---

## Letta SDK Streaming Findings

Validated the `letta-client` SDK streaming API to inform the SSE proxy implementation.

**Streaming call**:

```python
stream = client.conversations.messages.create(
    conversation_id,
    input=message,
    streaming=True,
    stream_tokens=True,
    include_pings=True,
)
```

`streaming=True` returns `Stream[LettaStreamingResponse]`. This is a **sync** iterator (`for item in stream:`), not async. The proxy must iterate it synchronously within the async generator or wrap with `asyncio.to_thread()`.

**`LettaStreamingResponse`** is a discriminated union on `message_type`:

| Type | `message_type` | Key Fields |
|---|---|---|
| `ReasoningMessage` | `"reasoning_message"` | `reasoning: str` |
| `ToolCallMessage` | `"tool_call_message"` | `tool_call: {name, arguments}` |
| `ToolReturnMessage` | `"tool_return_message"` | `tool_return: str, status: str` |
| `AssistantMessage` | `"assistant_message"` | `content: Union[List[LettaAssistantMessageContentUnion], str]` |
| `LettaErrorMessage` | `"error_message"` | `error_type: str, message: str, detail: Optional[str]` |
| `LettaStopReason` | `"stop_reason"` | `stop_reason: StopReasonType` |
| `LettaUsageStatistics` | `"usage_statistics"` | `completion_tokens, prompt_tokens, step_count` |
| `LettaPing` | `"ping"` | (keepalive) |

**`AssistantMessage.content`**: With `stream_tokens=True`, content is either a `str` (text fragment) or a `List[LettaAssistantMessageContentUnion]` (structured content with `type="text"`, `text=str`). The proxy must handle both forms.

**`LettaStopReason.stop_reason`** values: `"end_turn"`, `"error"`, `"llm_api_error"`, `"invalid_llm_response"`, `"invalid_tool_call"`, `"max_steps"`, `"max_tokens_exceeded"`, `"no_tool_call"`, `"tool_rule"`, `"cancelled"`, `"insufficient_credits"`, `"requires_approval"`, `"context_window_overflow_in_system_prompt"`.

**Stream termination**: The `Stream` class uses SSE internally and stops on `[DONE]` marker. It implements context manager protocol (`with stream:`).

---

## Sub-phase Order (by dependency)

```
2E (Carryover) ──> 2A (SSE Streaming) ──> 2D (Rate Limiting)
                                               |
                        2B/2C (Interface Contracts -- documentation only, no code dependency)
```

2E is first because it fixes `_is_blocked()` which is used by the streaming guardrails in 2A. 2A is the core new capability. 2D (rate limiting) layers on top of the streaming endpoint. 2B/2C are documentation-only and can be written at any time.

---

## Step 2E -- Phase 1 Carryover Items

**Goal**: Fix the two carryover issues from Phase 1 implementation review before building streaming on top.

### Step 2E.1 -- Replace `_is_blocked()` Heuristic

**Files to modify**: `src/guardrails/rails.py`, `tests/unit/test_guardrails_engine.py`

**Problem**: `_is_blocked()` uses prefix string matching (`_BLOCKED_PREFIXES`) to detect whether NeMo blocked a message. This is fragile -- legitimate responses starting with "I'm sorry" get false-positived, and novel refusal phrasings get false-negatived.

**Solution**: Replace the heuristic with explicit detection based on NeMo's response semantics.

NeMo Guardrails, when a rail blocks a message, replaces the content with the Colang-defined bot response (e.g., `"I'm the LiteMaaS platform assistant..."` from `topics.co`, or `"I apologize, but..."` from `safety.co`). The key insight is: **if NeMo's response differs from the original message, and the response matches a known Colang refusal, the message was blocked.**

For **input rails**: NeMo replaces the user message with a refusal response. Compare NeMo's output against the known refusal strings defined in the Colang files.

For **output rails**: NeMo replaces the assistant message with a refusal. Compare NeMo's output against known Colang refusal strings, plus check for content divergence.

```python
# Known Colang refusal responses (exact text from .co files)
_COLANG_REFUSALS = frozenset({
    # topics.co
    "I'm the LiteMaaS platform assistant. I can help you with model subscriptions, "
    "API keys, usage questions, and platform troubleshooting. For other topics, "
    "I'd suggest using the models directly via the Chat Playground!",
    # safety.co
    "I apologize, but I'm unable to provide that information. Is there something "
    "else about the LiteMaaS platform I can help you with?",
    # safety.co (jailbreak)
    "I'm the LiteMaaS platform assistant and I need to stay focused on helping "
    "you with platform questions. How can I help you with models, subscriptions, "
    "or API keys?",
})

@staticmethod
def _is_blocked_input(content: str | None) -> bool:
    """Detect whether NeMo blocked an input message.

    Input is blocked when NeMo replaces it with a known Colang refusal
    response, or returns empty/None content.
    """
    if not content or not content.strip():
        return True
    return content.strip() in _COLANG_REFUSALS
```

For output, also add a "NeMo response divergence" check -- if the output rail's response differs from the original assistant message AND is shorter than 200 chars AND is not a substring of the original (to avoid false positives on minor NeMo reformatting like stripping markdown), treat as blocked. This catches novel refusals from the LLM `self_check_output` flow that may not match Colang text exactly.

```python
@staticmethod
def _is_blocked_output(original: str, content: str | None) -> bool:
    """Output-specific blocking detection.

    Output rails are blocked when:
    1. Content is empty/None
    2. Content is a known Colang refusal
    3. Content is materially different from original, short, and not
       a minor reformatting (catches novel LLM-generated refusals)
    """
    if not content or not content.strip():
        return True
    stripped = content.strip()
    if stripped in _COLANG_REFUSALS:
        return True
    orig_stripped = original.strip()
    if stripped != orig_stripped and len(stripped) < 200:
        # Exclude minor reformatting (NeMo may strip markdown etc.)
        if stripped not in orig_stripped and orig_stripped not in stripped:
            return True
    return False
```

This replaces both the old `_is_blocked()` and the `_BLOCKED_PREFIXES` tuple. Two separate methods: `_is_blocked_input()` (for input rails -- only checks refusals) and `_is_blocked_output()` (for output rails -- also checks content divergence).

Update `check_input()` to call `self._is_blocked_input(content)` and `check_output()` to call `self._is_blocked_output(message, content)`.

**Tests to update**: `tests/unit/test_guardrails_engine.py`

Replace `TestGuardrailsEngineIsBlocked` class with two new classes:

```python
class TestIsBlockedInput:
    # Test _is_blocked_input returns True for each known Colang refusal (exact text)
    # Test _is_blocked_input returns True for empty/None content
    # Test _is_blocked_input returns True with leading whitespace on refusal
    # Test _is_blocked_input returns False for legitimate agent responses
    # Test _is_blocked_input returns False for "I'm sorry, your budget is low" (no false positive)
    # Test _is_blocked_input returns False for "Unfortunately, that model is not available yet."

class TestIsBlockedOutput:
    # Test _is_blocked_output returns True for empty/None content
    # Test _is_blocked_output returns True for known Colang refusal
    # Test _is_blocked_output returns False when content matches original (pass-through)
    # Test _is_blocked_output returns True when content differs and is short (novel refusal)
    # Test _is_blocked_output returns False when content differs but is long (>200 chars)
    # Test _is_blocked_output returns False for minor reformatting (substring match)
```

Update existing `TestGuardrailsEngineCheckInput.test_check_input_blocks_refusal` and `TestGuardrailsEngineCheckOutput.test_check_output_blocks_unsafe_response` to use actual Colang refusal text instead of prefix-matched strings.

**Verification**: Old tests updated, new tests pass. False positive on "I'm sorry, your budget is low" is eliminated.

---

### Step 2E.2 -- Verify Guardrails Strictness Enforcement

**Files to review**: `src/proxy/server.py` (lines 176-189)

**Problem statement from PROJECT_PLAN**: "When `guardrails_required=true`, the server must refuse to start (not fall back to no guardrails)."

**Current code** (already correct):
```python
try:
    from guardrails.rails import GuardrailsEngine
    _guardrails = GuardrailsEngine(settings)
    logger.info("Guardrails initialized")
except Exception:
    if settings.guardrails_required:
        logger.error("Guardrails initialization failed and GUARDRAILS_REQUIRED=true")
        raise   # <-- Server refuses to start
    logger.warning("Guardrails initialization failed -- running without guardrails", exc_info=True)
    _guardrails = None
```

**And in `routes.py`** (lines 72-76):
```python
if guardrails is None:
    logger.error("Guardrails unavailable -- refusing request for user %s", user.user_id)
    raise HTTPException(status_code=503, detail="Service temporarily unavailable -- guardrails not initialized")
```

This is already correctly implemented: the server refuses to start when `guardrails_required=true`, and even if guardrails become None after startup, requests are refused with 503.

**Action**: Mark this carryover item as resolved. Add a specific test that verifies the startup behavior:

**File to modify**: `tests/unit/test_server.py` (add new test class)

```python
class TestLifespanGuardrailsEnforcement:
    async def test_lifespan_raises_when_guardrails_required_and_init_fails(self):
        """When guardrails_required=true and guardrails init fails, lifespan raises."""
        # Mock settings with guardrails_required=True
        # Mock GuardrailsEngine.__init__ to raise
        # Mock bootstrap_agent and _wait_for_letta
        # Assert lifespan raises (not swallows)

    async def test_lifespan_continues_when_guardrails_optional_and_init_fails(self):
        """When guardrails_required=false and guardrails init fails, lifespan continues."""
        # Mock settings with guardrails_required=False
        # Mock GuardrailsEngine.__init__ to raise
        # Assert lifespan completes without error (_guardrails is None)
```

**Verification**: Test confirms startup failure when guardrails init fails with `guardrails_required=true`.

---

## Step 2A -- SSE Streaming

**Goal**: `/v1/chat/stream` endpoint with POST-based SSE, token-level streaming from Letta, two-layer chunked output guardrails, and retract mechanism.

### Step 2A.1 -- Spike: Letta Streaming Behavior

**Purpose**: Validate streaming behavior of the Letta SDK before implementing the proxy endpoint. Confirm token-level streaming works and characterize the response format.

**File to create**: `docs/development/phase-2-integration/SPIKE_RESULTS.md`

**What to validate** (run against a live Letta instance):

1. **Token-level streaming**: Call `client.conversations.messages.create(conv_id, input="Hello", streaming=True, stream_tokens=True)`. Iterate the `Stream[LettaStreamingResponse]` and log each chunk's `message_type`, content, and timing.

2. **Message type sequence**: Document the order of message types received during a typical tool-calling interaction (e.g., `reasoning_message` -> `tool_call_message` -> `tool_return_message` -> `assistant_message`).

3. **Assistant message chunking**: With `stream_tokens=True`, does the Letta SDK emit multiple `AssistantMessage` chunks with partial content, or one complete message? Document the content structure: is `content` a string or a list of `LettaAssistantMessageContentUnion`?

4. **Error handling in stream**: What happens when a Letta tool call fails mid-stream? Does the stream emit a `LettaErrorMessage`? How should the proxy handle it?

5. **Stream resumption**: Does `client.conversations.messages.stream()` work for reconnecting to an active run? (Needed for robustness.)

6. **Keepalive pings**: With `include_pings=True`, confirm `LettaPing` messages arrive at regular intervals.

**Decision tree**:
```
stream_tokens=True emits partial assistant_message chunks?
+-- YES -> Buffer chunks, run guardrails per ~200-token buffer
+-- NO (one complete message) -> Fall back to per-step streaming
    (emit reasoning/tool status as SSE events, full assistant message at end)

LettaErrorMessage emitted on tool failure?
+-- YES -> Forward as SSE error event
+-- NO -> Watch for stream termination without done event
```

**Verification**: `SPIKE_RESULTS.md` documents each finding with code snippets. Streaming mode decision confirmed.

---

### Step 2A.2 -- Chunked Output Guardrails

**File to modify**: `src/guardrails/rails.py`

**What the code should do**:

Add a new method `check_output_chunk()` to `GuardrailsEngine` for streaming evaluation. This method evaluates a single chunk (with context from the previous chunk's tail for continuity).

```python
async def check_output_chunk(
    self,
    chunk: str,
    user: AuthenticatedUser,
    overlap_context: str = "",
) -> RailResult:
    """Run output rails on a single chunk from the streaming response.

    Two-layer evaluation:
    1. Fast regex pre-filter (PII patterns) -- runs on every chunk
    2. Full NeMo LLM evaluation -- runs on the combined overlap_context + chunk

    Args:
        chunk: The text chunk to evaluate (~200 tokens).
        user: Authenticated user context.
        overlap_context: The last ~50 tokens of the previous chunk (sliding window).

    Returns:
        RailResult. If blocked, the chunk should be retracted.
    """
```

**Implementation details**:

Layer 1 -- Regex pre-filter (fast, per-chunk):
```python
from guardrails.actions import _regex_check_output_pii_impl

pii_context = {"last_bot_message": chunk}
if not _regex_check_output_pii_impl(pii_context):
    return RailResult(blocked=True, response=self._SAFE_FALLBACK)
```

Layer 2 -- NeMo LLM evaluation (slower, per-chunk):
```python
eval_text = overlap_context + chunk
response = await self._rails.generate_async(
    messages=[
        {"role": "user", "content": "respond to user"},
        {"role": "assistant", "content": eval_text},
    ],
    options={"rails": ["output"]},
)
content = _extract_nemo_content(response)
blocked = self._is_blocked_output(eval_text, content)
return RailResult(blocked=blocked, response=self._SAFE_FALLBACK if blocked else chunk)
```

**Fail-closed**: Any exception during chunk evaluation -> `blocked=True`.

**Dependencies**: Step 2E.1 (`_is_blocked_output` method).

**Tests to write**: `tests/unit/test_guardrails_engine.py` (additions)

```python
# Test check_output_chunk passes clean chunk
# Test check_output_chunk blocks chunk with email PII (regex layer)
# Test check_output_chunk blocks chunk with full API key (regex layer)
# Test check_output_chunk fails closed on NeMo error
# Test check_output_chunk includes overlap context in NeMo evaluation
```

---

### Step 2A.3 -- Token Buffer for Chunked Evaluation

**File to create**: `src/proxy/streaming.py`

**What the code should do**:

Implement a `TokenBuffer` class that accumulates streaming tokens from Letta and yields chunks of approximately `OUTPUT_RAIL_CHUNK_SIZE` tokens (default 200) with `OUTPUT_RAIL_OVERLAP` tokens (default 50) of overlap context.

```python
"""SSE streaming helpers: token buffering and chunked evaluation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Approximate: 1 token ~ 4 characters (conservative for English text)
_CHARS_PER_TOKEN = 4


@dataclass
class ChunkWithContext:
    """A chunk of text paired with its overlap context from the previous chunk."""

    text: str
    overlap_context: str


@dataclass
class TokenBuffer:
    """Accumulates streaming text and yields chunks for guardrail evaluation.

    Chunks are approximately `chunk_size` tokens (measured by character count)
    with `overlap` tokens of trailing context carried to the next chunk.

    Important: overlap_context returned with each chunk is the tail of the
    PREVIOUS chunk, not the current one. This ensures continuity semantics
    are correct for guardrail evaluation.
    """

    chunk_size: int = 200
    overlap: int = 50
    _buffer: str = ""
    _overlap_context: str = ""
    _chunk_count: int = 0

    def add(self, text: str) -> ChunkWithContext | None:
        """Add text to the buffer. Returns a chunk with context if full enough.

        Returns:
            A ChunkWithContext if the buffer has accumulated enough tokens,
            else None. The overlap_context field contains the tail of the
            previous chunk (empty for the first chunk).
        """
        self._buffer += text
        threshold = self.chunk_size * _CHARS_PER_TOKEN
        if len(self._buffer) >= threshold:
            return self._flush()
        return None

    def flush_remaining(self) -> ChunkWithContext | None:
        """Flush any remaining text in the buffer as a final chunk.

        Returns:
            A ChunkWithContext with remaining text, or None if empty.
        """
        if self._buffer:
            return self._flush()
        return None

    def _flush(self) -> ChunkWithContext:
        """Extract a chunk from the buffer, preserving overlap context."""
        chunk = self._buffer
        self._buffer = ""
        self._chunk_count += 1
        # Capture the overlap from the PREVIOUS chunk before updating
        prev_overlap = self._overlap_context
        # Update overlap context for the NEXT chunk
        overlap_chars = self.overlap * _CHARS_PER_TOKEN
        self._overlap_context = chunk[-overlap_chars:] if len(chunk) > overlap_chars else chunk
        return ChunkWithContext(text=chunk, overlap_context=prev_overlap)
```

**Tests to write**: `tests/unit/test_streaming.py`

```python
# Test TokenBuffer.add returns None when buffer is below threshold
# Test TokenBuffer.add returns ChunkWithContext when buffer reaches threshold (200*4 = 800 chars)
# Test ChunkWithContext.text contains the buffered text
# Test ChunkWithContext.overlap_context is empty string for the first chunk
# Test ChunkWithContext.overlap_context for chunk N is the tail of chunk N-1 (not chunk N)
# Test TokenBuffer.flush_remaining returns ChunkWithContext with remaining text
# Test TokenBuffer.flush_remaining returns None when empty
# Test multiple add() calls accumulate before yielding
# Test custom chunk_size and overlap values
# Test overlap_context length is overlap * _CHARS_PER_TOKEN characters
```

---

### Step 2A.4 -- Streaming Chat Route

**File to modify**: `src/proxy/routes.py`

**What the code should do**:

Add `POST /v1/chat/stream` endpoint that:
1. Validates JWT and runs input guardrails (same as `/v1/chat`)
2. If input is blocked, returns a JSON response (`application/json`) — no SSE stream
3. Injects user secrets and resolves conversation (under `_secrets_lock`)
4. Starts Letta streaming with `streaming=True, stream_tokens=True`
5. Buffers assistant message tokens into `ChunkWithContext` via `TokenBuffer`
6. Evaluates each chunk through `guardrails.check_output_chunk()` with overlap from previous chunk
7. Emits SSE events: `chunk` (safe only), `retract_chunk` (placeholder for blocked), `error`, `done`
8. Handles Letta `error_message` and error `stop_reason` types explicitly

```python
@router.post("/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(validate_jwt),
) -> StreamingResponse | JSONResponse:
    """Stream a response from the agent via SSE.

    If input rails block the message, returns a JSON response (application/json)
    with the same shape as /v1/chat blocked responses. Clients distinguish by
    content-type: application/json = block/error, text/event-stream = stream.

    SSE event format:
        data: {"chunk": "text...", "index": 0}
        data: {"retract_chunk": <index>, "placeholder": "...removed..."}
        data: {"error": "...", "retryable": bool}
        data: {"done": true, "conversation_id": "...", "safety_notice": "..."}
    """
```

**SSE generator function**:

```python
async def _stream_response(
    agent_state: AgentState,
    guardrails: GuardrailsEngine,
    user: AuthenticatedUser,
    message: str,
    conversation_id: str,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """Generate SSE events from a Letta streaming response.

    Buffers assistant message tokens into chunks, evaluates each through
    guardrails, and emits SSE events with chunk indexing.

    Security: Blocked chunks are NEVER emitted as text. Only a retract_chunk
    placeholder is sent so the client knows content was withheld.
    """
    buffer = TokenBuffer(
        chunk_size=settings.output_rail_chunk_size,
        overlap=settings.output_rail_overlap,
    )
    chunk_index = 0
    retracted_indices: list[int] = []

    # Start Letta streaming (still under secrets lock from caller)
    letta_stream = agent_state.client.conversations.messages.create(
        conversation_id,
        input=message,
        streaming=True,
        stream_tokens=True,
    )

    try:
        # NOTE: Stream is a sync iterator (not async). Iterate synchronously.
        for msg in letta_stream:
            if not hasattr(msg, "message_type"):
                continue

            # Handle Letta error messages explicitly
            if msg.message_type == "error_message":
                error_detail = getattr(msg, "message", "Unknown agent error")
                logger.error(
                    "Letta error during streaming for user %s: %s",
                    user.user_id, error_detail,
                )
                yield f"data: {_json_event('error', error_detail, retryable=False)}\n\n"
                yield f'data: {{"done": true, "conversation_id": "{conversation_id}", "safety_notice": null}}\n\n'
                return

            # Handle stop reasons that indicate errors
            if msg.message_type == "stop_reason":
                stop = getattr(msg, "stop_reason", None)
                _ERROR_STOP_REASONS = {
                    "error", "llm_api_error", "invalid_llm_response",
                    "max_tokens_exceeded", "insufficient_credits",
                    "context_window_overflow_in_system_prompt",
                }
                if stop in _ERROR_STOP_REASONS:
                    logger.error(
                        "Letta stop reason '%s' for user %s", stop, user.user_id
                    )
                    yield f"data: {_json_event('error', f'Agent stopped: {stop}', retryable=True)}\n\n"

            # Only stream assistant_message content
            if msg.message_type == "assistant_message":
                # Handle both str and List[LettaAssistantMessageContentUnion] content
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    content = "".join(
                        part.text for part in msg.content
                        if hasattr(part, "text")
                    )
                else:
                    continue
                if not content:
                    continue

                # Add to buffer; check if a chunk is ready
                chunk_with_ctx = buffer.add(content)
                if chunk_with_ctx:
                    result = await guardrails.check_output_chunk(
                        chunk_with_ctx.text, user, chunk_with_ctx.overlap_context
                    )
                    if result.blocked:
                        # Never emit blocked content — only send placeholder
                        yield f"data: {_json_event('retract_chunk', chunk_index)}\n\n"
                        retracted_indices.append(chunk_index)
                    else:
                        yield f"data: {_json_event('chunk', chunk_with_ctx.text, chunk_index)}\n\n"
                    chunk_index += 1

        # Flush remaining buffer
        remaining = buffer.flush_remaining()
        if remaining:
            result = await guardrails.check_output_chunk(
                remaining.text, user, remaining.overlap_context
            )
            if result.blocked:
                yield f"data: {_json_event('retract_chunk', chunk_index)}\n\n"
                retracted_indices.append(chunk_index)
            else:
                yield f"data: {_json_event('chunk', remaining.text, chunk_index)}\n\n"
            chunk_index += 1

    except Exception:
        logger.exception("Error during Letta streaming for user %s", user.user_id)
        yield f"data: {_json_event('error', 'Stream interrupted', retryable=True)}\n\n"
        yield f'data: {{"done": true, "conversation_id": "{conversation_id}", "safety_notice": null}}\n\n'
        return

    # Done event — always sent to signal stream completion
    safety_notice = (
        "Part of this response has been removed for safety reasons."
        if retracted_indices else None
    )
    yield f'data: {{"done": true, "conversation_id": "{conversation_id}", "safety_notice": {_json_str(safety_notice)}}}\n\n'
```

**Key design notes**:

- The `_secrets_lock` scope changes for streaming: secrets injection + conversation resolution remain inside the lock, but the **Letta streaming call also starts inside the lock** (to prevent another request from overwriting secrets while this stream's tools are executing). The lock is released only after `letta_stream` is fully consumed. This is the same serialization approach as Phase 1 -- streaming doesn't change the concurrency model.

- **Alternative design considered**: Release the lock after `messages.create()` returns the stream object (before consuming). Rejected because Letta tool execution happens during stream consumption, and tools read secrets from the environment. A concurrent request could overwrite secrets mid-tool-execution.

- **Security note on retract (D23)**: Blocked chunks are **never emitted** as text to the client. When guardrails block a chunk, only a `retract_chunk` placeholder event is sent (with the chunk index so the frontend can render `"...removed..."` in the correct position). This prevents any unsafe content from reaching the client, even momentarily. The frontend sees the gap in chunk indices and renders the placeholder.

- **Blocked input on stream route (D24)**: When input rails block a message, `/v1/chat/stream` returns a normal JSON response (`application/json`), not an SSE stream. The response body matches `/v1/chat` blocked responses: `{"message": "...", "conversation_id": null, "blocked": true}`. Clients distinguish by content-type: `application/json` = block/error, `text/event-stream` = stream started. This is simpler for clients than an SSE stream with an immediate terminal event.

**Helper functions**:

```python
import json

def _json_event(
    event_type: str,
    content: str | int,
    index: int | None = None,
    retryable: bool | None = None,
) -> str:
    """Format an SSE data payload."""
    if event_type == "chunk":
        return json.dumps({"chunk": content, "index": index})
    elif event_type == "retract_chunk":
        return json.dumps({"retract_chunk": content, "placeholder": "...removed..."})
    elif event_type == "error":
        return json.dumps({"error": content, "retryable": retryable or False})
    return json.dumps({event_type: content})

def _json_str(value: str | None) -> str:
    """JSON-encode a nullable string."""
    return json.dumps(value)
```

**Dependencies**: Step 2A.2 (chunked guardrails), Step 2A.3 (token buffer), Step 2E.1 (`_is_blocked_output`).

**Tests to write**: `tests/unit/test_routes.py` (additions)

```python
# Test /v1/chat/stream requires authentication (401 without token)
# Test /v1/chat/stream returns StreamingResponse with text/event-stream content type
# Test /v1/chat/stream blocked input returns JSON (application/json), not SSE
# Test /v1/chat/stream blocked input JSON body matches /v1/chat blocked shape
# Test /v1/chat/stream emits chunk events with sequential indices
# Test /v1/chat/stream does NOT emit blocked chunk content (only retract_chunk placeholder)
# Test /v1/chat/stream retract_chunk indices are sequential with emitted chunks
# Test /v1/chat/stream emits done event with conversation_id
# Test /v1/chat/stream emits safety_notice when chunks were retracted
# Test /v1/chat/stream emits error event on Letta error_message
# Test /v1/chat/stream emits error event on error stop_reason
# Test /v1/chat/stream emits done event after error event (always terminates cleanly)
# Test /v1/chat/stream handles unexpected exceptions gracefully (error + done)
# Test message length limit (> 4000 chars rejected)
# Test conversation ownership validation (403 for wrong user)
```

**Tests to write**: `tests/unit/test_streaming.py` (new file, see Step 2A.3)

**Verification**: `curl` against `/v1/chat/stream` with a valid JWT shows incremental `data:` lines. A message triggering PII output shows a `retract_chunk` event.

---

### Step 2A.5 -- Update Server Health Endpoint

**File to modify**: `src/proxy/server.py`

**What to add**: No code changes needed for health. The health endpoint already reports `agent` and `guardrails` status. The streaming endpoint is auto-documented via FastAPI's OpenAPI generation.

**Verification**: `/v1/health` still returns correct status. `/docs` shows both `/v1/chat` and `/v1/chat/stream`.

---

## Step 2D -- Rate Limiting

**Goal**: Per-user rate limiting at the proxy layer. Memory write throttling per user.

### Step 2D.1 -- Rate Limiter Implementation

**File to create**: `src/proxy/rate_limit.py`

**What the code should do**:

Implement a per-user sliding window rate limiter.

```python
"""Per-user rate limiting with sliding window."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """In-memory per-key sliding window rate limiter.

    Thread-safe within a single asyncio event loop (single-worker constraint).
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key.

        Prunes expired timestamps and checks the count against the limit.
        Returns True if allowed (and records the request), False if rate-limited.
        """
        now = time.monotonic()
        window_start = now - self._window_seconds
        timestamps = self._requests[key]

        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self._max_requests:
            return False

        timestamps.append(now)
        return True

    def remaining(self, key: str) -> int:
        """Return the number of remaining requests in the current window."""
        now = time.monotonic()
        window_start = now - self._window_seconds
        timestamps = self._requests[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        return max(0, self._max_requests - len(timestamps))

    def reset_time(self, key: str) -> float:
        """Return seconds until the oldest request in the window expires."""
        timestamps = self._requests[key]
        if not timestamps:
            return 0.0
        return max(0.0, self._window_seconds - (time.monotonic() - timestamps[0]))
```

**Tests to write**: `tests/unit/test_rate_limit.py`

```python
# Test is_allowed returns True when under limit
# Test is_allowed returns False when at limit
# Test is_allowed prunes expired timestamps (mock time.monotonic to advance past window)
# Test remaining returns correct count after some requests
# Test remaining returns 0 when at limit
# Test reset_time returns 0 when no requests
# Test reset_time returns time until oldest request expires
# Test different keys are tracked independently (user-1 limit doesn't affect user-2)
# Test edge case: max_requests=1
# Test window slides correctly (request expires, new request allowed)
```

---

### Step 2D.2 -- Rate Limiting Dependency

**File to modify**: `src/proxy/routes.py`

**What the code should do**:

Add a FastAPI dependency that checks the per-user rate limit before processing chat requests. Apply to both `/v1/chat` and `/v1/chat/stream`.

```python
_chat_rate_limiter: SlidingWindowRateLimiter | None = None
_memory_write_tracker: SlidingWindowRateLimiter | None = None


def _get_chat_rate_limiter() -> SlidingWindowRateLimiter:
    """Lazy-init the chat rate limiter from settings."""
    global _chat_rate_limiter
    if _chat_rate_limiter is None:
        from agent.config import Settings
        settings = Settings()  # type: ignore[call-arg]
        _chat_rate_limiter = SlidingWindowRateLimiter(
            max_requests=settings.rate_limit_rpm,
            window_seconds=60.0,
        )
    return _chat_rate_limiter


def check_rate_limit(user: AuthenticatedUser = Depends(validate_jwt)) -> AuthenticatedUser:
    """FastAPI dependency: check per-user rate limit. Raises 429 if exceeded."""
    limiter = _get_chat_rate_limiter()
    if not limiter.is_allowed(user.user_id):
        remaining = limiter.remaining(user.user_id)
        reset = limiter.reset_time(user.user_id)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(int(reset)),
                "X-RateLimit-Remaining": str(remaining),
            },
        )
    return user
```

**Apply to routes** (change `Depends(validate_jwt)` to `Depends(check_rate_limit)`):

```python
@router.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(check_rate_limit),
) -> ChatResponse:
    ...

@router.post("/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(check_rate_limit),
) -> StreamingResponse | JSONResponse:
    ...
```

**Tests to write**: `tests/unit/test_routes.py` (additions)

```python
# Test /v1/chat returns 429 when rate limited
# Test /v1/chat/stream returns 429 when rate limited
# Test 429 response includes Retry-After header
# Test rate limit is per-user (different users have independent limits)
```

---

### Step 2D.3 -- Memory Write Throttling

**File to modify**: `src/proxy/routes.py` (or `src/proxy/streaming.py`)

**What the code should do**:

Track memory write operations (detected from the Letta streaming response) per user. When a user exceeds `RATE_LIMIT_MEMORY_WRITES_PER_HOUR`, refuse subsequent requests.

**Detection approach**: During streaming, the proxy observes `ToolCallMessage` events. If the tool name is `core_memory_append`, `core_memory_replace`, or `archival_memory_insert`, increment the user's memory write counter.

```python
_MEMORY_WRITE_TOOLS = frozenset({
    "core_memory_append",
    "core_memory_replace",
    "archival_memory_insert",
})

# In the streaming generator:
if msg.message_type == "tool_call_message":
    tool_call = getattr(msg, "tool_call", None)
    if tool_call and hasattr(tool_call, "name") and tool_call.name in _MEMORY_WRITE_TOOLS:
        memory_limiter = _get_memory_write_limiter()
        if not memory_limiter.is_allowed(user.user_id):
            logger.warning(
                "Memory write throttle exceeded for user %s", user.user_id
            )
            # Cannot prevent the write (already sent to Letta), but log it
            # and the NEXT request from this user will be refused
```

**Note**: Memory writes happen inside Letta's process -- the proxy cannot prevent them in real-time. The throttle works by refusing subsequent requests from users who have exceeded their hourly limit. This is a best-effort mechanism, documented as such.

**For the non-streaming `/v1/chat` endpoint**: After extracting the assistant message, scan the Letta response for `ToolCallMessage` chunks that indicate memory writes and update the counter.

**Tests to write**: `tests/unit/test_rate_limit.py` (additions)

```python
# Test memory write limiter tracks tool calls
# Test memory write limiter refuses after threshold exceeded
# Test memory write limiter window is per hour
```

---

## Step 2B/2C -- Interface Contracts (Documentation Only)

**Goal**: Document the API contract that the LiteMaaS backend and frontend need to integrate with. No code changes in this project.

**File to create**: `docs/guides/integration-contract.md`

**Contents**:

### LiteMaaS Backend Routes

The LiteMaaS backend needs to add a thin proxy at `/api/v1/assistant/*` that forwards requests to the agent container:

| Backend Route | Agent Route | Method | Notes |
|---|---|---|---|
| `POST /api/v1/assistant/chat` | `POST /v1/chat` | Forward | JSON request/response |
| `POST /api/v1/assistant/chat/stream` | `POST /v1/chat/stream` | Forward SSE | Stream `text/event-stream` response body |
| `GET /api/v1/assistant/health` | `GET /v1/health` | Forward | JSON response |

**Auth**: Forward the `Authorization: Bearer <jwt>` header as-is. The agent proxy validates the JWT independently using the same `JWT_SECRET`.

**Feature flag**: Routes should only be registered when `AGENT_URL` environment variable is configured.

### SSE Protocol

```
data: {"chunk": "Hello, how can I", "index": 0}
data: {"chunk": " help you today?", "index": 1}
data: {"retract_chunk": 2, "placeholder": "...removed..."}
data: {"done": true, "conversation_id": "conv-uuid", "safety_notice": "Part of this response has been removed for safety reasons."}
```

**Note**: Blocked chunks are never emitted as text. Only a `retract_chunk` placeholder is sent — the client never sees the unsafe content.

**Note**: If input rails block the message, no SSE stream is started. The response is a JSON body (`application/json`) with `{"message": "...", "conversation_id": null, "blocked": true}`, identical to `/v1/chat` blocked responses. Clients distinguish by content-type.

| Event | Fields | Description |
|---|---|---|
| `chunk` | `chunk: str`, `index: int` | Safe text chunk with sequential index |
| `retract_chunk` | `retract_chunk: int`, `placeholder: str` | A chunk at this index was withheld (unsafe content never sent) |
| `error` | `error: str`, `retryable: bool` | Agent or stream error; `retryable` hints whether the client should retry |
| `done` | `done: true`, `conversation_id: str`, `safety_notice: str\|null` | Stream complete. Always sent as the final event (even after errors). |

### Error Responses

| Status | Cause |
|---|---|
| `401` | Missing/invalid/expired JWT |
| `403` | Conversation doesn't belong to user |
| `422` | Invalid request body |
| `429` | Rate limit exceeded (check `Retry-After` header) |
| `502` | Agent/Letta unreachable |
| `503` | Guardrails not initialized |

### Frontend Widget

- Use `fetch()` + `ReadableStream` for POST-based SSE (not `EventSource`)
- Track chunk indices for retract UX (replace content at retracted index with placeholder)
- Show safety notice at end of message if `safety_notice` is non-null
- Disable input during streaming via `MessageBar.isDisabled`
- Health check: `GET /api/v1/assistant/health` on mount; disable floating button if unhealthy

**No code changes in this project** -- the contract is implemented by the agent proxy (Steps 2A, 2D) and consumed by the LiteMaaS team.

---

## Configuration Changes

### New Environment Variables

None -- all Phase 2 config variables already exist in `Settings`:
- `OUTPUT_RAIL_CHUNK_SIZE` (default: 200)
- `OUTPUT_RAIL_OVERLAP` (default: 50)
- `RATE_LIMIT_RPM` (default: 30)
- `RATE_LIMIT_MEMORY_WRITES_PER_HOUR` (default: 20)

### Settings Changes

**File to modify**: `src/agent/config.py`

Remove the `# TODO` comments from `rate_limit_rpm` and `rate_limit_memory_writes_per_hour` since they'll be enforced.

---

## File Manifest

| # | File | Action | Content |
|---|---|---|---|
| 1 | `docs/development/phase-2-integration/SPIKE_RESULTS.md` | Create | Spike findings (Step 2A.1) |
| 2 | `src/guardrails/rails.py` | Modify | Replace `_is_blocked()` with `_is_blocked_input()` / `_is_blocked_output()`, add `check_output_chunk()` (Steps 2E.1, 2A.2) |
| 3 | `src/proxy/streaming.py` | Create | `TokenBuffer` class (Step 2A.3) |
| 4 | `src/proxy/routes.py` | Modify | Add `/v1/chat/stream` endpoint, add rate limit dependency, memory write tracking (Steps 2A.4, 2D.2, 2D.3) |
| 5 | `src/proxy/rate_limit.py` | Create | `SlidingWindowRateLimiter` class (Step 2D.1) |
| 6 | `src/agent/config.py` | Modify | Remove TODO comments (minor) |
| 7 | `docs/guides/integration-contract.md` | Create | API contract for LiteMaaS team (Step 2B/2C) |
| 8 | `tests/unit/test_guardrails_engine.py` | Modify | Update blocking detection tests, add chunk evaluation tests (Steps 2E.1, 2A.2) |
| 9 | `tests/unit/test_streaming.py` | Create | TokenBuffer tests (Step 2A.3) |
| 10 | `tests/unit/test_routes.py` | Modify | Add streaming route tests, rate limit tests (Steps 2A.4, 2D.2) |
| 11 | `tests/unit/test_rate_limit.py` | Create | SlidingWindowRateLimiter tests (Step 2D.1) |
| 12 | `tests/unit/test_server.py` | Modify | Add guardrails startup failure test (Step 2E.2) |
| 13 | `docs/reference/api.md` | Modify | Update SSE protocol section: blocked chunks never emitted, `error` event type, blocked-input JSON contract, `done` event semantics (Steps 2A.4, 2B/2C) |
| 14 | `docs/guides/frontend-integration.md` | Modify | Update SSE handling: content-type branching for blocked input, retract without prior chunk, `error` event handling, `retryable` hint (Steps 2A.4, 2B/2C) |

---

## Implementation Notes

### Secrets Lock Scope During Streaming

The `_secrets_lock` must remain held for the entire duration of the Letta stream, not just the `messages.create()` call. This is because Letta's tools execute during stream consumption and read secrets from the environment. Releasing the lock before the stream is fully consumed would allow a concurrent request to overwrite the secrets mid-tool-execution.

This means streaming requests are fully serialized, same as non-streaming. This is acceptable for Phase 2 scale (single proxy, moderate concurrency). If concurrency becomes a bottleneck, the architecture would need per-user agent instances (Phase 3+).

### SSE Format (POST-based)

Standard `EventSource` only supports GET. Since we use POST (to avoid message content in URLs), clients must use `fetch()` + `ReadableStream`. The SSE format is still standard (`data: {...}\n\n`), just delivered over a POST response.

### Token Approximation in Buffer

The `TokenBuffer` uses a simple `4 chars ~ 1 token` approximation. This is conservative for English text and avoids the complexity of a real tokenizer. The chunk size doesn't need to be exact -- +/-20% is fine for guardrail evaluation purposes.

### Letta Stream is Sync-Only

The Letta SDK `Stream[LettaStreamingResponse]` implements `__iter__` (sync), not `__aiter__` (async). In the async SSE generator, iterate it synchronously with `for msg in letta_stream:`. Since the stream does I/O, this blocks the event loop briefly per chunk -- acceptable under the `_secrets_lock` serialization (only one stream active at a time). If this becomes a bottleneck, wrap iteration in `asyncio.to_thread()`.

### AssistantMessage Content Type

`AssistantMessage.content` is `Union[List[LettaAssistantMessageContentUnion], str]`. With `stream_tokens=True`, individual token chunks may arrive as plain `str` or as structured `List` with `type="text"` entries. The streaming generator must handle both forms:

```python
if isinstance(msg.content, str):
    content = msg.content
elif isinstance(msg.content, list):
    content = "".join(part.text for part in msg.content if hasattr(part, "text"))
```

### Memory Write Throttling Limitations

Memory writes happen inside Letta's sandbox -- the proxy cannot intercept or prevent them in real-time. The throttle works reactively: count writes observed in the stream, refuse the user's next request if the hourly limit is exceeded. A user's final request before hitting the limit could still trigger writes. This is documented behavior, not a bug.

### NeMo Guardrails `check_output_chunk` Performance

Each chunk requires a full NeMo `generate_async()` call with LLM evaluation. For a 1000-token response (~5 chunks at 200 tokens each), this means 5 LLM calls to the guardrails model. This adds latency proportional to the response length. The guardrails model should be fast (e.g., a small model optimized for classification). The regex pre-filter catches obvious violations before the LLM call.

### `_is_blocked_output` Divergence False Positives

NeMo sometimes strips markdown or slightly reformats content without blocking it. The divergence check (`stripped != orig_stripped and len(stripped) < 200`) would false-positive on these minor reformattings. To avoid this, the check includes a substring guard: if the NeMo output is a substring of the original (or vice versa), it's considered a minor reformatting, not a block. For example, `"Your subscription is active"` vs `"Your subscription is **active**"` -- the stripped version is a substring of the original, so it passes.

---

## Verification

### Unit Tests (no external services needed)

```bash
uv run pytest tests/unit/ -v --tb=short

# Security invariant tests still pass
uv run pytest tests/unit/test_security_invariants.py -v

# New streaming tests
uv run pytest tests/unit/test_streaming.py -v
uv run pytest tests/unit/test_rate_limit.py -v
```

### Lint and Type Check

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

### End-to-End Test (manual)

```bash
# 1. Start the full stack
podman-compose up --build

# 2. Wait for both containers
until curl -s http://host.containers.internal:8400/v1/health | grep -q "healthy"; do sleep 2; done

# 3. Create a test JWT
JWT_SECRET="your-test-secret"
TOKEN=$(python3 -c "
import jwt, time
print(jwt.encode({
    'userId': 'test-user-1',
    'username': 'tester',
    'email': 'test@example.com',
    'roles': ['user'],
    'iat': int(time.time()),
    'exp': int(time.time()) + 3600,
}, '${JWT_SECRET}', algorithm='HS256'))
")

# 4. Test streaming endpoint
curl -sN -X POST http://host.containers.internal:8400/v1/chat/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "Why cant I access gpt-4o?"}'

# Expected: Sequential data: lines with chunk events, ending with done event

# 5. Test non-streaming still works
curl -s -X POST http://host.containers.internal:8400/v1/chat \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "Why cant I access gpt-4o?"}' | python3 -m json.tool

# 6. Test rate limiting (send 31 rapid requests)
for i in $(seq 1 31); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://host.containers.internal:8400/v1/chat \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"message": "test"}'
done
# Expected: First 30 return 200 (or guardrails responses), 31st returns 429

# 7. Test off-topic blocking via stream
curl -sN -X POST http://host.containers.internal:8400/v1/chat/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "Write me a poem about cats"}'

# Expected: JSON response (application/json, not text/event-stream) with {"message": "...", "conversation_id": null, "blocked": true}

# 8. Cleanup
podman-compose down
```

**Success criteria**: Streaming responses arrive incrementally. Unsafe chunks are withheld (only `retract_chunk` placeholders sent, no blocked content emitted). Blocked input on stream route returns JSON, not SSE. Letta errors produce explicit `error` SSE events followed by `done`. Rate limiting returns 429 after threshold. Non-streaming endpoint still works. All unit tests pass.
