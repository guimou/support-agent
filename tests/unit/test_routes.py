import json
import time
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.auth import _JwtConfig
from proxy.routes import _extract_assistant_message, router

JWT_SECRET = "test-secret-for-routes-minimum-32chars"
_TEST_JWT_CONFIG = _JwtConfig(secret=JWT_SECRET, issuer="", audience="")


def _make_test_token(user_id: str = "test-user-123", is_admin: bool = False) -> str:
    """Create a test JWT token."""
    claims = {
        "userId": user_id,
        "username": "testuser",
        "email": "test@example.com",
        "roles": ["admin", "user"] if is_admin else ["user"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def app():
    """Create a test FastAPI app with the routes."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_agent_state():
    """Mock AgentState for testing."""
    state = Mock()
    state.agent_id = "test-agent-id"
    state.client = Mock()
    state.client.agents = Mock()
    state.client.agents.update = Mock()
    state.client.conversations = Mock()
    state.client.conversations.messages = Mock()
    state.settings = Mock()
    state.settings.litemaas_api_url = "http://litemaas"
    state.settings.litellm_api_url = "http://litellm"
    state.settings.litellm_user_api_key = "user-key"
    state.settings.litellm_api_key = "admin-key"
    state.settings.litemaas_admin_api_key = "litemaas-admin-key"
    state.get_or_create_conversation = Mock(return_value="conv-123")
    state.validate_conversation_ownership = Mock(return_value=True)
    return state


@pytest.fixture(autouse=True)
def _allow_rate_limit():
    """Disable rate limiting by default in all route tests."""
    mock_limiter = Mock()
    mock_limiter.is_allowed.return_value = True
    mock_limiter.remaining.return_value = 100
    mock_limiter.reset_time.return_value = 0.0
    mock_mem_limiter = Mock()
    mock_mem_limiter.is_allowed.return_value = True
    mock_mem_limiter.remaining.return_value = 100
    mock_mem_limiter.reset_time.return_value = 0.0
    with (
        patch("proxy.routes._get_chat_rate_limiter", return_value=mock_limiter),
        patch("proxy.routes._get_memory_write_limiter", return_value=mock_mem_limiter),
    ):
        yield mock_limiter


@pytest.fixture
def mock_guardrails():
    """Mock GuardrailsEngine for testing."""
    guardrails = Mock()
    result = Mock()
    result.blocked = False
    result.response = "test response"
    guardrails.check_input = AsyncMock(return_value=result)
    guardrails.check_output = AsyncMock(return_value=result)
    return guardrails


class TestChatEndpoint:
    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_chat_requires_authentication(self, mock_secret, client):
        """Test that /v1/chat returns 401 without valid token."""
        response = client.post("/v1/chat", json={"message": "Hello"})
        assert response.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_returns_response_with_valid_token(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test successful chat with valid token."""
        # Setup mocks
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        # Output guardrails should pass through the agent's response
        output_result = Mock()
        output_result.blocked = False
        output_result.response = "Hello from agent"
        mock_guardrails.check_output = AsyncMock(return_value=output_result)

        # Mock Letta response
        mock_letta_message = Mock()
        mock_letta_message.message_type = "assistant_message"
        mock_letta_message.content = "Hello from agent"
        mock_agent_state.client.conversations.messages.create.return_value = iter(
            [mock_letta_message]
        )

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello from agent"
        assert data["conversation_id"] == "conv-123"
        assert data["blocked"] is False

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_blocked_by_input_guardrails(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret, client, mock_agent_state
    ):
        """Test that blocked messages return blocked=True and Letta is never called."""
        mock_get_agent_state.return_value = mock_agent_state

        # Setup guardrails to block input
        guardrails = Mock()
        blocked_result = Mock()
        blocked_result.blocked = True
        blocked_result.response = "This message is not allowed."
        guardrails.check_input = AsyncMock(return_value=blocked_result)
        mock_get_guardrails.return_value = guardrails

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Bad message"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["blocked"] is True
        assert data["message"] == "This message is not allowed."
        mock_agent_state.client.conversations.messages.create.assert_not_called()

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_returns_503_when_guardrails_unavailable(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret, client, mock_agent_state
    ):
        """Test that requests are refused when guardrails are not initialized."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = None

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 503
        assert "guardrails" in response.json()["detail"].lower()

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_conversation_creation_failure_returns_502(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that conversation creation failure returns 502."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.get_or_create_conversation.side_effect = Exception("SDK error")

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 502
        assert "resolve conversation" in response.json()["detail"]

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_response_parse_failure_returns_502(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that an unparseable Letta response returns 502."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.client.conversations.messages.create.return_value = iter([])

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 502
        assert "could not be processed" in response.json()["detail"]

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_with_conversation_id(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that conversation_id is used when provided."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.validate_conversation_ownership.return_value = True

        # Mock Letta response
        mock_letta_message = Mock()
        mock_letta_message.message_type = "assistant_message"
        mock_letta_message.content = "Response"
        mock_agent_state.client.conversations.messages.create.return_value = iter(
            [mock_letta_message]
        )

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello", "conversation_id": "550e8400-e29b-41d4-a716-446655440456"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "550e8400-e29b-41d4-a716-446655440456"
        # Verify ownership was validated
        mock_agent_state.validate_conversation_ownership.assert_called_once_with(
            "550e8400-e29b-41d4-a716-446655440456", "test-user-123"
        )

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_rejects_other_user_conversation(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that conversation_id belonging to another user returns 403."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        # Ownership validation fails
        mock_agent_state.validate_conversation_ownership.return_value = False

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello", "conversation_id": "550e8400-e29b-41d4-a716-446655440999"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert "does not belong" in response.json()["detail"]

    def test_message_length_limit(self, client):
        """Test that messages > 4000 chars are rejected."""
        token = _make_test_token()
        long_message = "x" * 4001

        with patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG):
            response = client.post(
                "/v1/chat",
                json={"message": long_message},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422  # Validation error

    def test_invalid_conversation_id_format_rejected(self, client):
        """Test that non-UUID conversation_id is rejected."""
        token = _make_test_token()

        with patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG):
            response = client.post(
                "/v1/chat",
                json={"message": "Hello", "conversation_id": "not-a-uuid"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_admin_user_receives_admin_key(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that admin users get the admin API key injected."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        # Mock Letta response
        mock_letta_message = Mock()
        mock_letta_message.message_type = "assistant_message"
        mock_letta_message.content = "Response"
        mock_agent_state.client.conversations.messages.create.return_value = iter(
            [mock_letta_message]
        )

        token = _make_test_token(is_admin=True)
        client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Verify admin key was set
        call_args = mock_agent_state.client.agents.update.call_args
        secrets = call_args[1]["secrets"]
        assert secrets["LETTA_USER_ROLE"] == "admin"
        assert secrets["LITELLM_API_KEY"] == "admin-key"
        assert secrets["LITEMAAS_ADMIN_API_KEY"] == "litemaas-admin-key"

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_regular_user_does_not_receive_admin_key(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that regular users do not get the admin API key."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        # Mock Letta response
        mock_letta_message = Mock()
        mock_letta_message.message_type = "assistant_message"
        mock_letta_message.content = "Response"
        mock_agent_state.client.conversations.messages.create.return_value = iter(
            [mock_letta_message]
        )

        token = _make_test_token(is_admin=False)
        client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Verify admin key is empty
        call_args = mock_agent_state.client.agents.update.call_args
        secrets = call_args[1]["secrets"]
        assert secrets["LETTA_USER_ROLE"] == "user"
        assert secrets["LITELLM_API_KEY"] == ""
        assert secrets["LITEMAAS_ADMIN_API_KEY"] == ""

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_blocked_by_output_guardrails(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
    ):
        """Test that output guardrails can block agent responses."""
        mock_get_agent_state.return_value = mock_agent_state

        # Input guardrails pass
        input_result = Mock()
        input_result.blocked = False
        input_result.response = "ok"

        # Output guardrails block
        output_result = Mock()
        output_result.blocked = True
        output_result.response = "Blocked output."

        guardrails = Mock()
        guardrails.check_input = AsyncMock(return_value=input_result)
        guardrails.check_output = AsyncMock(return_value=output_result)
        mock_get_guardrails.return_value = guardrails

        mock_letta_message = Mock()
        mock_letta_message.message_type = "assistant_message"
        mock_letta_message.content = "Unsafe content"
        mock_agent_state.client.conversations.messages.create.return_value = iter(
            [mock_letta_message]
        )

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["blocked"] is True
        assert data["message"] == "Blocked output."


    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_letta_api_error_returns_502(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that a Letta API error during message send returns 502."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.client.conversations.messages.create.side_effect = Exception(
            "Letta connection refused"
        )

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 502
        assert "Agent failed to process message" in response.json()["detail"]

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_conversation_lookup_error_returns_502(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that infrastructure errors during ownership check return 502, not 403."""
        from proxy.server import ConversationLookupError

        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.validate_conversation_ownership.side_effect = ConversationLookupError(
            "connection error"
        )

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello", "conversation_id": "550e8400-e29b-41d4-a716-446655440456"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 502
        assert "verify conversation ownership" in response.json()["detail"]

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_secret_injection_error_returns_502(
        self,
        mock_get_guardrails,
        mock_get_agent_state,
        mock_secret,
        client,
        mock_agent_state,
        mock_guardrails,
    ):
        """Test that a secret injection failure returns 502 with specific detail."""
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.client.agents.update.side_effect = Exception("SDK error")

        token = _make_test_token()
        response = client.post(
            "/v1/chat",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 502
        assert "prepare agent context" in response.json()["detail"]


class TestExtractAssistantMessage:
    def test_extract_from_assistant_message_type(self):
        """Test extracting from assistant_message type."""
        msg = Mock()
        msg.message_type = "assistant_message"
        msg.content = "Hello world"
        response = iter([msg])

        result = _extract_assistant_message(response)
        assert result == "Hello world"

    def test_extract_from_multiple_chunks(self):
        """Test extracting from multiple chunks."""
        msg1 = Mock()
        msg1.message_type = "assistant_message"
        msg1.content = "Hello"

        msg2 = Mock()
        msg2.message_type = "assistant_message"
        msg2.content = "world"

        response = iter([msg1, msg2])

        result = _extract_assistant_message(response)
        assert result == "Hello world"

    def test_extract_fallback_to_content(self):
        """Test fallback when message_type not present."""
        msg = Mock()
        msg.content = "Fallback message"
        del msg.message_type  # Simulate missing attribute

        response = iter([msg])

        result = _extract_assistant_message(response)
        assert result == "Fallback message"

    def test_extract_ignores_non_assistant_messages(self):
        """Test that non-assistant messages are ignored."""
        msg1 = Mock()
        msg1.message_type = "system_message"
        msg1.content = "System"

        msg2 = Mock()
        msg2.message_type = "assistant_message"
        msg2.content = "Assistant"

        response = iter([msg1, msg2])

        result = _extract_assistant_message(response)
        assert result == "Assistant"

    def test_extract_raises_on_empty(self):
        """Test that ValueError is raised when no content found."""
        response = iter([])

        with pytest.raises(ValueError, match="Failed to extract assistant message"):
            _extract_assistant_message(response)

    def test_extract_raises_on_none_response(self):
        """Test that ValueError is raised for None response."""
        with pytest.raises(ValueError, match="Letta returned None response"):
            _extract_assistant_message(None)


class TestChatStreamEndpoint:
    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    def test_stream_requires_authentication(self, mock_secret, client):
        response = client.post("/v1/chat/stream", json={"message": "Hello"})
        assert response.status_code == 401

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_stream_returns_event_stream_content_type(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state, mock_guardrails,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.settings.output_rail_chunk_size = 200
        mock_agent_state.settings.output_rail_overlap = 50

        mock_msg = Mock()
        mock_msg.message_type = "assistant_message"
        mock_msg.content = "Hello from agent"
        mock_agent_state.client.conversations.messages.create.return_value = iter([mock_msg])

        output_result = Mock()
        output_result.blocked = False
        output_result.response = "Hello from agent"
        mock_guardrails.check_output_chunk = AsyncMock(return_value=output_result)

        token = _make_test_token()
        response = client.post(
            "/v1/chat/stream",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_stream_blocked_input_returns_json(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        guardrails = Mock()
        blocked_result = Mock()
        blocked_result.blocked = True
        blocked_result.response = "This message is not allowed."
        guardrails.check_input = AsyncMock(return_value=blocked_result)
        mock_get_guardrails.return_value = guardrails

        token = _make_test_token()
        response = client.post(
            "/v1/chat/stream",
            json={"message": "Bad message"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data = response.json()
        assert data["blocked"] is True
        assert data["message"] == "This message is not allowed."
        assert data["conversation_id"] is None

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_stream_emits_done_event(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state, mock_guardrails,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails
        mock_agent_state.settings.output_rail_chunk_size = 200
        mock_agent_state.settings.output_rail_overlap = 50

        mock_msg = Mock()
        mock_msg.message_type = "assistant_message"
        mock_msg.content = "Hello"
        mock_agent_state.client.conversations.messages.create.return_value = iter([mock_msg])

        output_result = Mock()
        output_result.blocked = False
        output_result.response = "Hello"
        mock_guardrails.check_output_chunk = AsyncMock(return_value=output_result)

        token = _make_test_token()
        response = client.post(
            "/v1/chat/stream",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        lines = [line for line in response.text.strip().split("\n") if line.startswith("data:")]
        last_line = lines[-1]
        last_data = json.loads(last_line.removeprefix("data: "))
        assert last_data["done"] is True
        assert "conversation_id" in last_data

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_stream_returns_503_when_guardrails_unavailable(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = None

        token = _make_test_token()
        response = client.post(
            "/v1/chat/stream",
            json={"message": "Hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503


class TestRateLimiting:
    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_chat_returns_429_when_rate_limited(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state, mock_guardrails,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        mock_limiter = Mock()
        mock_limiter.is_allowed.return_value = False
        mock_limiter.remaining.return_value = 0
        mock_limiter.reset_time.return_value = 45.0

        mock_mem_limiter = Mock()
        mock_mem_limiter.remaining.return_value = 100

        token = _make_test_token()
        with (
            patch("proxy.routes._get_chat_rate_limiter", return_value=mock_limiter),
            patch("proxy.routes._get_memory_write_limiter", return_value=mock_mem_limiter),
        ):
            response = client.post(
                "/v1/chat",
                json={"message": "Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_stream_returns_429_when_rate_limited(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state, mock_guardrails,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        mock_limiter = Mock()
        mock_limiter.is_allowed.return_value = False
        mock_limiter.remaining.return_value = 0
        mock_limiter.reset_time.return_value = 45.0

        mock_mem_limiter = Mock()
        mock_mem_limiter.remaining.return_value = 100

        token = _make_test_token()
        with (
            patch("proxy.routes._get_chat_rate_limiter", return_value=mock_limiter),
            patch("proxy.routes._get_memory_write_limiter", return_value=mock_mem_limiter),
        ):
            response = client.post(
                "/v1/chat/stream",
                json={"message": "Hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 429

    @patch("proxy.auth._get_jwt_config", return_value=_TEST_JWT_CONFIG)
    @patch("proxy.server.get_agent_state")
    @patch("proxy.server.get_guardrails")
    def test_rate_limit_is_per_user(
        self, mock_get_guardrails, mock_get_agent_state, mock_secret,
        client, mock_agent_state, mock_guardrails,
    ):
        mock_get_agent_state.return_value = mock_agent_state
        mock_get_guardrails.return_value = mock_guardrails

        mock_limiter = Mock()
        def is_allowed_side_effect(key):
            return key != "test-user-123"
        mock_limiter.is_allowed.side_effect = is_allowed_side_effect
        mock_limiter.remaining.return_value = 0
        mock_limiter.reset_time.return_value = 45.0

        mock_mem_limiter = Mock()
        mock_mem_limiter.remaining.return_value = 100

        with (
            patch("proxy.routes._get_chat_rate_limiter", return_value=mock_limiter),
            patch("proxy.routes._get_memory_write_limiter", return_value=mock_mem_limiter),
        ):
            token1 = _make_test_token(user_id="test-user-123")
            r1 = client.post(
                "/v1/chat",
                json={"message": "Hello"},
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert r1.status_code == 429

            token2 = _make_test_token(user_id="other-user")
            r2 = client.post(
                "/v1/chat",
                json={"message": "Hello"},
                headers={"Authorization": f"Bearer {token2}"},
            )
            assert r2.status_code != 429
