"""API route definitions for /v1/chat."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.auth import AuthenticatedUser, validate_jwt

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
    user: AuthenticatedUser = Depends(validate_jwt),  # noqa: B008
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
            raise HTTPException(
                status_code=502, detail="Failed to prepare agent context"
            ) from None

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

        # 4. Send message to Letta
        try:
            letta_response = agent_state.client.conversations.messages.create(
                conversation_id,
                input=request.message,
            )
        except Exception:
            logger.exception("Letta message creation failed for user %s", user.user_id)
            raise HTTPException(
                status_code=502, detail="Agent failed to process message"
            ) from None

    # 5. Extract assistant message from response
    try:
        assistant_message = _extract_assistant_message(letta_response)
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


def _extract_assistant_message(response: Any) -> str:
    """Extract the assistant's text from a Letta conversation message response.

    Raises ValueError when no assistant message can be extracted.
    """
    messages = []
    try:
        for chunk in response:
            messages.append(chunk)
    except TypeError:
        if response is None:
            raise ValueError("Letta returned None response")
        messages = [response]

    text_parts = []
    for msg in messages:
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
