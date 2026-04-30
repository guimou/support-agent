import inspect
from unittest.mock import MagicMock, patch

import pytest

from tools.admin import get_global_usage_stats, lookup_user_subscriptions


class TestToolSecurityInvariants:
    """Verify security invariants across all admin tools."""

    @pytest.mark.parametrize("func", [get_global_usage_stats, lookup_user_subscriptions])
    def test_checks_letta_user_role(self, func):
        """Admin tools must check LETTA_USER_ROLE env var."""
        source = inspect.getsource(func)
        assert 'os.getenv("LETTA_USER_ROLE")' in source
        assert 'role != "admin"' in source or 'role == "admin"' in source

    @pytest.mark.parametrize("func", [get_global_usage_stats, lookup_user_subscriptions])
    def test_raises_permission_error_for_non_admin(self, func):
        """Admin tools must raise PermissionError for non-admin users."""
        # Test with non-admin role
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "admin-key",
                    "LETTA_USER_ROLE": "user",
                },
            ),
            pytest.raises(PermissionError, match="admin privileges"),
        ):
            if func == lookup_user_subscriptions:
                func("550e8400-e29b-41d4-a716-446655440099")
            else:
                func()

        # Test with missing role
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
            },
            clear=True,
        ):
            import os

            os.environ.pop("LETTA_USER_ROLE", None)
            with pytest.raises(PermissionError, match="admin privileges"):
                if func == lookup_user_subscriptions:
                    func("550e8400-e29b-41d4-a716-446655440099")
                else:
                    func()

    @pytest.mark.parametrize("func", [get_global_usage_stats, lookup_user_subscriptions])
    def test_uses_litemaas_admin_key(self, func):
        """Admin tools calling LiteMaaS must use LITEMAAS_ADMIN_API_KEY."""
        source = inspect.getsource(func)
        assert 'os.getenv("LITEMAAS_ADMIN_API_KEY")' in source
        assert 'os.getenv("LITELLM_USER_API_KEY")' not in source

    def test_lookup_user_subscriptions_accepts_target_user_id_parameter(self):
        """lookup_user_subscriptions must accept target_user_id as a parameter."""
        sig = inspect.signature(lookup_user_subscriptions)
        assert "target_user_id" in sig.parameters
        # This is OK — the admin is looking up someone else, not using their own user_id


class TestAdminToolEmptyApiKey:
    """Defense-in-depth: empty LITEMAAS_ADMIN_API_KEY must raise RuntimeError."""

    @pytest.mark.parametrize("func", [get_global_usage_stats, lookup_user_subscriptions])
    def test_raises_on_empty_api_key(self, func):
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "",
                    "LETTA_USER_ROLE": "admin",
                },
            ),
            pytest.raises(RuntimeError, match="LITEMAAS_ADMIN_API_KEY not set"),
        ):
            if func == lookup_user_subscriptions:
                func("550e8400-e29b-41d4-a716-446655440099")
            else:
                func()


class TestAdminToolHttpErrors:
    """Verify HTTP errors are wrapped with sanitized messages."""

    @patch("httpx.post")
    def test_get_global_usage_stats_wraps_http_error(self, mock_post):
        import httpx as httpx_mod

        mock_resp = MagicMock(status_code=500)
        mock_resp.raise_for_status.side_effect = httpx_mod.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )
        mock_post.return_value = mock_resp
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "admin-key",
                    "LETTA_USER_ROLE": "admin",
                },
            ),
            pytest.raises(RuntimeError, match="HTTP 500"),
        ):
            get_global_usage_stats()

    @patch("httpx.get")
    def test_lookup_user_subscriptions_wraps_http_error(self, mock_get):
        import httpx as httpx_mod

        mock_resp = MagicMock(status_code=403)
        mock_resp.raise_for_status.side_effect = httpx_mod.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_resp
        )
        mock_get.return_value = mock_resp
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "admin-key",
                    "LETTA_USER_ROLE": "admin",
                },
            ),
            pytest.raises(RuntimeError, match="HTTP 403"),
        ):
            lookup_user_subscriptions("550e8400-e29b-41d4-a716-446655440099")


class TestGetGlobalUsageStats:
    """Tests for get_global_usage_stats admin tool."""

    def test_uses_post_request(self):
        """This is the documented exception to the GET-only rule."""
        source = inspect.getsource(get_global_usage_stats)
        assert "httpx.post" in source
        # Verify the docstring mentions this is an exception
        assert "POST" in source

    @patch("httpx.post")
    def test_formats_global_stats(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "totals": {
                    "requests": 100000,
                    "tokens": 5000000,
                    "cost": 250.0,
                    "successRate": 98,
                },
                "modelBreakdown": [
                    {"modelName": "gpt-4", "requests": 50000, "cost": 150.0, "uniqueUsers": 25},
                    {"modelName": "claude-3", "requests": 30000, "cost": 75.0, "uniqueUsers": 20},
                ],
            },
        )
        mock_post.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
                "LETTA_USER_ROLE": "admin",
            },
        ):
            result = get_global_usage_stats()
        assert "Global Usage Statistics:" in result
        assert "100,000" in result
        assert "5,000,000" in result
        assert "$250.00" in result
        assert "gpt-4: 50,000 requests" in result
        assert "25 users" in result

    @patch("httpx.post")
    def test_sends_empty_filters(self, mock_post):
        """The tool should send an empty filter object for global stats."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"totals": {}, "modelBreakdown": []},
        )
        mock_post.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
                "LETTA_USER_ROLE": "admin",
            },
        ):
            get_global_usage_stats()
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {}


class TestLookupUserSubscriptions:
    """Tests for lookup_user_subscriptions admin tool."""

    def test_rejects_path_traversal_user_id(self):
        """target_user_id must be a valid UUID format to prevent path traversal."""
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "admin-key",
                    "LETTA_USER_ROLE": "admin",
                },
            ),
            pytest.raises(ValueError, match="Invalid user ID format"),
        ):
            lookup_user_subscriptions("../../other-endpoint")

    def test_rejects_non_uuid_user_id(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "LITEMAAS_API_URL": "http://test",
                    "LITEMAAS_ADMIN_API_KEY": "admin-key",
                    "LETTA_USER_ROLE": "admin",
                },
            ),
            pytest.raises(ValueError, match="Invalid user ID format"),
        ):
            lookup_user_subscriptions("not-a-uuid")

    @patch("httpx.get")
    def test_no_subscriptions_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
                "LETTA_USER_ROLE": "admin",
            },
        ):
            result = lookup_user_subscriptions("550e8400-e29b-41d4-a716-446655440099")
        assert "No subscriptions found" in result
        assert "550e8400-e29b-41d4-a716-446655440099" in result

    @patch("httpx.get")
    def test_formats_subscriptions(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {"modelName": "gpt-4", "provider": "openai", "status": "active"},
                    {"modelName": "claude-3", "provider": "anthropic", "status": "active"},
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
                "LETTA_USER_ROLE": "admin",
            },
        ):
            result = lookup_user_subscriptions("550e8400-e29b-41d4-a716-446655440099")
        assert "550e8400-e29b-41d4-a716-446655440099" in result
        assert "gpt-4 (openai): active" in result
        assert "claude-3 (anthropic): active" in result

    @patch("httpx.get")
    def test_calls_admin_endpoint_with_target_user_id(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITEMAAS_ADMIN_API_KEY": "admin-key",
                "LETTA_USER_ROLE": "admin",
            },
        ):
            lookup_user_subscriptions("550e8400-e29b-41d4-a716-446655440456")
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "/admin/users/550e8400-e29b-41d4-a716-446655440456/subscriptions" in call_args[0][0]
