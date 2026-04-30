"""Shared fixtures for guardrail scenario tests."""

import pytest

from agent.config import Settings
from guardrails.rails import GuardrailsEngine


@pytest.fixture
def guardrails_engine():
    """Create a GuardrailsEngine for testing. Requires env vars."""
    try:
        settings = Settings()  # type: ignore[call-arg]
        return GuardrailsEngine(settings)
    except Exception as e:
        pytest.skip(f"Guardrails not configured: {e}")
