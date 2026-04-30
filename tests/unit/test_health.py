"""Tests for the /v1/health endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_returns_503_when_not_initialized(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not ready"
    assert data["agent"] == "not initialized"


def test_health_returns_200_when_initialized(client: TestClient) -> None:
    import proxy.server as srv

    original_state = srv._agent_state
    original_guardrails = srv._guardrails
    mock_state = MagicMock()
    mock_state.agent_id = "test-agent"
    srv._agent_state = mock_state
    srv._guardrails = MagicMock()
    try:
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["agent"] == "connected"
        assert "agent_id" not in data
    finally:
        srv._agent_state = original_state
        srv._guardrails = original_guardrails


def test_health_returns_degraded_when_guardrails_optional_and_inactive(client: TestClient) -> None:
    import proxy.server as srv

    original_state = srv._agent_state
    original_guardrails = srv._guardrails
    mock_state = MagicMock()
    mock_state.agent_id = "test-agent"
    mock_state.settings.guardrails_required = False
    srv._agent_state = mock_state
    srv._guardrails = None
    try:
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["guardrails"] == "inactive"
    finally:
        srv._agent_state = original_state
        srv._guardrails = original_guardrails


def test_health_returns_503_when_guardrails_required_but_inactive(client: TestClient) -> None:
    import proxy.server as srv

    original_state = srv._agent_state
    original_guardrails = srv._guardrails
    mock_state = MagicMock()
    mock_state.agent_id = "test-agent"
    mock_state.settings.guardrails_required = True
    srv._agent_state = mock_state
    srv._guardrails = None
    try:
        response = client.get("/v1/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["guardrails"] == "inactive"
    finally:
        srv._agent_state = original_state
        srv._guardrails = original_guardrails


def test_health_response_shape(client: TestClient) -> None:
    response = client.get("/v1/health")
    data = response.json()
    assert "status" in data
    assert "guardrails" in data
