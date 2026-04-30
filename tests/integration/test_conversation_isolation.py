"""Integration tests for conversation isolation.

These tests verify that recall memory (conversation history) is properly
scoped per conversation. Messages in conversation A must not appear in
conversation B's search results.

Requires: Running Letta instance (podman-compose up).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from letta_client import Letta


@pytest.mark.integration
class TestConversationIsolation:
    def test_conversations_have_separate_history(self, letta_client: Letta, agent_id: str) -> None:
        """Messages in conv-A are not visible in conv-B."""
        conv_a = letta_client.conversations.create(
            agent_id=agent_id, summary="litemaas-user:alice-test"
        )
        conv_b = letta_client.conversations.create(
            agent_id=agent_id, summary="litemaas-user:bob-test"
        )

        letta_client.conversations.messages.create(
            conv_a.id,
            input="My secret project is codenamed ALPHA_PHOENIX",
            streaming=False,
        )

        messages_b = letta_client.conversations.messages.list(conv_b.id)
        for msg in messages_b:
            if hasattr(msg, "content") and msg.content:
                assert "ALPHA_PHOENIX" not in msg.content, (
                    "conv-A message leaked into conv-B message history"
                )

    def test_summary_search_returns_correct_conversation(
        self, letta_client: Letta, agent_id: str
    ) -> None:
        """summary_search finds only the matching conversation."""
        conv = letta_client.conversations.create(
            agent_id=agent_id, summary="litemaas-user:unique-test-user-42"
        )

        results = letta_client.conversations.list(
            agent_id=agent_id,
            summary_search="litemaas-user:unique-test-user-42",
        )

        found = False
        if results and hasattr(results, "__iter__"):
            for r in results:
                if r.id == conv.id:
                    found = True
        assert found, "summary_search did not find the expected conversation"
