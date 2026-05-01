"""Tests for server module (AgentState, get_agent_state, _wait_for_letta)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from proxy.server import (
    AgentState,
    ConversationLookupError,
    _wait_for_letta,
    get_agent_state,
    lifespan,
)


class TestGetAgentState:
    def test_raises_before_initialization(self) -> None:
        import proxy.server as srv

        original = srv._agent_state
        srv._agent_state = None
        try:
            with pytest.raises(RuntimeError, match="not bootstrapped"):
                get_agent_state()
        finally:
            srv._agent_state = original


class TestAgentStateGetOrCreateConversation:
    def test_returns_cached(self) -> None:
        state = AgentState(
            agent_id="a1",
            client=MagicMock(),
            tool_ids={},
            settings=MagicMock(),
        )
        state._conversation_cache["user-1"] = "conv-cached"
        assert state.get_or_create_conversation("user-1") == "conv-cached"

    def test_finds_existing_by_summary(self) -> None:
        client = MagicMock()
        conv = MagicMock()
        conv.id = "conv-found"
        conv.summary = "litemaas-user:user-2"
        client.conversations.list.return_value = [conv]

        state = AgentState(agent_id="a1", client=client, tool_ids={}, settings=MagicMock())
        result = state.get_or_create_conversation("user-2")
        assert result == "conv-found"
        assert state._conversation_cache["user-2"] == "conv-found"

    def test_creates_new_when_not_found(self) -> None:
        client = MagicMock()
        client.conversations.list.return_value = []
        new_conv = MagicMock()
        new_conv.id = "conv-new"
        client.conversations.create.return_value = new_conv

        state = AgentState(agent_id="a1", client=client, tool_ids={}, settings=MagicMock())
        result = state.get_or_create_conversation("user-3")
        assert result == "conv-new"
        client.conversations.create.assert_called_once()


class TestValidateConversationOwnership:
    def test_returns_true_for_cached_match(self) -> None:
        state = AgentState(agent_id="a1", client=MagicMock(), tool_ids={}, settings=MagicMock())
        state._conversation_cache["user-1"] = "conv-1"
        assert state.validate_conversation_ownership("conv-1", "user-1") is True

    def test_returns_true_after_lookup(self) -> None:
        client = MagicMock()
        conv = MagicMock()
        conv.summary = "litemaas-user:user-2"
        client.conversations.retrieve.return_value = conv

        state = AgentState(agent_id="a1", client=client, tool_ids={}, settings=MagicMock())
        assert state.validate_conversation_ownership("conv-2", "user-2") is True

    def test_returns_false_for_wrong_user(self) -> None:
        client = MagicMock()
        conv = MagicMock()
        conv.summary = "litemaas-user:other-user"
        client.conversations.retrieve.return_value = conv

        state = AgentState(agent_id="a1", client=client, tool_ids={}, settings=MagicMock())
        assert state.validate_conversation_ownership("conv-2", "user-2") is False

    def test_raises_conversation_lookup_error_on_exception(self) -> None:
        client = MagicMock()
        client.conversations.retrieve.side_effect = Exception("connection error")

        state = AgentState(agent_id="a1", client=client, tool_ids={}, settings=MagicMock())
        with pytest.raises(ConversationLookupError, match="Failed to retrieve"):
            state.validate_conversation_ownership("conv-bad", "user-1")


class TestWaitForLetta:
    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("proxy.server.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="not reachable"):
                await _wait_for_letta("http://localhost:9999", timeout=1, interval=0.1)

    @pytest.mark.asyncio
    async def test_returns_on_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("proxy.server.httpx.AsyncClient", return_value=mock_client):
            await _wait_for_letta("http://localhost:8283", timeout=5, interval=0.1)

        mock_client.get.assert_called()


class TestLifespanGuardrailsEnforcement:
    @pytest.mark.asyncio
    async def test_lifespan_raises_when_guardrails_required_and_init_fails(self) -> None:
        """When guardrails_required=true and guardrails init fails, lifespan raises."""
        mock_settings = MagicMock()
        mock_settings.guardrails_required = True
        mock_settings.log_level = "info"
        mock_settings.letta_server_url = "http://localhost:8283"

        with (
            patch("agent.config.Settings", return_value=mock_settings),
            patch("proxy.server._wait_for_letta", new_callable=AsyncMock),
            patch("proxy.routes.init_rate_limiters"),
            patch("agent.bootstrap.bootstrap_agent", return_value=("agent-id", MagicMock(), {})),
            patch(
                "guardrails.rails.GuardrailsEngine",
                side_effect=RuntimeError("NeMo init failed"),
            ),
            pytest.raises(RuntimeError, match="NeMo init failed"),
        ):
            app = FastAPI(lifespan=lifespan)
            async with app.router.lifespan_context(app):
                pass

    @pytest.mark.asyncio
    async def test_lifespan_continues_when_guardrails_optional_and_init_fails(self) -> None:
        """When guardrails_required=false and guardrails init fails, lifespan continues."""
        import proxy.server as srv

        mock_settings = MagicMock()
        mock_settings.guardrails_required = False
        mock_settings.log_level = "info"
        mock_settings.letta_server_url = "http://localhost:8283"

        with (
            patch("agent.config.Settings", return_value=mock_settings),
            patch("proxy.server._wait_for_letta", new_callable=AsyncMock),
            patch("proxy.routes.init_rate_limiters"),
            patch("agent.bootstrap.bootstrap_agent", return_value=("agent-id", MagicMock(), {})),
            patch(
                "guardrails.rails.GuardrailsEngine",
                side_effect=RuntimeError("NeMo init failed"),
            ),
            patch.object(srv, "_agent_state", None),
            patch.object(srv, "_guardrails", None),
        ):
            app = FastAPI(lifespan=lifespan)
            async with app.router.lifespan_context(app):
                assert srv._guardrails is None
