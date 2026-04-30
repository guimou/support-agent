"""Custom guardrail actions for NeMo Guardrails.

These actions are registered with the NeMo Guardrails runtime and can be
invoked from Colang flows via the `execute` keyword.

The pure logic lives in _*_impl functions so it can be tested without
importing NeMo (which may not be available on all Python versions).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PII_PATTERNS = [
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # Email
    r"sk-[a-zA-Z0-9]{20,}",  # Full API keys (not prefixes like sk-...xxxx)
]

_INJECTION_PATTERNS = [
    r"ignore.*instructions",
    r"ignore.*rules",
    r"pretend (you are|you're|to be)",
    r"act as (if|though)",
    r"you are now",
    r"system prompt",
    r"reveal your instructions",
    r"what are your rules",
    r"jailbreak",
    r"DAN mode",
]


def _check_user_context_impl(context: dict[str, Any] | None) -> bool:
    """Verify that a valid user_id exists in the NeMo context dict.

    Registered with the NeMo runtime but not yet invoked from any Colang
    flow. Awaits context injection logic in the proxy (Phase 2).
    """
    if context is None:
        return False
    user_id = context.get("user_id")
    return bool(user_id)


def _regex_check_output_pii_impl(context: dict[str, Any] | None) -> bool:
    """Regex pre-filter for PII in bot output (emails, API keys)."""
    if context is None:
        return False

    bot_response = context.get("last_bot_message", "")
    if not bot_response:
        return True

    return all(not re.search(pattern, bot_response) for pattern in _PII_PATTERNS)


def _regex_check_input_injection_impl(context: dict[str, Any] | None) -> bool:
    """Regex pre-filter for jailbreak / injection attempts in user input."""
    if context is None:
        return False

    user_input = context.get("last_user_message", "")
    if not user_input:
        return True

    user_lower = user_input.lower()
    return not any(re.search(pattern, user_lower) for pattern in _INJECTION_PATTERNS)


# --- NeMo @action() wrappers (delegate to impl functions) ---
# Guarded import: NeMo may not be available on all Python versions.
# The wrappers are only needed at runtime inside the Letta container.

try:
    from nemoguardrails.actions import action  # noqa: E402

    @action()  # type: ignore[untyped-decorator]
    async def check_user_context(context: dict[str, Any] | None = None) -> bool:
        return _check_user_context_impl(context)

    @action()  # type: ignore[untyped-decorator]
    async def regex_check_output_pii(context: dict[str, Any] | None = None) -> bool:
        return _regex_check_output_pii_impl(context)

    @action()  # type: ignore[untyped-decorator]
    async def regex_check_input_injection(context: dict[str, Any] | None = None) -> bool:
        return _regex_check_input_injection_impl(context)

except ImportError:
    logger.info("NeMo actions not available — action wrappers not registered (expected in tests)")

    async def check_user_context(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")

    async def regex_check_output_pii(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")

    async def regex_check_input_injection(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")
