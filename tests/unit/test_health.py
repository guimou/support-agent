"""Tests for the /v1/health endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_health_response_shape(client: TestClient) -> None:
    response = client.get("/v1/health")
    data = response.json()
    assert "status" in data
