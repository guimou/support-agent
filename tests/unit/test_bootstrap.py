"""Tests for agent bootstrap module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.bootstrap import (
    AGENT_NAME,
    SEED_VERSION_MARKER,
    _find_existing_agent,
    _seed_archival_memory,
    bootstrap_agent,
)


class TestFindExistingAgent:
    def test_returns_none_when_no_match(self) -> None:
        client = MagicMock()
        other_agent = MagicMock()
        other_agent.name = "other-agent"
        client.agents.list.return_value = [other_agent]
        assert _find_existing_agent(client) is None

    def test_returns_agent_when_name_matches(self) -> None:
        client = MagicMock()
        matching = MagicMock()
        matching.name = AGENT_NAME
        matching.id = "agent-123"
        client.agents.list.return_value = [matching]
        result = _find_existing_agent(client)
        assert result is not None
        assert result.id == "agent-123"

    def test_returns_none_for_empty_list(self) -> None:
        client = MagicMock()
        client.agents.list.return_value = []
        assert _find_existing_agent(client) is None


class TestSeedArchivalMemory:
    def test_skips_when_marker_exists(self) -> None:
        client = MagicMock()
        client.agents.passages.list.return_value = [MagicMock()]
        _seed_archival_memory(client, "agent-123")
        client.agents.passages.create.assert_not_called()

    def test_seeds_and_writes_marker_when_absent(self) -> None:
        client = MagicMock()
        client.agents.passages.list.return_value = []
        _seed_archival_memory(client, "agent-123")
        calls = client.agents.passages.create.call_args_list
        assert len(calls) >= 2
        last_call = calls[-1]
        assert SEED_VERSION_MARKER in str(last_call)


class TestBootstrapAgent:
    @patch("agent.bootstrap._seed_archival_memory")
    @patch("agent.bootstrap._register_tools")
    @patch("agent.bootstrap._find_existing_agent")
    @patch("agent.bootstrap.get_letta_client")
    def test_creates_new_agent(
        self,
        mock_client_fn: MagicMock,
        mock_find: MagicMock,
        mock_tools: MagicMock,
        mock_seed: MagicMock,
    ) -> None:
        client = MagicMock()
        mock_client_fn.return_value = client
        mock_find.return_value = None
        agent = MagicMock()
        agent.id = "new-agent-id"
        agent.name = AGENT_NAME
        client.agents.create.return_value = agent
        mock_tools.return_value = {"tool1": "id1"}

        settings = MagicMock()
        agent_id, ret_client, _tool_ids = bootstrap_agent(settings)

        assert agent_id == "new-agent-id"
        assert ret_client is client
        client.agents.create.assert_called_once()

    @patch("agent.bootstrap._seed_archival_memory")
    @patch("agent.bootstrap._register_tools")
    @patch("agent.bootstrap._find_existing_agent")
    @patch("agent.bootstrap.get_letta_client")
    def test_reuses_existing_agent(
        self,
        mock_client_fn: MagicMock,
        mock_find: MagicMock,
        mock_tools: MagicMock,
        mock_seed: MagicMock,
    ) -> None:
        client = MagicMock()
        mock_client_fn.return_value = client
        existing = MagicMock()
        existing.id = "existing-id"
        existing.name = AGENT_NAME
        mock_find.return_value = existing
        mock_tools.return_value = {}

        settings = MagicMock()
        agent_id, _, _ = bootstrap_agent(settings)

        assert agent_id == "existing-id"
        client.agents.create.assert_not_called()
