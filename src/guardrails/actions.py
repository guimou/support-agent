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
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",  # UUID-4
    r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)",  # Phone (US)
    r"(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)",  # IPv4
    # Credit card (Visa, Mastercard, Discover, Amex prefixes)
    r"(?<!\d)(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)",
]

_CROSS_USER_PATTERNS = [
    # --- High-signal syntactic patterns (EN/ES/FR/DE) ---
    # "other/another/different user" + translations
    r"(?:other|another|different)\s+users?",
    r"(?:otros?|diferentes?)\s+usuarios?",
    r"(?:autres?|différents?)\s+utilisateurs?",
    r"(?:andere[rns]?|verschiedene[rns]?)\s+(?:Benutzer|Nutzer|Anwender)",
    # "all/every/list users" + translations
    r"(?:all|every|list)\s+users?",
    r"(?:todos?\s+los|listar?)\s+usuarios?",
    r"(?:tous\s+les|lister?\s+les)\s+utilisateurs?",
    r"(?:alle|jeden?)\s+(?:Benutzer|Nutzer|Anwender)",
    # "someone/somebody else" + translations
    r"(?:someone|somebody)\s+else",
    r"(?:alguien|algún\s+otro)\s+(?:más|usuario)?",
    r"quelqu.un\s+d.autre",
    r"(?:jemand|jemanden)\s+andere[rns]?",
    # "how many users" + translations
    r"how\s+many\s+users",
    r"cu[áa]ntos\s+usuarios",
    r"combien\s+d.utilisateurs",
    r"wie\s+viele\s+(?:Benutzer|Nutzer)",
    # Email in input — language-independent cross-user signal
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    # user_id reference — language-independent
    r"user[\s_-]?id[\s_:-]+[a-zA-Z0-9_-]*\d[a-zA-Z0-9_-]*",
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


def _check_user_is_admin_impl(context: dict[str, Any] | None) -> bool:
    """Returns True if the user has admin role."""
    if context is None:
        return False
    return bool(context.get("user_role", "user") == "admin")


def _regex_check_input_cross_user_impl(context: dict[str, Any] | None) -> bool:
    """Detect cross-user probing patterns in user input.

    Returns True if the input is safe (no cross-user probing detected).
    Returns False if cross-user probing is detected.

    Admin bypass: if context contains user_role == "admin", the check
    is skipped (returns True). Admin tools legitimately query other
    users' data and are already gated by runtime role checks.
    """
    if context is None:
        return False

    user_role = context.get("user_role", "user")
    if user_role == "admin":
        return True

    user_message = context.get("last_user_message") or context.get("user_message", "")
    if not user_message:
        return True

    for pattern in _CROSS_USER_PATTERNS:
        if re.search(pattern, user_message, re.IGNORECASE):
            return False
    return True


def _regex_check_output_pii_impl(context: dict[str, Any] | None) -> bool:
    """Regex pre-filter for PII in bot output (emails, API keys)."""
    if context is None:
        return False

    bot_response = context.get("bot_message", "")
    if not bot_response:
        return True

    return all(not re.search(pattern, bot_response) for pattern in _PII_PATTERNS)


# --- NeMo @action() wrappers (delegate to impl functions) ---
# Guarded import: NeMo may not be available on all Python versions.
# The wrappers are only needed at runtime inside the Letta container.

try:
    from nemoguardrails.actions import action

    @action()  # type: ignore[untyped-decorator]
    async def check_user_context(context: dict[str, Any] | None = None) -> bool:
        return _check_user_context_impl(context)

    @action()  # type: ignore[untyped-decorator]
    async def regex_check_output_pii(context: dict[str, Any] | None = None) -> bool:
        return _regex_check_output_pii_impl(context)

    @action()  # type: ignore[untyped-decorator]
    async def regex_check_input_cross_user(context: dict[str, Any] | None = None) -> bool:
        return _regex_check_input_cross_user_impl(context)

    @action()  # type: ignore[untyped-decorator]
    async def check_user_is_admin(context: dict[str, Any] | None = None) -> bool:
        return _check_user_is_admin_impl(context)

except ImportError:
    logger.info("NeMo actions not available — action wrappers not registered (expected in tests)")

    async def check_user_context(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")

    async def regex_check_output_pii(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")

    async def regex_check_input_cross_user(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")

    async def check_user_is_admin(**kwargs: Any) -> bool:
        raise RuntimeError("NeMo action wrappers not available")
