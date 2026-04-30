import inspect
from unittest.mock import MagicMock, patch

import pytest

from tools.litellm import check_model_health, check_rate_limits, get_model_info


class TestToolSecurityInvariants:
    """Verify security invariants across all LiteLLM tools."""

    @pytest.mark.parametrize("func", [check_rate_limits])
    def test_user_id_not_in_parameters(self, func):
        """user_id must never be a function parameter."""
        sig = inspect.signature(func)
        assert "user_id" not in sig.parameters

    @pytest.mark.parametrize("func", [check_model_health, get_model_info, check_rate_limits])
    def test_source_contains_get_only(self, func):
        """Tools must only make GET requests."""
        source = inspect.getsource(func)
        assert "httpx.post" not in source
        assert "httpx.put" not in source
        assert "httpx.patch" not in source
        assert "httpx.delete" not in source

    @pytest.mark.parametrize("func", [check_rate_limits])
    def test_reads_user_id_from_env(self, func):
        """Tools that need user context must read user_id from LETTA_USER_ID env var."""
        source = inspect.getsource(func)
        assert 'os.getenv("LETTA_USER_ID")' in source

    @pytest.mark.parametrize("func", [check_model_health, get_model_info, check_rate_limits])
    def test_uses_scoped_token(self, func):
        """Standard tools must use LITELLM_USER_API_KEY, not LITELLM_API_KEY."""
        source = inspect.getsource(func)
        assert "LITELLM_USER_API_KEY" in source
        assert 'os.getenv("LITELLM_API_KEY")' not in source

    @pytest.mark.parametrize("func", [check_model_health, get_model_info, check_rate_limits])
    def test_uses_x_litellm_api_key_header(self, func):
        """LiteLLM tools must use x-litellm-api-key header, not Authorization: Bearer."""
        source = inspect.getsource(func)
        assert '"x-litellm-api-key"' in source


class TestCheckModelHealth:
    """Tests for check_model_health tool."""

    @patch("httpx.get")
    def test_handles_json_response(self, mock_get):
        mock_resp = MagicMock(
            headers={"content-type": "application/json"},
            json=lambda: {"status": "healthy", "litellm_version": "1.2.3"},
            text="",
        )
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = check_model_health()
        assert "healthy" in result
        assert "1.2.3" in result

    @patch("httpx.get")
    def test_handles_plain_text_alive_response(self, mock_get):
        mock_resp = MagicMock(
            headers={"content-type": "text/plain"},
            text="I'm alive!",
        )
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = check_model_health()
        assert "healthy (alive)" in result

    @patch("httpx.get")
    def test_handles_other_plain_text_response(self, mock_get):
        mock_resp = MagicMock(
            headers={"content-type": "text/plain"},
            text="OK",
        )
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = check_model_health()
        assert "OK" in result

    @patch("httpx.get")
    def test_raises_on_http_error(self, mock_get):
        import httpx as httpx_mod

        mock_resp = MagicMock(status_code=500)
        mock_resp.raise_for_status.side_effect = httpx_mod.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )
        mock_get.return_value = mock_resp
        with (
            patch.dict(
                "os.environ",
                {
                    "LITELLM_API_URL": "http://test",
                    "LITELLM_USER_API_KEY": "test-key",
                },
            ),
            pytest.raises(RuntimeError, match="HTTP 500"),
        ):
            check_model_health()


class TestGetModelInfo:
    """Tests for get_model_info tool."""

    @patch("httpx.get")
    def test_formats_empty_result(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = get_model_info()
        assert "No model info found" in result

    @patch("httpx.get")
    def test_formats_unlimited_sentinel_correctly(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "model_name": "gpt-4",
                        "litellm_params": {
                            "custom_llm_provider": "openai",
                            "model": "gpt-4-0125-preview",
                            "tpm": 2147483647,
                            "rpm": 2147483647,
                        },
                        "model_info": {
                            "max_tokens": 8192,
                            "supports_vision": False,
                            "supports_function_calling": True,
                        },
                    }
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = get_model_info()
        assert "Model: gpt-4" in result
        assert "TPM: unlimited" in result
        assert "RPM: unlimited" in result
        assert "8,192" in result

    @patch("httpx.get")
    def test_filters_by_model_name(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "model_name": "gpt-4",
                        "litellm_params": {"custom_llm_provider": "openai", "model": "gpt-4"},
                        "model_info": {},
                    },
                    {
                        "model_name": "claude-3",
                        "litellm_params": {"custom_llm_provider": "anthropic", "model": "claude-3"},
                        "model_info": {},
                    },
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
        ):
            result = get_model_info("gpt")
        assert "gpt-4" in result
        assert "claude-3" not in result


class TestCheckRateLimits:
    """Tests for check_rate_limits tool."""

    def test_raises_without_user_id(self):
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
            },
            clear=True,
        ):
            import os

            os.environ.pop("LETTA_USER_ID", None)
            with pytest.raises(RuntimeError, match="LETTA_USER_ID"):
                check_rate_limits()

    @patch("httpx.get")
    def test_normalizes_nested_response(self, mock_get):
        """Test that nested response format (data.info.*) is normalized."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "info": {
                    "key_name": "test-key",
                    "spend": 10.5,
                    "max_budget": 100.0,
                    "budget_reset_at": "2026-05-01",
                    "tpm_limit": 10000,
                    "rpm_limit": 100,
                    "blocked": False,
                }
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = check_rate_limits()
        assert "test-key" in result
        assert "$10.50 / $100.00" in result

    @patch("httpx.get")
    def test_normalizes_flat_response(self, mock_get):
        """Test that flat response format is normalized."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "key_name": "test-key",
                "spend": 10.5,
                "max_budget": None,
                "budget_reset_at": "never",
                "tpm_limit": 2147483647,
                "rpm_limit": None,
                "blocked": False,
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = check_rate_limits()
        assert "test-key" in result
        assert "unlimited" in result
        assert "TPM limit: unlimited" in result
        assert "RPM limit: not set" in result

    @patch("httpx.get")
    def test_includes_model_spend(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "key_name": "test-key",
                "spend": 25.0,
                "max_budget": 100.0,
                "budget_reset_at": "2026-05-01",
                "tpm_limit": 10000,
                "rpm_limit": 100,
                "blocked": False,
                "model_spend": {
                    "gpt-4": 15.0,
                    "claude-3": 10.0,
                },
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        with patch.dict(
            "os.environ",
            {
                "LITELLM_API_URL": "http://test",
                "LITELLM_USER_API_KEY": "test-key",
                "LETTA_USER_ID": "user-123",
            },
        ):
            result = check_rate_limits()
        assert "Per-model spend:" in result
        assert "gpt-4: $15.00" in result
        assert "claude-3: $10.00" in result
