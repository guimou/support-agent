"""API route definitions for /v1/chat."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from proxy.auth import AuthenticatedUser, validate_jwt
from proxy.rate_limit import SlidingWindowRateLimiter
from proxy.streaming import TokenBuffer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from agent.config import Settings
    from guardrails.rails import GuardrailsEngine
    from proxy.server import AgentState

logger = logging.getLogger(__name__)

router = APIRouter()

# Serializes agent secret updates. Required because the single shared Letta
# agent has one set of secrets: concurrent requests could race between
# update() and messages.create(), causing user A's request to execute with
# user B's credentials.
#
# IMPORTANT: asyncio.Lock only protects within a single event loop. The proxy
# MUST run with a single uvicorn worker (--workers 1). Multiple workers each
# get their own lock instance, breaking credential isolation entirely.
_secrets_lock = asyncio.Lock()

_chat_rate_limiter: SlidingWindowRateLimiter | None = None
_memory_write_limiter: SlidingWindowRateLimiter | None = None


def init_rate_limiters(rate_limit_rpm: int, rate_limit_memory_writes_per_hour: int) -> None:
    """Initialize rate limiters from the already-loaded Settings instance.

    Called once during lifespan startup; must be called before any request.
    """
    global _chat_rate_limiter, _memory_write_limiter
    _chat_rate_limiter = SlidingWindowRateLimiter(
        max_requests=rate_limit_rpm,
        window_seconds=60.0,
    )
    _memory_write_limiter = SlidingWindowRateLimiter(
        max_requests=rate_limit_memory_writes_per_hour,
        window_seconds=3600.0,
    )


def _get_chat_rate_limiter() -> SlidingWindowRateLimiter:
    if _chat_rate_limiter is None:
        raise RuntimeError("Rate limiters not initialized — call init_rate_limiters() first")
    return _chat_rate_limiter


def _get_memory_write_limiter() -> SlidingWindowRateLimiter:
    if _memory_write_limiter is None:
        raise RuntimeError("Rate limiters not initialized — call init_rate_limiters() first")
    return _memory_write_limiter


def check_rate_limit(user: AuthenticatedUser = Depends(validate_jwt)) -> AuthenticatedUser:  # noqa: B008
    # Check memory write limit first (non-consuming read) so we don't
    # waste a chat RPM token on a request that will be rejected anyway.
    memory_limiter = _get_memory_write_limiter()
    if memory_limiter.remaining(user.user_id) <= 0:
        reset = memory_limiter.reset_time(user.user_id)
        raise HTTPException(
            status_code=429,
            detail="Memory write limit exceeded",
            headers={
                "Retry-After": str(int(reset)),
            },
        )

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


class ChatRequest(BaseModel):
    """Request body for the /v1/chat endpoint."""

    message: str = Field(..., max_length=4000, description="User message")
    conversation_id: str | None = Field(
        None,
        pattern=r"^(conv-)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        description="Conversation ID for continuity (optional)",
    )


class ChatResponse(BaseModel):
    """Response body for the /v1/chat endpoint."""

    message: str = Field(..., description="Agent's response message")
    conversation_id: str | None = Field(
        None,
        description=(
            "Conversation ID for follow-ups (null when blocked before conversation resolution)"
        ),
    )
    blocked: bool = Field(False, description="Whether the message was blocked by guardrails")


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(check_rate_limit),  # noqa: B008
) -> ChatResponse:
    """Send a message to the agent and get a response.

    Flow:
    1. Run input guardrails
    2. Inject user context into Letta agent secrets
    3. Get or create conversation for this user
    4. Send message to Letta via conversation API
    5. Run output guardrails on response
    6. Return response
    """
    from proxy.server import ConversationLookupError, get_agent_state, get_guardrails

    agent_state = get_agent_state()
    guardrails = get_guardrails()
    if guardrails is None:
        logger.error("Guardrails unavailable — refusing request for user %s", user.user_id)
        raise HTTPException(
            status_code=503, detail="Service temporarily unavailable — guardrails not initialized"
        )

    # 1. Input guardrails
    input_result = await guardrails.check_input(request.message, user)
    if input_result.blocked:
        return ChatResponse(
            message=input_result.response,
            conversation_id=request.conversation_id,
            blocked=True,
        )

    # 2. Inject user context + get/create conversation + send message (serialized)
    async with _secrets_lock:
        try:
            agent_state.client.agents.update(
                agent_state.agent_id,
                secrets={
                    "LETTA_USER_ID": user.user_id,
                    "LETTA_USER_ROLE": "admin" if user.is_admin else "user",
                    "LITEMAAS_API_URL": agent_state.settings.litemaas_api_url,
                    "LITELLM_API_URL": agent_state.settings.litellm_api_url,
                    "LITELLM_USER_API_KEY": agent_state.settings.litellm_user_api_key,
                    "LITELLM_API_KEY": (
                        agent_state.settings.litellm_api_key if user.is_admin else ""
                    ),
                    "LITEMAAS_ADMIN_API_KEY": (
                        agent_state.settings.litemaas_admin_api_key if user.is_admin else ""
                    ),
                },
            )
        except Exception:
            logger.exception("Failed to inject user secrets for user %s", user.user_id)
            raise HTTPException(status_code=502, detail="Failed to prepare agent context") from None

        # 3. Get or create conversation (with ownership validation)
        if request.conversation_id:
            try:
                owns = agent_state.validate_conversation_ownership(
                    request.conversation_id, user.user_id
                )
            except ConversationLookupError:
                logger.exception(
                    "Could not verify conversation ownership for user %s", user.user_id
                )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to verify conversation ownership",
                ) from None
            if not owns:
                raise HTTPException(
                    status_code=403,
                    detail="Conversation does not belong to this user",
                )
            conversation_id = request.conversation_id
        else:
            try:
                conversation_id = agent_state.get_or_create_conversation(user.user_id)
            except Exception:
                logger.exception("Failed to resolve conversation for user %s", user.user_id)
                raise HTTPException(
                    status_code=502, detail="Failed to resolve conversation"
                ) from None

        # 4. Send message to Letta (may be annotated by topic classifier)
        try:
            letta_response = agent_state.client.conversations.messages.create(
                conversation_id,
                input=input_result.response,
            )
        except Exception:
            logger.exception("Letta message creation failed for user %s", user.user_id)
            raise HTTPException(status_code=502, detail="Agent failed to process message") from None

    # 5. Extract assistant message from response
    try:
        assistant_message = _extract_assistant_message(letta_response, user)
    except ValueError:
        logger.exception("Failed to parse Letta response for user %s", user.user_id)
        raise HTTPException(
            status_code=502, detail="Agent response could not be processed"
        ) from None

    # 6. Output guardrails
    output_result = await guardrails.check_output(assistant_message, user)
    if output_result.blocked:
        logger.warning(
            "Output guardrails blocked response for user %s (length=%d)",
            user.user_id,
            len(assistant_message),
        )
        assistant_message = output_result.response

    return ChatResponse(
        message=assistant_message,
        conversation_id=conversation_id,
        blocked=output_result.blocked,
    )


def _extract_assistant_message(
    response: Any,
    user: AuthenticatedUser | None = None,
) -> str:
    """Extract the assistant's text from a Letta conversation message response.

    Also tracks memory-write tool calls against the per-user rate limiter
    when *user* is provided.

    Raises ValueError when no assistant message can be extracted.
    """
    if response is None:
        raise ValueError("Letta returned None response")
    messages = []
    if hasattr(response, "__iter__"):
        for chunk in response:
            messages.append(chunk)
    else:
        messages = [response]

    text_parts = []
    for msg in messages:
        if user and hasattr(msg, "message_type") and msg.message_type == "tool_call_message":
            _count_memory_write(msg, user)
            _audit_memory_write_pii(msg, user)
        if hasattr(msg, "message_type") and msg.message_type == "assistant_message":
            if hasattr(msg, "content") and msg.content:
                text_parts.append(msg.content)
        elif (
            not hasattr(msg, "message_type")
            and hasattr(msg, "content")
            and isinstance(msg.content, str)
        ):
            text_parts.append(msg.content)

    if text_parts:
        return " ".join(text_parts)

    logger.error(
        "No assistant_message in Letta response (chunks=%d, types=%s)",
        len(messages),
        [type(m).__name__ for m in messages],
    )
    raise ValueError(f"Failed to extract assistant message from {len(messages)} response chunks")


_ERROR_STOP_REASONS = frozenset(
    {
        "error",
        "llm_api_error",
        "invalid_llm_response",
        "max_tokens_exceeded",
        "insufficient_credits",
        "context_window_overflow_in_system_prompt",
    }
)

_MEMORY_WRITE_TOOLS = frozenset(
    {
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
    }
)


def _audit_memory_write_pii(msg: Any, user: AuthenticatedUser) -> None:
    """Post-commit audit: scan memory write arguments for PII.

    Defense-in-depth layer. The primary enforcement is in the custom
    memory tool wrappers (src/tools/memory.py) which reject PII
    before the write. This catches any PII that bypasses the wrappers
    (e.g., regex gap, tool registration race).
    """
    tool_call = getattr(msg, "tool_call", None)
    if not tool_call or not hasattr(tool_call, "name"):
        return
    if tool_call.name not in _MEMORY_WRITE_TOOLS:
        return

    arguments = getattr(tool_call, "arguments", None)
    if not arguments:
        return

    if isinstance(arguments, str):
        try:
            args_dict = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            args_dict = {"raw": arguments}
    elif isinstance(arguments, dict):
        args_dict = arguments
    else:
        return

    from guardrails.actions import _PII_PATTERNS

    for key, value in args_dict.items():
        if not isinstance(value, str):
            continue
        for pattern in _PII_PATTERNS:
            match = re.search(pattern, value)
            if match:
                logger.warning(
                    "SECURITY: PII detected in committed memory write "
                    "(post-commit audit) by user %s "
                    "(tool=%s, field=%s, pattern_match=%s...). "
                    "This should have been blocked by the tool wrapper.",
                    user.user_id,
                    tool_call.name,
                    key,
                    match.group()[:10],
                )
                break


def _count_memory_write(msg: Any, user: AuthenticatedUser) -> None:
    """Record a memory write tool call against the per-user rate limiter.

    Post-hoc accounting only: by the time this runs, the write has already
    been committed inside Letta.  Enforcement happens at the pre-request
    gate in check_rate_limit(); this tracking ensures the NEXT request is
    blocked if the limit is exhausted.
    """
    tool_call = getattr(msg, "tool_call", None)
    if tool_call and hasattr(tool_call, "name") and tool_call.name in _MEMORY_WRITE_TOOLS:
        memory_limiter = _get_memory_write_limiter()
        allowed = memory_limiter.is_allowed(user.user_id)
        if not allowed:
            logger.error(
                "Memory write limit exceeded for user %s during active request "
                "(tool: %s) — write already committed, next request will be blocked",
                user.user_id,
                tool_call.name,
            )


_KNOWN_EVENT_TYPES = frozenset({"chunk", "retract_chunk", "error"})


def _json_event(
    event_type: str,
    content: str | int,
    index: int | None = None,
    retryable: bool | None = None,
) -> str:
    if event_type not in _KNOWN_EVENT_TYPES:
        logger.error("Unknown SSE event type: %r", event_type)
    if event_type == "chunk":
        return json.dumps({"chunk": content, "index": index})
    elif event_type == "retract_chunk":
        return json.dumps({"retract_chunk": content, "placeholder": "...removed..."})
    elif event_type == "error":
        return json.dumps({"error": content, "retryable": retryable or False})
    return json.dumps({event_type: content})


def _done_event(conversation_id: str, safety_notice: str | None = None) -> str:
    payload = {
        "done": True,
        "conversation_id": conversation_id,
        "safety_notice": safety_notice,
    }
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/v1/chat/stream", response_model=None)
async def chat_stream(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(check_rate_limit),  # noqa: B008
) -> StreamingResponse | JSONResponse:
    """Stream a response from the agent via SSE."""
    from proxy.server import ConversationLookupError, get_agent_state, get_guardrails

    agent_state = get_agent_state()
    guardrails = get_guardrails()
    if guardrails is None:
        logger.error("Guardrails unavailable — refusing request for user %s", user.user_id)
        raise HTTPException(
            status_code=503, detail="Service temporarily unavailable — guardrails not initialized"
        )

    # 1. Input guardrails (safe outside lock — no agent secrets involved)
    input_result = await guardrails.check_input(request.message, user)
    if input_result.blocked:
        return JSONResponse(
            content={
                "message": input_result.response,
                "conversation_id": None,
                "blocked": True,
            },
        )

    # 2. Acquire secrets lock BEFORE returning StreamingResponse.
    #    The generator releases it in its finally block, so the lock is held
    #    across the entire stream lifetime (secret injection → stream consumption).
    try:
        await asyncio.wait_for(
            _secrets_lock.acquire(),
            timeout=agent_state.settings.stream_lock_timeout_seconds,
        )
    except TimeoutError:
        raise HTTPException(status_code=503, detail="Service busy — try again shortly") from None
    try:
        try:
            agent_state.client.agents.update(
                agent_state.agent_id,
                secrets={
                    "LETTA_USER_ID": user.user_id,
                    "LETTA_USER_ROLE": "admin" if user.is_admin else "user",
                    "LITEMAAS_API_URL": agent_state.settings.litemaas_api_url,
                    "LITELLM_API_URL": agent_state.settings.litellm_api_url,
                    "LITELLM_USER_API_KEY": agent_state.settings.litellm_user_api_key,
                    "LITELLM_API_KEY": (
                        agent_state.settings.litellm_api_key if user.is_admin else ""
                    ),
                    "LITEMAAS_ADMIN_API_KEY": (
                        agent_state.settings.litemaas_admin_api_key if user.is_admin else ""
                    ),
                },
            )
        except Exception:
            logger.exception("Failed to inject user secrets for user %s", user.user_id)
            raise HTTPException(status_code=502, detail="Failed to prepare agent context") from None

        if request.conversation_id:
            try:
                owns = agent_state.validate_conversation_ownership(
                    request.conversation_id, user.user_id
                )
            except ConversationLookupError:
                logger.exception(
                    "Could not verify conversation ownership for user %s", user.user_id
                )
                raise HTTPException(
                    status_code=502,
                    detail="Unable to verify conversation ownership",
                ) from None
            if not owns:
                raise HTTPException(
                    status_code=403,
                    detail="Conversation does not belong to this user",
                )
            conversation_id = request.conversation_id
        else:
            try:
                conversation_id = agent_state.get_or_create_conversation(user.user_id)
            except Exception:
                logger.exception("Failed to resolve conversation for user %s", user.user_id)
                raise HTTPException(
                    status_code=502, detail="Failed to resolve conversation"
                ) from None
    except Exception:
        _secrets_lock.release()
        raise

    # Lock is held — _stream_response releases it when the generator finishes.
    return StreamingResponse(
        _stream_response(
            agent_state,
            guardrails,
            user,
            input_result.response,
            conversation_id,
            agent_state.settings,
        ),
        media_type="text/event-stream",
    )


async def _stream_response(
    agent_state: AgentState,
    guardrails: GuardrailsEngine,
    user: AuthenticatedUser,
    message: str,
    conversation_id: str,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """Consume the Letta stream, applying output guardrails to each chunk.

    IMPORTANT: Caller must hold _secrets_lock before entering this generator.
    The lock is released in the finally block when the generator finishes.
    """
    try:
        buffer = TokenBuffer(
            chunk_size=settings.output_rail_chunk_size,
            overlap=settings.output_rail_overlap,
        )
        chunk_index = 0
        retracted_indices: list[int] = []
        stream_deadline = asyncio.get_event_loop().time() + settings.stream_max_duration_seconds

        try:
            letta_stream = agent_state.client.conversations.messages.create(
                conversation_id,
                input=message,
                streaming=True,
                stream_tokens=True,
            )
        except Exception:
            logger.exception("Failed to create Letta stream for user %s", user.user_id)
            event = _json_event("error", "Failed to start agent stream", retryable=True)
            yield f"data: {event}\n\n"
            yield _done_event(conversation_id)
            return

        try:
            for msg in letta_stream:
                if asyncio.get_event_loop().time() > stream_deadline:
                    logger.error(
                        "Stream duration exceeded %.0fs for user %s",
                        settings.stream_max_duration_seconds,
                        user.user_id,
                    )
                    event = _json_event("error", "Stream duration limit exceeded", retryable=False)
                    yield f"data: {event}\n\n"
                    yield _done_event(conversation_id)
                    return
                if not hasattr(msg, "message_type"):
                    continue

                if msg.message_type == "error_message":
                    error_detail = getattr(msg, "message", "Unknown agent error")
                    logger.error(
                        "Letta error during streaming for user %s: %s",
                        user.user_id,
                        error_detail,
                    )
                    yield f"data: {_json_event('error', error_detail, retryable=False)}\n\n"
                    yield _done_event(conversation_id)
                    return

                if msg.message_type == "stop_reason":
                    stop = getattr(msg, "stop_reason", None)
                    if stop in _ERROR_STOP_REASONS:
                        logger.error("Letta stop reason '%s' for user %s", stop, user.user_id)
                        event = _json_event("error", f"Agent stopped: {stop}", retryable=True)
                        yield f"data: {event}\n\n"
                        yield _done_event(conversation_id)
                        return

                if msg.message_type == "tool_call_message":
                    _count_memory_write(msg, user)
                    _audit_memory_write_pii(msg, user)

                if msg.message_type == "assistant_message":
                    if isinstance(msg.content, str):
                        content = msg.content
                    elif isinstance(msg.content, list):
                        content = "".join(
                            part.text for part in msg.content if hasattr(part, "text")
                        )
                    else:
                        continue
                    if not content:
                        continue

                    chunk_with_ctx = buffer.add(content)
                    if chunk_with_ctx:
                        result = await guardrails.check_output_chunk(
                            chunk_with_ctx.text, user, chunk_with_ctx.overlap_context
                        )
                        if result.blocked:
                            yield f"data: {_json_event('retract_chunk', chunk_index)}\n\n"
                            retracted_indices.append(chunk_index)
                        else:
                            event = _json_event("chunk", chunk_with_ctx.text, chunk_index)
                            yield f"data: {event}\n\n"
                        chunk_index += 1

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
            yield _done_event(conversation_id)
            return

        safety_notice = (
            "Part of this response has been removed for safety reasons."
            if retracted_indices
            else None
        )
        yield _done_event(conversation_id, safety_notice)
    finally:
        _secrets_lock.release()
