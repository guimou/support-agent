"""NeMo Guardrails integration (embedded library).

Provides input/output rail evaluation via the NeMo Guardrails library.
The guardrails model is configured via config.yml and uses OpenAI-compatible provider.

Input pipeline: Llama Guard (safety, via NeMo) + agent-model topic classifier
run in parallel. Output pipeline: regex PII + Llama Guard (safety, via NeMo).

RailResult, TopicResult, and _extract_nemo_content are importable without NeMo;
GuardrailsEngine requires NeMo at runtime.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from agent.config import Settings
    from proxy.auth import AuthenticatedUser

logger = logging.getLogger(__name__)

GUARDRAILS_CONFIG_DIR = Path(__file__).parent / "config"
_MD_INLINE_RE = re.compile(r"[*_~`]")
_REFUSAL_KEYWORDS_RE = re.compile(
    r"I(?:'m| am) (?:sorry|unable|not able)|I (?:can(?:'t|not)|cannot) (?:provide|respond|help"
    r" with that|assist with that|do that)|I apologize|I need to (?:stay focused|decline)",
    re.IGNORECASE,
)

_COLANG_REFUSALS = frozenset(
    {
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
        # privacy.co (cross-user)
        "I can only access your own account information. I'm not able to look up other "
        "users' data. How can I help you with your account?",
    }
)

_INPUT_REFUSAL = (
    "I'm the LiteMaaS platform assistant. I can help you with "
    "model subscriptions, API keys, usage questions, and platform "
    "troubleshooting. How can I help?"
)

_OUTPUT_REFUSAL = (
    "I'm unable to provide a response at this time. "
    "Please try again or contact support if the issue persists."
)

_TOPIC_CHECK_TIMEOUT = 10.0

_TOPIC_SYSTEM_PROMPT = """\
You are a topic classifier for the LiteMaaS Platform Assistant.

LiteMaaS is a platform that provides access to AI models. The assistant helps users with:
- Model subscriptions and access management
- API keys (creation, management, troubleshooting)
- Usage statistics and billing
- Platform troubleshooting and errors
- Model availability, health, and rate limits
- Account and team management
- Understanding how to use the platform

Classify the user's message as:
- "on_topic" if clearly related to LiteMaaS platform operations
- "off_topic: <reason>" if clearly unrelated (e.g., creative writing, general knowledge)
- "uncertain: <reason>" if ambiguous (e.g., AI/ML questions that might relate to models)

Respond with ONLY the classification. No explanation beyond the reason tag.\
"""


@dataclass(frozen=True)
class TopicResult:
    """Result of the agent-model topic classifier."""

    status: str  # "on_topic", "off_topic", or "uncertain"
    reason: str = ""


def _extract_nemo_content(response: object) -> str:
    """Extract text content from a NeMo Guardrails response."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content") or response.get("response")
        if content is None:
            logger.error(
                "NeMo dict response has no 'content' or 'response' key (keys=%s) "
                "— returning empty string, which will trigger fail-closed blocking",
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
        if _REFUSAL_KEYWORDS_RE.search(stripped):
            return True
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
            check_user_is_admin,
            regex_check_input_cross_user,
            regex_check_output_pii,
        )

        self._rails.register_action(check_user_context, "check_user_context")
        self._rails.register_action(regex_check_output_pii, "regex_check_output_pii")
        self._rails.register_action(regex_check_input_cross_user, "regex_check_input_cross_user")
        self._rails.register_action(check_user_is_admin, "check_user_is_admin")

        self._topic_model = settings.topic_model or settings.agent_model
        self._topic_api_base = (settings.topic_llm_api_base or settings.agent_llm_api_base).rstrip(
            "/"
        )
        self._topic_api_key = settings.topic_llm_api_key or settings.agent_llm_api_key

        logger.info("NeMo Guardrails loaded from %s", GUARDRAILS_CONFIG_DIR)

    async def _check_input_safety(self, message: str, user: AuthenticatedUser) -> RailResult:
        """Run Llama Guard input safety check via NeMo (fails closed)."""
        try:
            response = await self._rails.generate_async(
                messages=[
                    {"role": "user", "content": message},
                ],
                options={
                    "rails": ["input"],
                    "context": {"user_role": user.roles[0] if user.roles else "user"},
                },
            )
            try:
                content = _extract_nemo_content(response)
            except ValueError:
                logger.error(
                    "Failed to parse NeMo response format (type=%s) — failing closed",
                    type(response).__name__,
                )
                return RailResult(blocked=True, response=_INPUT_REFUSAL)

            logger.debug("Input safety check: content=%r", content)

            blocked = self._is_blocked_input(content)
            return RailResult(
                blocked=blocked,
                response=_INPUT_REFUSAL if blocked else message,
            )

        except Exception:
            logger.exception("Input safety check error — failing closed")
            return RailResult(blocked=True, response=_INPUT_REFUSAL)

    async def _check_topic(self, message: str) -> TopicResult:
        """Classify message topic using the agent model (fails open)."""
        try:
            async with httpx.AsyncClient(timeout=_TOPIC_CHECK_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._topic_api_base}/chat/completions",
                    headers={
                        "x-litellm-api-key": self._topic_api_key,
                        "Authorization": f"Bearer {self._topic_api_key}",
                    },
                    json={
                        "model": self._topic_model,
                        "messages": [
                            {"role": "system", "content": _TOPIC_SYSTEM_PROMPT},
                            {"role": "user", "content": message},
                        ],
                        "max_tokens": 100,
                        "temperature": 0,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                resp.raise_for_status()

            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return self._parse_topic_response(text)

        except Exception:
            logger.exception("Topic classifier error — failing open")
            return TopicResult(status="on_topic")

    @staticmethod
    def _parse_topic_response(text: str) -> TopicResult:
        lower = text.lower()
        if lower.startswith("off_topic"):
            reason = text.partition(":")[2].strip() or "unrelated to LiteMaaS"
            return TopicResult(status="off_topic", reason=reason)
        if lower.startswith("uncertain"):
            reason = text.partition(":")[2].strip() or "topic relevance unclear"
            return TopicResult(status="uncertain", reason=reason)
        return TopicResult(status="on_topic")

    async def check_input(self, message: str, user: AuthenticatedUser) -> RailResult:
        """Run input guardrails: Llama Guard safety + topic classification in parallel."""
        results = await asyncio.gather(
            self._check_input_safety(message, user),
            self._check_topic(message),
            return_exceptions=True,
        )
        raw_safety, raw_topic = results[0], results[1]

        if isinstance(raw_safety, BaseException):
            logger.exception("Input safety check raised — failing closed", exc_info=raw_safety)
            return RailResult(blocked=True, response=_INPUT_REFUSAL)
        safety_result: RailResult = raw_safety

        topic_result: TopicResult
        if isinstance(raw_topic, BaseException):
            logger.exception("Topic classifier raised — failing open", exc_info=raw_topic)
            topic_result = TopicResult(status="on_topic")
        else:
            topic_result = raw_topic

        if safety_result.blocked:
            return safety_result

        if topic_result.status == "off_topic":
            logger.info("Topic classifier blocked input: %s", topic_result.reason)
            return RailResult(blocked=True, response=_INPUT_REFUSAL)

        if topic_result.status == "uncertain":
            logger.info("Topic classifier uncertain: %s", topic_result.reason)
            annotation = (
                f"[TOPIC_REVIEW: {topic_result.reason}. "
                f"Assess relevance — if off-topic, politely redirect.]\n\n{message}"
            )
            return RailResult(blocked=False, response=annotation)

        return RailResult(blocked=False, response=message)

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

            eval_text = overlap_context + chunk
            pii_context = {"bot_message": eval_text}
            if not _regex_check_output_pii_impl(pii_context):
                return RailResult(blocked=True, response=self._SAFE_FALLBACK)
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
