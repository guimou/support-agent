"""Shared fixtures for unit tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from proxy.server import app


@pytest.fixture
def client() -> TestClient:
    """Create a FastAPI test client."""
    return TestClient(app)
