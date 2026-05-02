"""Tests for guardrail action logic.

Imports the _impl functions directly (no NeMo dependency) so these tests
run on any Python version, including environments where NeMo is not available.
"""

from guardrails.actions import (
    _check_user_context_impl,
    _regex_check_output_pii_impl,
)


class TestCheckUserContext:
    def test_valid_context(self):
        assert _check_user_context_impl({"user_id": "user-123"}) is True

    def test_missing_user_id(self):
        assert _check_user_context_impl({}) is False

    def test_empty_string_user_id(self):
        assert _check_user_context_impl({"user_id": ""}) is False

    def test_none_context(self):
        assert _check_user_context_impl(None) is False


class TestRegexCheckOutputPii:
    def test_clean_output(self):
        result = _regex_check_output_pii_impl({"bot_message": "Your subscription is active."})
        assert result is True

    def test_detects_email(self):
        result = _regex_check_output_pii_impl({"bot_message": "User alice@example.com has..."})
        assert result is False

    def test_detects_full_api_key(self):
        result = _regex_check_output_pii_impl({"bot_message": "Key: sk-abcdefghijklmnopqrstuvwxyz"})
        assert result is False

    def test_allows_key_prefix(self):
        result = _regex_check_output_pii_impl({"bot_message": "Key prefix: sk-...a1b2"})
        assert result is True

    def test_allows_uuid_in_output(self):
        """UUIDs are legitimate tool output (model IDs, conversation IDs)."""
        result = _regex_check_output_pii_impl(
            {"bot_message": "Model 550e8400-e29b-41d4-a716-446655440001 is active."}
        )
        assert result is True

    def test_none_context_fails_closed(self):
        assert _regex_check_output_pii_impl(None) is False

    def test_empty_message_passes(self):
        assert _regex_check_output_pii_impl({"bot_message": ""}) is True
