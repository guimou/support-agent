import inspect
from unittest.mock import MagicMock, patch

import pytest

from tools.litemaas import check_subscription, get_usage_stats, get_user_api_keys, list_models


class TestToolSecurityInvariants:
    """Verify security invariants across all LiteMaaS tools."""

    @pytest.mark.parametrize("func", [check_subscription, get_user_api_keys, get_usage_stats])
    def test_user_id_not_in_parameters(self, func):
        """user_id must never be a function parameter."""
        sig = inspect.signature(func)
        assert "user_id" not in sig.parameters

    @pytest.mark.parametrize(
        "func", [list_models, check_subscription, get_user_api_keys, get_usage_stats]
    )
    def test_source_contains_get_only(self, func):
        """Tools must only make GET requests."""
        source = inspect.getsource(func)
        assert "httpx.post" not in source
        assert "httpx.put" not in source
        assert "httpx.patch" not in source
        assert "httpx.delete" not in source

    @pytest.mark.parametrize("func", [check_subscription, get_user_api_keys, get_usage_stats])
    def test_reads_user_id_from_env(self, func):
        """Tools must read user_id from LETTA_USER_ID env var."""
        source = inspect.getsource(func)
        assert 'os.getenv("LETTA_USER_ID")' in source

    @pytest.mark.parametrize("func", [check_subscription, get_user_api_keys, get_usage_stats])
    def test_uses_scoped_token(self, func):
        """Standard tools must use LITELLM_USER_API_KEY, not LITELLM_API_KEY."""
        source = inspect.getsource(func)
        assert 'os.getenv("LITELLM_USER_API_KEY")' in source
        assert 'os.getenv("LITELLM_API_KEY")' not in source


class TestListModels:
    """Tests for list_models tool."""

    def test_raises_without_litemaas_url(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("LITEMAAS_API_URL", None)
            with pytest.raises(RuntimeError, match="LITEMAAS_API_URL"):
                list_models()

    @patch("httpx.get")
    def test_wraps_http_error(self, mock_get):
        import httpx as httpx_mod

        mock_resp = MagicMock(status_code=500)
        mock_resp.raise_for_status.side_effect = httpx_mod.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )
        mock_get.return_value = mock_resp
        with (
            patch.dict("os.environ", {"LITEMAAS_API_URL": "http://test"}),
            pytest.raises(RuntimeError, match="HTTP 500"),
        ):
            list_models()

    @patch("httpx.get")
    def test_formats_empty_result(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [], "pagination": {"total": 0}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict("os.environ", {"LITEMAAS_API_URL": "http://test"}):
            result = list_models()
        assert "No models found" in result

    @patch("httpx.get")
    def test_formats_model_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "name": "gpt-4",
                        "provider": "openai",
                        "isActive": True,
                        "restrictedAccess": False,
                    },
                    {
                        "name": "claude-3",
                        "provider": "anthropic",
                        "isActive": True,
                        "restrictedAccess": True,
                    },
                ],
                "pagination": {"total": 2},
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict("os.environ", {"LITEMAAS_API_URL": "http://test"}):
            result = list_models()
        assert "Found 2 models" in result
        assert "gpt-4 (openai) — active" in result
        assert "claude-3 (anthropic) — active [restricted]" in result

    @patch("httpx.get")
    def test_passes_search_param(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [], "pagination": {"total": 0}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict("os.environ", {"LITEMAAS_API_URL": "http://test"}):
            result = list_models("gpt")
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["params"]["search"] == "gpt"
        assert "(search: 'gpt')" in result


class TestCheckSubscription:
    """Tests for check_subscription tool."""

    @patch("httpx.get")
    def test_no_subscription_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = check_subscription("gpt-4o")
        assert "No subscription found" in result

    def test_raises_without_user_id(self):
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
            clear=True,
        ):
            # Remove LETTA_USER_ID
            import os

            os.environ.pop("LETTA_USER_ID", None)
            with pytest.raises(RuntimeError, match="LETTA_USER_ID"):
                check_subscription("gpt-4o")

    @patch("httpx.get")
    def test_formats_subscription(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "modelName": "gpt-4o",
                        "provider": "openai",
                        "status": "active",
                        "usedRequests": 100,
                        "quotaRequests": 1000,
                        "usedTokens": 5000,
                        "quotaTokens": 100000,
                        "utilizationPercent": {"requests": 10, "tokens": 5},
                        "resetAt": "2026-05-01",
                    }
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = check_subscription("gpt-4o")
        assert "gpt-4o (openai)" in result
        assert "Status: active" in result
        assert "100/1000" in result
        assert "5000/100000" in result


class TestGetUserApiKeys:
    """Tests for get_user_api_keys tool."""

    def test_raises_without_user_id(self):
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
            clear=True,
        ):
            import os

            os.environ.pop("LETTA_USER_ID", None)
            with pytest.raises(RuntimeError, match="LETTA_USER_ID"):
                get_user_api_keys()

    @patch("httpx.get")
    def test_no_keys_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = get_user_api_keys()
        assert "No API keys found" in result

    @patch("httpx.get")
    def test_wraps_http_error(self, mock_get):
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
                    "LITELLM_USER_API_KEY": "test-key",
                    "LETTA_USER_ID": "user-123",
                },
            ),
            pytest.raises(RuntimeError, match="HTTP 403"),
        ):
            get_user_api_keys()

    @patch("httpx.get")
    def test_revoked_key_status(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "name": "Revoked Key",
                        "prefix": "sk-rev",
                        "isActive": False,
                        "revokedAt": "2026-04-01",
                        "currentSpend": 0,
                        "syncStatus": "synced",
                        "models": [],
                    }
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = get_user_api_keys()
        assert "Status: revoked" in result

    @patch("httpx.get")
    def test_formats_api_keys(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "name": "Production Key",
                        "prefix": "sk-abc",
                        "isActive": True,
                        "maxBudget": 100.0,
                        "currentSpend": 25.5,
                        "syncStatus": "synced",
                        "models": ["gpt-4", "claude-3"],
                        "expiresAt": "2026-12-31",
                    }
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = get_user_api_keys()
        assert "Production Key (sk-abc)" in result
        assert "Status: active" in result
        assert "$25.50/$100.00" in result
        assert "gpt-4, claude-3" in result


class TestGetUsageStats:
    """Tests for get_usage_stats tool."""

    def test_raises_without_user_id(self):
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
            clear=True,
        ):
            import os

            os.environ.pop("LETTA_USER_ID", None)
            with pytest.raises(RuntimeError, match="LETTA_USER_ID"):
                get_usage_stats()

    @patch("httpx.get")
    def test_formats_usage_stats(self, mock_get):
        def side_effect(url, **kwargs):
            if "budget" in url:
                return MagicMock(
                    status_code=200,
                    json=lambda: {
                        "maxBudget": 100.0,
                        "currentSpend": 45.0,
                        "budgetDuration": "monthly",
                        "budgetResetAt": "2026-05-01",
                    },
                    raise_for_status=lambda: None,
                )
            else:  # summary endpoint
                return MagicMock(
                    status_code=200,
                    json=lambda: {
                        "totals": {
                            "requests": 5000,
                            "tokens": 100000,
                            "cost": 25.5,
                            "successRate": 95,
                        },
                        "byModel": [
                            {"modelName": "gpt-4", "requests": 3000, "cost": 20.0},
                            {"modelName": "claude-3", "requests": 2000, "cost": 5.5},
                        ],
                    },
                    raise_for_status=lambda: None,
                )

        mock_get.side_effect = side_effect
        with patch.dict(
            "os.environ",
            {
                "LITEMAAS_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = get_usage_stats()
        assert "$45.00 / $100.00" in result
        assert "monthly" in result
        assert "5,000" in result
        assert "100,000" in result
        assert "$25.50" in result
        assert "gpt-4: 3,000 requests" in result
