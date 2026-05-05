"""Shared fixtures for integration tests.

Integration tests require running services (Letta, LiteMaaS, LiteLLM).
Mark all tests in this directory with @pytest.mark.integration.
"""

from __future__ import annotations

import os
import time

import httpx
import jwt
import pytest
from letta_client import Letta

# JWT secret for generating test tokens. Must match the proxy's JWT_SECRET
# when running against a live stack. Defaults to a test-only value for
# environments that start the proxy with this same default.
_TEST_JWT_SECRET = os.getenv("JWT_SECRET", "test-secret-for-integration-tests-default-key")


def _make_token(
    user_id: str,
    username: str,
    email: str,
    roles: list[str],
    exp_delta: int = 3600,
) -> str:
    """Generate a signed HS256 JWT with the proxy's expected claims."""
    now = int(time.time())
    payload = {
        "userId": user_id,
        "username": username,
        "email": email,
        "roles": roles,
        "iat": now,
        "exp": now + exp_delta,
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


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


@pytest.fixture
async def http_client() -> httpx.AsyncClient:
    """Async HTTP client pointed at the proxy.

    Reads AGENT_PROXY_URL from environment (default: http://host.containers.internal:8400).
    """
    base_url = os.getenv("AGENT_PROXY_URL", "http://host.containers.internal:8400")
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        yield client


@pytest.fixture
def user_token() -> str:
    """Valid JWT for a regular test user."""
    return _make_token(
        user_id="test-user-001",
        username="testuser",
        email="testuser@example.com",
        roles=["user"],
    )


@pytest.fixture
def expired_token() -> str:
    """Expired JWT (expiry 1 hour in the past)."""
    return _make_token(
        user_id="test-user-expired",
        username="expireduser",
        email="expired@example.com",
        roles=["user"],
        exp_delta=-3600,
    )


@pytest.fixture
def user_a_token() -> str:
    """Valid JWT for user A (cross-user isolation tests)."""
    return _make_token(
        user_id="test-user-alice",
        username="alice",
        email="alice@example.com",
        roles=["user"],
    )


@pytest.fixture
def user_b_token() -> str:
    """Valid JWT for user B (cross-user isolation tests)."""
    return _make_token(
        user_id="test-user-bob",
        username="bob",
        email="bob@example.com",
        roles=["user"],
    )


@pytest.fixture
async def user_b_conv_id(http_client: httpx.AsyncClient, user_b_token: str) -> str:
    """Create a conversation for user B and return its conversation_id.

    Sends an initial message as user B so the proxy creates and registers
    a conversation for that user. The returned ID is used in cross-user
    spoofing tests to confirm user A cannot access it.
    """
    try:
        response = await http_client.post(
            "/v1/chat",
            headers={"Authorization": f"Bearer {user_b_token}"},
            json={"message": "Hello, I am user B. This is my private conversation."},
        )
    except httpx.ConnectError:
        pytest.skip("Proxy not reachable — start the stack with podman-compose up --build")

    if response.status_code == 503:
        pytest.skip("Proxy running but guardrails/agent not ready — wait for stack to stabilize")

    assert response.status_code == 200, f"Unexpected status {response.status_code}: {response.text}"
    data = response.json()
    conv_id = data.get("conversation_id")
    if not conv_id:
        pytest.skip("No conversation_id returned — proxy may not be fully initialized")
    return conv_id
