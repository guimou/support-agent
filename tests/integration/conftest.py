"""Shared fixtures for integration tests.

Integration tests require running services (Letta, LiteMaaS, LiteLLM).
Mark all tests in this directory with @pytest.mark.integration.
"""

from __future__ import annotations

import os

import pytest
from letta_client import Letta


@pytest.fixture
def letta_client() -> Letta:
    """Create a Letta client connected to the test instance."""
    url = os.getenv("LETTA_SERVER_URL", "http://localhost:8283")
    return Letta(base_url=url)


@pytest.fixture
def agent_id(letta_client: Letta) -> str:
    """Get or create a test agent."""
    agents = letta_client.agents.list()
    for agent in agents:
        if agent.name == "test-isolation-agent":
            return agent.id

    agent = letta_client.agents.create(
        name="test-isolation-agent",
        model="letta/letta-free",
        memory_blocks=[
            {"label": "persona", "value": "Test agent", "limit": 1000},
        ],
        include_base_tools=True,
    )
    return agent.id
