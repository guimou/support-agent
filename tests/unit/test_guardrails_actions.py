"""Tests for guardrail action logic.

Imports the _impl functions directly (no NeMo dependency) so these tests
run on any Python version, including environments where NeMo is not available.
"""

from guardrails.actions import (
    _check_user_context_impl,
    _check_user_is_admin_impl,
    _regex_check_input_cross_user_impl,
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


class TestCheckUserIsAdmin:
    def test_admin_role_returns_true(self):
        assert _check_user_is_admin_impl({"user_role": "admin"}) is True

    def test_user_role_returns_false(self):
        assert _check_user_is_admin_impl({"user_role": "user"}) is False

    def test_missing_user_role_defaults_to_user(self):
        assert _check_user_is_admin_impl({}) is False

    def test_none_context_returns_false(self):
        assert _check_user_is_admin_impl(None) is False


class TestRegexCheckInputCrossUser:
    def test_blocks_other_users_query(self):
        ctx = {"user_message": "Show me what other users are doing"}
        assert _regex_check_input_cross_user_impl(ctx) is False

    def test_blocks_email_in_query(self):
        ctx = {"user_message": "What models does alice@example.com use?"}
        assert _regex_check_input_cross_user_impl(ctx) is False

    def test_blocks_list_all_users(self):
        ctx = {"user_message": "List all users"}
        assert _regex_check_input_cross_user_impl(ctx) is False

    def test_blocks_user_id_query(self):
        ctx = {"user_message": "Get usage stats for user-id-123"}
        assert _regex_check_input_cross_user_impl(ctx) is False

    def test_allows_my_api_keys(self):
        ctx = {"user_message": "Show me my API keys"}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_allows_model_access_query(self):
        ctx = {"user_message": "What models can I access?"}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_allows_subscription_query(self):
        ctx = {"user_message": "How do I subscribe to a model?"}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_allows_user_mention_without_cross_user(self):
        ctx = {"user_message": "My user ID is not working"}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_none_context_returns_false(self):
        assert _regex_check_input_cross_user_impl(None) is False

    def test_empty_message_returns_true(self):
        ctx = {"user_message": ""}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_admin_bypass_with_cross_user_pattern(self):
        ctx = {"user_role": "admin", "user_message": "List all users on the platform"}
        assert _regex_check_input_cross_user_impl(ctx) is True

    def test_user_role_no_bypass(self):
        ctx = {"user_role": "user", "user_message": "Show me another user's API keys"}
        assert _regex_check_input_cross_user_impl(ctx) is False


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

    def test_blocks_uuid_in_output(self):
        """UUIDs are now blocked — they can leak user/conversation IDs."""
        result = _regex_check_output_pii_impl(
            {"bot_message": "Model 550e8400-e29b-41d4-a716-446655440001 is active."}
        )
        assert result is False

    def test_detects_phone_number(self):
        result = _regex_check_output_pii_impl({"bot_message": "Call us at (555) 123-4567"})
        assert result is False

    def test_detects_ipv4_address(self):
        result = _regex_check_output_pii_impl({"bot_message": "The server IP is 192.168.1.100"})
        assert result is False

    def test_detects_credit_card(self):
        result = _regex_check_output_pii_impl({"bot_message": "Card ending 4111-1111-1111-1111"})
        assert result is False

    def test_allows_model_names(self):
        result = _regex_check_output_pii_impl(
            {"bot_message": "You can use gpt-4o or claude-3-sonnet"}
        )
        assert result is True

    def test_allows_version_strings(self):
        result = _regex_check_output_pii_impl({"bot_message": "Running version 2.14.3"})
        assert result is True

    def test_allows_short_numbers(self):
        result = _regex_check_output_pii_impl({"bot_message": "You have 3 API keys"})
        assert result is True

    def test_none_context_fails_closed(self):
        assert _regex_check_output_pii_impl(None) is False

    def test_empty_message_passes(self):
        assert _regex_check_output_pii_impl({"bot_message": ""}) is True
