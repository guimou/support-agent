"""Agent bootstrap: create or connect to Letta agent instance."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from letta_client import Letta

from agent.memory_seeds import ARCHIVAL_SEEDS
from agent.persona import KNOWLEDGE_BLOCK, PATTERNS_BLOCK, PERSONA_BLOCK

if TYPE_CHECKING:
    from letta_client.types import AgentState

    from agent.config import Settings

logger = logging.getLogger(__name__)

AGENT_NAME = "litemaas-assistant"


def get_letta_client(settings: Settings) -> Letta:
    """Create a Letta SDK client."""
    return Letta(base_url=settings.letta_server_url)


def _find_existing_agent(client: Letta) -> AgentState | None:
    """Find existing agent by name, return None if not found."""
    agents = client.agents.list()
    for agent in agents:
        if agent.name == AGENT_NAME:
            return agent
    return None


def _register_tools(client: Letta, agent_id: str) -> dict[str, str]:
    """Register all tools via upsert. Returns dict of tool_name -> tool_id."""
    from tools.admin import get_global_usage_stats, lookup_user_subscriptions
    from tools.docs import search_docs
    from tools.litellm import (
        check_model_health,
        check_rate_limits,
        get_model_info,
    )
    from tools.litemaas import (
        check_subscription,
        get_usage_stats,
        get_user_api_keys,
        list_models,
    )

    all_tools = [
        list_models,
        check_subscription,
        get_user_api_keys,
        get_usage_stats,
        check_model_health,
        get_model_info,
        check_rate_limits,
        search_docs,
        get_global_usage_stats,
        lookup_user_subscriptions,
    ]

    tool_ids: dict[str, str] = {}
    for func in all_tools:
        tool = client.tools.upsert_from_function(func=func)  # type: ignore[arg-type]  # letta-client stubs expect stricter type than plain Callable
        tool_ids[tool.name] = tool.id  # type: ignore[index]  # ToolState.name is str, dict key is str — stubs overly strict
        client.agents.tools.attach(tool.id, agent_id=agent_id)
        logger.info("Registered tool: %s (id=%s)", tool.name, tool.id)

    return tool_ids


def _register_memory_tools(client: Letta, agent_id: str, tool_ids: dict[str, str]) -> None:
    """Register PII-audited memory write wrappers, overriding built-in tools."""
    from tools.memory import archival_memory_insert, core_memory_append, core_memory_replace

    for func in [core_memory_append, core_memory_replace, archival_memory_insert]:
        tool = client.tools.upsert_from_function(func=func)  # type: ignore[arg-type]
        tool_ids[tool.name] = tool.id  # type: ignore[index]
        client.agents.tools.attach(tool.id, agent_id=agent_id)
        logger.info("Registered memory tool: %s (id=%s)", tool.name, tool.id)


SEED_VERSION_MARKER = "litemaas-seed-version:1"


def _seed_archival_memory(client: Letta, agent_id: str) -> None:
    """Seed archival memory with initial documentation. Skip if already seeded.

    Uses a deterministic version marker to detect whether seeds have been
    applied. This avoids false positives from unrelated passages and supports
    re-seeding when seeds are updated (bump the version marker).
    """
    existing = client.agents.passages.list(agent_id=agent_id, search=SEED_VERSION_MARKER, limit=1)
    if existing and len(existing) > 0:
        logger.info(
            "Archival memory already seeded (marker: %s), skipping",
            SEED_VERSION_MARKER,
        )
        return

    for seed in ARCHIVAL_SEEDS:
        client.agents.passages.create(agent_id=agent_id, text=seed)
        logger.debug("Seeded archival: %s...", seed[:60])

    client.agents.passages.create(agent_id=agent_id, text=SEED_VERSION_MARKER)
    logger.info(
        "Seeded %d archival memory entries (marker: %s)",
        len(ARCHIVAL_SEEDS),
        SEED_VERSION_MARKER,
    )


def bootstrap_agent(settings: Settings) -> tuple[str, Letta, dict[str, str]]:
    """Bootstrap the Letta agent. Returns (agent_id, client, tool_ids).

    Idempotent: safe to call on every proxy startup.
    - If agent exists by name, reuses it
    - Tool upserts are idempotent
    - Archival seeds skip if already present
    """
    client = get_letta_client(settings)

    agent = _find_existing_agent(client)
    if agent is not None:
        logger.info("Found existing agent: %s (id=%s)", agent.name, agent.id)
    else:
        agent = client.agents.create(
            name=AGENT_NAME,
            model=settings.agent_model,
            memory_blocks=[
                {"label": "persona", "value": PERSONA_BLOCK, "limit": 5000},
                {"label": "knowledge", "value": KNOWLEDGE_BLOCK, "limit": 5000},
                {"label": "patterns", "value": PATTERNS_BLOCK, "limit": 5000},
            ],
            # include_base_tools=True keeps read tools (core_memory_view,
            # archival_memory_search, conversation_search). Write tools are
            # overridden by _register_memory_tools() with PII-audited wrappers
            # (Security Invariant #5).
            include_base_tools=True,
            secrets={
                "LITEMAAS_API_URL": settings.litemaas_api_url,
                "LITELLM_API_URL": settings.litellm_api_url,
                "LITELLM_USER_API_KEY": settings.litellm_user_api_key,
                "LITELLM_API_KEY": "",  # injected per-request for admin users only
                "LITEMAAS_ADMIN_API_KEY": "",  # injected per-request for admin users only
            },
        )
        logger.info("Created agent: %s (id=%s)", agent.name, agent.id)

    tool_ids = _register_tools(client, agent.id)
    _register_memory_tools(client, agent.id, tool_ids)
    _seed_archival_memory(client, agent.id)

    return agent.id, client, tool_ids
