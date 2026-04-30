"""Unit tests for agent persona and memory block definitions."""

from __future__ import annotations

import re

from agent.persona import KNOWLEDGE_BLOCK, PATTERNS_BLOCK, PERSONA_BLOCK


def test_persona_block_is_non_empty_string():
    """Verify PERSONA_BLOCK is a non-empty string."""
    assert isinstance(PERSONA_BLOCK, str)
    assert len(PERSONA_BLOCK.strip()) > 0


def test_knowledge_block_is_non_empty_string():
    """Verify KNOWLEDGE_BLOCK is a non-empty string."""
    assert isinstance(KNOWLEDGE_BLOCK, str)
    assert len(KNOWLEDGE_BLOCK.strip()) > 0


def test_patterns_block_is_non_empty_string():
    """Verify PATTERNS_BLOCK is a non-empty string."""
    assert isinstance(PATTERNS_BLOCK, str)
    assert len(PATTERNS_BLOCK.strip()) > 0


def test_persona_block_mentions_pii_rules():
    """Verify persona block mentions key PII storage rules."""
    assert "NEVER store user-specific information" in PERSONA_BLOCK
    assert "names, emails, API keys, user IDs" in PERSONA_BLOCK


def test_persona_block_mentions_tool_usage():
    """Verify persona block mentions using tools for real data."""
    assert "tools" in PERSONA_BLOCK.lower()
    assert "real" in PERSONA_BLOCK.lower() or "actual" in PERSONA_BLOCK.lower()


def test_persona_block_mentions_topic_boundaries():
    """Verify persona block mentions platform topic boundaries."""
    assert "LiteMaaS" in PERSONA_BLOCK or "platform" in PERSONA_BLOCK.lower()


def test_knowledge_block_mentions_key_platform_concepts():
    """Verify knowledge block mentions key platform concepts."""
    # Should mention models, subscriptions, API keys, budgets
    concepts = ["model", "subscription", "API key", "budget"]
    text_lower = KNOWLEDGE_BLOCK.lower()
    for concept in concepts:
        assert concept.lower() in text_lower, f"Missing concept: {concept}"


def test_knowledge_block_mentions_subscription_statuses():
    """Verify knowledge block mentions subscription statuses."""
    # Should mention at least some subscription statuses
    statuses = ["active", "pending", "denied", "suspended"]
    text_lower = KNOWLEDGE_BLOCK.lower()
    found_statuses = [s for s in statuses if s in text_lower]
    assert len(found_statuses) >= 2, "Should mention at least 2 subscription statuses"


def test_knowledge_block_mentions_common_issues():
    """Verify knowledge block mentions common issues or patterns."""
    # Should mention common issues or confusions
    assert "common" in KNOWLEDGE_BLOCK.lower() or "issue" in KNOWLEDGE_BLOCK.lower()


def test_patterns_block_mentions_learning():
    """Verify patterns block mentions learning from interactions."""
    # Should indicate this is a learning/evolving block
    text_lower = PATTERNS_BLOCK.lower()
    assert "updated" in text_lower or "learn" in text_lower or "interactions" in text_lower


def test_no_real_api_keys_in_persona_blocks():
    """Verify persona blocks do not contain real API keys."""
    all_text = f"{PERSONA_BLOCK}\n{KNOWLEDGE_BLOCK}\n{PATTERNS_BLOCK}"

    # Check for actual API key patterns (not just the example format)
    # Allow "sk-...a1b2" examples but not real keys like "sk-abcd1234..."
    real_key_pattern = r"\bsk-[A-Za-z0-9]{20,}\b"
    assert not re.search(real_key_pattern, all_text), (
        "Found potential real API key in persona blocks"
    )

    # Allow pedagogical examples like "alice@example.com" in persona blocks
    # since they're teaching what NOT to do. Only seeds are checked for PII.
