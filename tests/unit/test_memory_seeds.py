"""Unit tests for archival memory seeds."""

from __future__ import annotations

import re

from agent.memory_seeds import ARCHIVAL_SEEDS


def test_archival_seeds_is_non_empty_list():
    """Verify ARCHIVAL_SEEDS is a non-empty list."""
    assert isinstance(ARCHIVAL_SEEDS, list)
    assert len(ARCHIVAL_SEEDS) > 0


def test_archival_seeds_has_minimum_entries():
    """Verify ARCHIVAL_SEEDS has at least 3 entries."""
    assert len(ARCHIVAL_SEEDS) >= 3, "Should have at least 3 seed entries"


def test_each_seed_is_non_empty_string():
    """Verify each seed is a non-empty string."""
    for i, seed in enumerate(ARCHIVAL_SEEDS):
        assert isinstance(seed, str), f"Seed {i} is not a string"
        assert len(seed.strip()) > 0, f"Seed {i} is empty or whitespace-only"


def test_seeds_contain_faq_or_platform_content():
    """Verify seeds contain FAQ or platform documentation content."""
    all_seeds = "\n".join(ARCHIVAL_SEEDS)
    # Should have FAQ-style content or platform documentation
    assert "FAQ" in all_seeds or "Platform" in all_seeds or "Overview" in all_seeds


def test_seeds_mention_key_concepts():
    """Verify seeds mention key platform concepts."""
    all_seeds = "\n".join(ARCHIVAL_SEEDS).lower()
    # Should mention core platform concepts
    concepts = ["model", "api key", "subscription", "budget"]
    for concept in concepts:
        assert concept.lower() in all_seeds, f"Seeds should mention '{concept}'"


def test_seeds_provide_troubleshooting_guidance():
    """Verify seeds provide troubleshooting or diagnostic guidance."""
    all_seeds = "\n".join(ARCHIVAL_SEEDS).lower()
    # Should have diagnostic/troubleshooting content
    troubleshooting_terms = ["diagnostic", "troubleshoot", "check", "cause", "issue"]
    found_terms = [term for term in troubleshooting_terms if term in all_seeds]
    assert len(found_terms) >= 2, "Seeds should contain troubleshooting guidance"


def test_no_pii_in_seeds():
    """Verify no seed contains PII patterns (email addresses, UUIDs)."""
    all_seeds = "\n".join(ARCHIVAL_SEEDS)

    # Check for email patterns
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    email_matches = re.findall(email_pattern, all_seeds)
    assert not email_matches, f"Found email addresses in seeds: {email_matches}"

    # Check for UUID patterns
    uuid_pattern = r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    uuid_matches = re.findall(uuid_pattern, all_seeds, re.IGNORECASE)
    assert not uuid_matches, f"Found UUIDs in seeds: {uuid_matches}"


def test_no_real_api_keys_in_seeds():
    """Verify seeds do not contain real API keys."""
    all_seeds = "\n".join(ARCHIVAL_SEEDS)

    # Check for real API key patterns (not example formats like "sk-...a1b2")
    real_key_pattern = r"\bsk-[A-Za-z0-9]{20,}\b"
    key_matches = re.findall(real_key_pattern, all_seeds)
    assert not key_matches, f"Found potential real API keys in seeds: {key_matches}"


def test_seeds_are_reasonably_sized():
    """Verify each seed is reasonably sized (not too short or too long)."""
    for i, seed in enumerate(ARCHIVAL_SEEDS):
        # Seeds should be substantial but not massive
        assert len(seed) >= 50, f"Seed {i} is too short (< 50 chars)"
        assert len(seed) <= 5000, f"Seed {i} is too long (> 5000 chars)"


def test_seeds_are_distinct():
    """Verify seeds are distinct (no exact duplicates)."""
    # Check for exact duplicates
    seed_set = set(ARCHIVAL_SEEDS)
    assert len(seed_set) == len(ARCHIVAL_SEEDS), "Found duplicate seeds"
