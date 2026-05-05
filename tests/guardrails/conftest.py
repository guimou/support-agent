"""Shared fixtures for guardrail scenario tests."""

import asyncio

import pytest

from agent.config import Settings
from guardrails.rails import GuardrailsEngine
from proxy.auth import AuthenticatedUser


@pytest.fixture(scope="session", autouse=True)
def _check_guardrails_available() -> None:
    """Skip entire guardrails test session if engine can't initialize."""
    try:
        settings = Settings()  # type: ignore[call-arg]
        engine = GuardrailsEngine(settings)
        user = AuthenticatedUser("test", "test-user", "test@test.com", ("user",), False)
        asyncio.run(engine.check_input("hello", user))
    except Exception as e:
        pytest.skip(f"Guardrails not available: {e}")


@pytest.fixture
def guardrails_engine() -> GuardrailsEngine:
    """Create a GuardrailsEngine for testing. Requires env vars."""
    try:
        settings = Settings()  # type: ignore[call-arg]
        return GuardrailsEngine(settings)
    except Exception as e:
        pytest.skip(f"Guardrails not configured: {e}")
