import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from proxy.auth import _JwtConfig, validate_jwt

JWT_SECRET = "test-secret-key-for-unit-tests-min32"
_TEST_JWT_CONFIG = _JwtConfig(secret=JWT_SECRET, issuer="", audience="")


def _make_token(claims: dict, secret: str = JWT_SECRET) -> str:
    """Helper to create a JWT for testing."""
    defaults = {
        "userId": "550e8400-e29b-41d4-a716-446655440001",
        "username": "alice",
        "email": "alice@example.com",
        "roles": ["user"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    defaults.update(claims)
    return jwt.encode(defaults, secret, algorithm="HS256")


def _make_request(token: str) -> MagicMock:
    """Create a mock FastAPI Request with an Authorization header."""
    request = MagicMock()
    request.headers = {"Authorization": f"Bearer {token}"}
    return request


class TestValidateJwt:
    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_valid_token(self, mock_secret):
        token = _make_token({})
        user = validate_jwt(_make_request(token))
        assert user.user_id == "550e8400-e29b-41d4-a716-446655440001"
        assert user.username == "alice"
        assert user.is_admin is False
        assert isinstance(user.roles, tuple)

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_admin_role(self, mock_secret):
        token = _make_token({"roles": ["admin", "user"]})
        user = validate_jwt(_make_request(token))
        assert user.is_admin is True

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_missing_auth_header(self, mock_secret):
        request = MagicMock()
        request.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(request)
        assert exc_info.value.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_expired_token(self, mock_secret):
        token = _make_token({"exp": int(time.time()) - 100})
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(_make_request(token))
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_invalid_signature(self, mock_secret):
        token = _make_token({}, secret="wrong-secret")
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(_make_request(token))
        assert exc_info.value.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_missing_claim(self, mock_secret):
        payload = {
            "username": "bob",
            "email": "b@b.com",
            "roles": ["user"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        # Missing userId
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(_make_request(token))
        assert exc_info.value.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_rejects_non_string_roles(self, mock_secret):
        token = _make_token({"roles": [123, True]})
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(_make_request(token))
        assert exc_info.value.status_code == 401
        assert "strings" in exc_info.value.detail.lower()

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_rejects_non_bearer_auth_scheme(self, mock_secret):
        request = MagicMock()
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        with pytest.raises(HTTPException) as exc_info:
            validate_jwt(request)
        assert exc_info.value.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_catches_unexpected_jwt_errors(self, mock_secret):
        """jwt.InvalidTokenError subclasses not explicitly listed still return 401."""
        token = _make_token({})
        with patch("jwt.decode", side_effect=jwt.ImmatureSignatureError("not yet valid")):
            with pytest.raises(HTTPException) as exc_info:
                validate_jwt(_make_request(token))
            assert exc_info.value.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_roles_are_immutable_tuple(self, mock_secret):
        token = _make_token({"roles": ["admin", "user"]})
        user = validate_jwt(_make_request(token))
        assert isinstance(user.roles, tuple)
        assert user.roles == ("admin", "user")
