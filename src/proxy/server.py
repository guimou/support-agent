"""FastAPI proxy server for the LiteMaaS Agent Assistant."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

_MAX_CONVERSATION_CACHE_SIZE = 10_000

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from letta_client import Letta

    from agent.config import Settings
    from guardrails.rails import GuardrailsEngine

logger = logging.getLogger(__name__)


class ConversationLookupError(Exception):
    """Raised when conversation ownership cannot be verified due to infrastructure errors."""


@dataclass
class AgentState:
    """Holds the bootstrapped agent state for the proxy's lifetime."""

    agent_id: str
    client: Letta
    tool_ids: dict[str, str]
    settings: Settings
    _conversation_cache: OrderedDict[str, str] = field(default_factory=OrderedDict)

    def _cache_put(self, user_id: str, conversation_id: str) -> None:
        """Add entry to bounded conversation cache, evicting oldest if full."""
        self._conversation_cache[user_id] = conversation_id
        self._conversation_cache.move_to_end(user_id)
        if len(self._conversation_cache) > _MAX_CONVERSATION_CACHE_SIZE:
            self._conversation_cache.popitem(last=False)

    def get_or_create_conversation(self, user_id: str) -> str:
        """Get existing or create new conversation for a user."""
        if user_id in self._conversation_cache:
            self._conversation_cache.move_to_end(user_id)
            return self._conversation_cache[user_id]

        summary_key = f"litemaas-user:{user_id}"
        convs = self.client.conversations.list(
            agent_id=self.agent_id,
            summary_search=summary_key,
        )
        if convs and hasattr(convs, "__iter__"):
            for conv in convs:
                if conv.summary == summary_key:
                    self._cache_put(user_id, conv.id)
                    return conv.id

        conv = self.client.conversations.create(
            agent_id=self.agent_id,
            summary=summary_key,
        )
        self._cache_put(user_id, conv.id)
        logger.info("Created conversation %s for user %s", conv.id, user_id)
        return conv.id

    def validate_conversation_ownership(self, conversation_id: str, user_id: str) -> bool:
        """Verify that a conversation belongs to the given user.

        Raises ConversationLookupError on infrastructure failures so the
        caller can distinguish "not owner" (403) from "could not verify" (502).
        """
        cached_conv = self._conversation_cache.get(user_id)
        if cached_conv == conversation_id:
            return True

        summary_key = f"litemaas-user:{user_id}"
        try:
            conv = self.client.conversations.retrieve(conversation_id)
        except Exception as exc:
            raise ConversationLookupError(
                f"Failed to retrieve conversation {conversation_id}"
            ) from exc
        if conv.summary == summary_key:
            self._cache_put(user_id, conversation_id)
            return True
        return False


_agent_state: AgentState | None = None
_guardrails: GuardrailsEngine | None = None


def get_agent_state() -> AgentState:
    """Get the bootstrapped agent state. Raises if not initialized."""
    if _agent_state is None:
        raise RuntimeError("Agent not bootstrapped — server not fully started")
    return _agent_state


def get_guardrails() -> GuardrailsEngine | None:
    """Get the guardrails engine. Returns None if not configured."""
    return _guardrails  # type: ignore[return-value]


async def _wait_for_letta(base_url: str, timeout: int = 120, interval: int = 2) -> None:
    """Wait until Letta's health endpoint responds with 200."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(
                    f"{base_url}/v1/health", timeout=5, follow_redirects=True
                )
                if resp.status_code == 200:
                    logger.info("Letta is ready at %s", base_url)
                    return
                logger.info(
                    "Letta returned %d at %s, retrying...", resp.status_code, base_url
                )
            except httpx.ConnectError:
                logger.info("Letta not reachable at %s (connection refused), retrying...", base_url)
            except httpx.TimeoutException:
                logger.info("Letta health check timed out at %s, retrying...", base_url)
            except httpx.HTTPError as exc:
                logger.info("Letta health check error at %s: %s, retrying...", base_url, exc)
            await asyncio.sleep(interval)
    raise RuntimeError(f"Letta not reachable at {base_url} after {timeout}s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: bootstrap agent and guardrails on startup."""
    global _agent_state, _guardrails

    from agent.bootstrap import bootstrap_agent
    from agent.config import Settings

    settings = Settings()  # type: ignore[call-arg]

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        force=True,
    )

    import os

    workers = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS")
    if workers and int(workers) > 1:
        raise RuntimeError(
            f"Proxy MUST run with a single worker (got {workers}). "
            "The secrets lock only protects within one event loop — "
            "multiple workers break credential isolation between users."
        )

    await _wait_for_letta(settings.letta_server_url)
    logger.info("Bootstrapping agent...")
    agent_id, client, tool_ids = bootstrap_agent(settings)
    _agent_state = AgentState(
        agent_id=agent_id,
        client=client,
        tool_ids=tool_ids,
        settings=settings,
    )
    logger.info("Agent bootstrapped: %s", agent_id)

    try:
        from guardrails.rails import GuardrailsEngine

        _guardrails = GuardrailsEngine(settings)
        logger.info("Guardrails initialized")
    except Exception:
        if settings.guardrails_required:
            logger.error("Guardrails initialization failed and GUARDRAILS_REQUIRED=true")
            raise
        logger.warning(
            "Guardrails initialization failed — running without guardrails",
            exc_info=True,
        )
        _guardrails = None

    yield

    _agent_state = None
    _guardrails = None
    logger.info("Server shutdown complete")


app = FastAPI(
    title="LiteMaaS Agent Proxy",
    description="Proxy server for the LiteMaaS AI Agent Assistant",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/v1/health")
async def health() -> JSONResponse:
    """Health check endpoint for container probes."""
    base_health: dict[str, str | bool] = {}

    if _agent_state is not None:
        guardrails_active = _guardrails is not None
        if guardrails_active:
            base_health["status"] = "healthy"
            status_code = 200
        elif _agent_state.settings.guardrails_required:
            base_health["status"] = "unhealthy"
            status_code = 503
        else:
            base_health["status"] = "degraded"
            status_code = 200
        base_health["agent"] = "connected"
    else:
        base_health["status"] = "not ready"
        base_health["agent"] = "not initialized"
        status_code = 503

    base_health["guardrails"] = "active" if _guardrails is not None else "inactive"

    return JSONResponse(content=base_health, status_code=status_code)


from proxy.routes import router  # noqa: E402

app.include_router(router)
