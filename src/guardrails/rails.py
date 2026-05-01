"""NeMo Guardrails integration (embedded library).

Provides input/output rail evaluation via the NeMo Guardrails library.
The guardrails model is configured via config.yml and uses OpenAI-compatible provider.

RailResult and _extract_nemo_content are importable without NeMo; GuardrailsEngine
requires NeMo at runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nemoguardrails import LLMRails, RailsConfig

    from agent.config import Settings
    from proxy.auth import AuthenticatedUser

logger = logging.getLogger(__name__)

GUARDRAILS_CONFIG_DIR = Path(__file__).parent / "config"
_MD_INLINE_RE = re.compile(r"[*_~`]")

_COLANG_REFUSALS = frozenset({
    # NeMo default refusal (self check input)
    "I'm sorry, I can't respond to that.",
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

_INPUT_REFUSAL = (
    "I'm the LiteMaaS platform assistant. I can help you with "
    "model subscriptions, API keys, usage questions, and platform "
    "troubleshooting. How can I help?"
)

_OUTPUT_REFUSAL = (
    "I'm unable to provide a response at this time. "
    "Please try again or contact support if the issue persists."
)


def _extract_nemo_content(response: object) -> str:
    """Extract text content from a NeMo Guardrails response."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content") or response.get("response")
        if content is None:
            logger.warning(
                "NeMo dict response has no 'content' or 'response' key: %s",
                list(response.keys()),
            )
            return ""
        return str(content)
    if hasattr(response, "response") and isinstance(response.response, list):
        for msg in response.response:
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return str(msg.get("content", ""))
    if hasattr(response, "content"):
        return str(response.content)
    raise ValueError(f"Unrecognized NeMo response type: {type(response).__name__}")


@dataclass(frozen=True)
class RailResult:
    """Result of a guardrail check."""

    blocked: bool
    response: str


class GuardrailsEngine:
    """Embedded NeMo Guardrails engine for input/output rail evaluation."""

    _SAFE_FALLBACK = _OUTPUT_REFUSAL

    @staticmethod
    def _is_blocked_input(content: str | None) -> bool:
        if not content or not content.strip():
            return True
        return content.strip() in _COLANG_REFUSALS

    @staticmethod
    def _is_blocked_output(original: str, content: str | None) -> bool:
        if not content or not content.strip():
            return True
        stripped = content.strip()
        if stripped in _COLANG_REFUSALS:
            return True
        orig_stripped = original.strip()
        if stripped == orig_stripped:
            return False
        norm_orig = _MD_INLINE_RE.sub("", orig_stripped)
        norm_content = _MD_INLINE_RE.sub("", stripped)
        if norm_orig == norm_content or norm_content in norm_orig or norm_orig in norm_content:
            return False
        return len(stripped) < 200

    def __init__(self, settings: Settings) -> None:
        from nemoguardrails import LLMRails, RailsConfig

        config = RailsConfig.from_path(str(GUARDRAILS_CONFIG_DIR))

        for model_cfg in config.models:
            if model_cfg.model == "${GUARDRAILS_MODEL}":
                model_cfg.model = settings.guardrails_model
            params = model_cfg.parameters or {}
            if params.get("openai_api_base") == "${GUARDRAILS_LLM_API_BASE}":
                params["openai_api_base"] = settings.guardrails_llm_api_base
            if params.get("api_key") == "${GUARDRAILS_LLM_API_KEY}":
                params["api_key"] = settings.guardrails_llm_api_key
            params.setdefault("model_kwargs", {}).setdefault("extra_body", {})[
                "chat_template_kwargs"
            ] = {"enable_thinking": False}
            model_cfg.parameters = params

        self._rails = LLMRails(config)

        from guardrails.actions import (
            check_user_context,
            regex_check_input_injection,
            regex_check_output_pii,
        )

        self._rails.register_action(check_user_context, "check_user_context")
        self._rails.register_action(regex_check_input_injection, "regex_check_input_injection")
        self._rails.register_action(regex_check_output_pii, "regex_check_output_pii")

        logger.info("NeMo Guardrails loaded from %s", GUARDRAILS_CONFIG_DIR)

    async def check_input(self, message: str, user: AuthenticatedUser) -> RailResult:
        """Run input rails on a user message."""
        try:
            response = await self._rails.generate_async(
                messages=[
                    {"role": "user", "content": message},
                ],
                options={"rails": ["input"]},
            )
            try:
                content = _extract_nemo_content(response)
            except ValueError:
                logger.error(
                    "Failed to parse NeMo response format (type=%s) — failing closed",
                    type(response).__name__,
                )
                return RailResult(blocked=True, response=_INPUT_REFUSAL)

            logger.debug("Input guardrails: content=%r", content)

            blocked = self._is_blocked_input(content)
            return RailResult(
                blocked=blocked,
                response=_INPUT_REFUSAL if blocked else content,
            )

        except Exception:
            logger.exception("Input guardrails error — failing closed")
            return RailResult(blocked=True, response=_INPUT_REFUSAL)

    async def check_output(self, message: str, user: AuthenticatedUser) -> RailResult:
        """Run output rails on an agent response."""
        try:
            response = await self._rails.generate_async(
                messages=[
                    {"role": "user", "content": "respond to user"},
                    {"role": "assistant", "content": message},
                ],
                options={"rails": ["output"]},
            )
            try:
                content = _extract_nemo_content(response)
            except ValueError:
                logger.error(
                    "Failed to parse NeMo response format (type=%s) — failing closed",
                    type(response).__name__,
                )
                return RailResult(blocked=True, response=_OUTPUT_REFUSAL)

            logger.debug("Output guardrails: content=%r", content)

            blocked = self._is_blocked_output(message, content)
            return RailResult(
                blocked=blocked,
                response=_OUTPUT_REFUSAL if blocked else message,
            )

        except Exception:
            logger.exception("Output guardrails error — failing closed")
            return RailResult(blocked=True, response=_OUTPUT_REFUSAL)

    async def check_output_chunk(
        self,
        chunk: str,
        user: AuthenticatedUser,
        overlap_context: str = "",
    ) -> RailResult:
        try:
            from guardrails.actions import _regex_check_output_pii_impl

            pii_context = {"last_bot_message": chunk}
            if not _regex_check_output_pii_impl(pii_context):
                return RailResult(blocked=True, response=self._SAFE_FALLBACK)

            eval_text = overlap_context + chunk
            response = await self._rails.generate_async(
                messages=[
                    {"role": "user", "content": "respond to user"},
                    {"role": "assistant", "content": eval_text},
                ],
                options={"rails": ["output"]},
            )
            try:
                content = _extract_nemo_content(response)
            except ValueError:
                logger.error("Failed to parse NeMo chunk response — failing closed")
                return RailResult(blocked=True, response=self._SAFE_FALLBACK)

            blocked = self._is_blocked_output(eval_text, content)
            return RailResult(blocked=blocked, response=self._SAFE_FALLBACK if blocked else chunk)
        except Exception:
            logger.exception("Chunk guardrails error — failing closed")
            return RailResult(blocked=True, response=self._SAFE_FALLBACK)
