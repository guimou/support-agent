"""Unit tests for GuardrailsEngine.

Tests for RailResult, TopicResult, _extract_nemo_content, _parse_topic_response,
and _is_blocked do NOT need NeMo and always run.  Tests for check_input /
check_output need GuardrailsEngine (NeMo) and are skipped when NeMo is unavailable.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardrails.rails import RailResult, TopicResult, _extract_nemo_content
from proxy.auth import AuthenticatedUser

# GuardrailsEngine.__init__ imports NeMo at runtime, but the class itself
# can be imported. However, instantiation requires NeMo, so we check
# whether NeMo is actually importable for tests that need an engine instance.
_nemo_available = True
try:
    import nemoguardrails  # noqa: F401
except (ImportError, TypeError):
    _nemo_available = False

from guardrails.rails import GuardrailsEngine  # noqa: E402


@pytest.fixture
def mock_settings():
    return MagicMock()


@pytest.fixture
def mock_user():
    return AuthenticatedUser(
        user_id="user-123",
        username="alice",
        email="alice@example.com",
        roles=("user",),
        is_admin=False,
    )


class TestRailResult:
    def test_rail_result_fields(self):
        result = RailResult(blocked=True, response="Blocked message")
        assert result.blocked is True
        assert result.response == "Blocked message"

    def test_rail_result_frozen(self):
        result = RailResult(blocked=False, response="OK")
        with pytest.raises(AttributeError):
            result.blocked = True


class TestExtractNemoContent:
    def test_string_response(self):
        assert _extract_nemo_content("Hello") == "Hello"

    def test_dict_with_content_key(self):
        assert _extract_nemo_content({"content": "Hello"}) == "Hello"

    def test_dict_with_response_key(self):
        assert _extract_nemo_content({"response": "Hello"}) == "Hello"

    def test_dict_prefers_content_over_response(self):
        assert _extract_nemo_content({"content": "A", "response": "B"}) == "A"

    def test_object_with_response_list(self):
        obj = MagicMock()
        obj.response = [{"role": "assistant", "content": "Hello"}]
        del obj.content
        assert _extract_nemo_content(obj) == "Hello"

    def test_object_with_content_attribute(self):
        obj = MagicMock()
        obj.content = "Hello"
        del obj.response
        assert _extract_nemo_content(obj) == "Hello"

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unrecognized NeMo response type"):
            _extract_nemo_content(42)


class TestIsBlockedInput:
    _TOPIC_REFUSAL = (
        "I'm the LiteMaaS platform assistant. I can help you with model subscriptions, "
        "API keys, usage questions, and platform troubleshooting. For other topics, "
        "I'd suggest using the models directly via the Chat Playground!"
    )
    _SAFETY_REFUSAL = (
        "I apologize, but I'm unable to provide that information. Is there something "
        "else about the LiteMaaS platform I can help you with?"
    )
    _JAILBREAK_REFUSAL = (
        "I'm the LiteMaaS platform assistant and I need to stay focused on helping "
        "you with platform questions. How can I help you with models, subscriptions, "
        "or API keys?"
    )

    def test_empty_response_is_blocked(self):
        assert GuardrailsEngine._is_blocked_input("") is True
        assert GuardrailsEngine._is_blocked_input("   ") is True

    def test_none_content_is_blocked(self):
        assert GuardrailsEngine._is_blocked_input(None) is True

    def test_colang_topic_refusal_detected(self):
        assert GuardrailsEngine._is_blocked_input(self._TOPIC_REFUSAL) is True

    def test_colang_safety_refusal_detected(self):
        assert GuardrailsEngine._is_blocked_input(self._SAFETY_REFUSAL) is True

    def test_colang_jailbreak_refusal_detected(self):
        assert GuardrailsEngine._is_blocked_input(self._JAILBREAK_REFUSAL) is True

    def test_leading_whitespace_on_refusal(self):
        assert GuardrailsEngine._is_blocked_input("  " + self._TOPIC_REFUSAL) is True

    def test_normal_response_allowed(self):
        assert GuardrailsEngine._is_blocked_input("Your API key is: sk-...a1b2") is False

    def test_no_false_positive_on_sorry(self):
        assert GuardrailsEngine._is_blocked_input("I'm sorry, your budget is low") is False

    def test_no_false_positive_on_unfortunately(self):
        msg = "Unfortunately, that model is not available yet."
        assert GuardrailsEngine._is_blocked_input(msg) is False


class TestIsBlockedOutput:
    _COLANG_REFUSAL = (
        "I apologize, but I'm unable to provide that information. Is there something "
        "else about the LiteMaaS platform I can help you with?"
    )

    def test_empty_response_is_blocked(self):
        assert GuardrailsEngine._is_blocked_output("original", "") is True
        assert GuardrailsEngine._is_blocked_output("original", "   ") is True

    def test_none_content_is_blocked(self):
        assert GuardrailsEngine._is_blocked_output("original", None) is True

    def test_colang_refusal_detected(self):
        assert GuardrailsEngine._is_blocked_output("something else", self._COLANG_REFUSAL) is True

    def test_passthrough_not_blocked(self):
        text = "Your subscription is active."
        assert GuardrailsEngine._is_blocked_output(text, text) is False

    def test_novel_short_refusal_blocked(self):
        result = GuardrailsEngine._is_blocked_output("original text", "totally different short")
        assert result is True

    def test_long_different_content_not_blocked(self):
        original = "Original content here"
        long_content = "A" * 201
        assert GuardrailsEngine._is_blocked_output(original, long_content) is False

    def test_substring_reformatting_not_blocked(self):
        original = "Your subscription is **active** and renews soon."
        subset = "Your subscription is **active**"
        assert GuardrailsEngine._is_blocked_output(original, subset) is False

    def test_long_refusal_with_keywords_is_blocked(self):
        original = "Tell me about all users in the system"
        long_refusal = (
            "I understand you're asking about that, but I'm not able to provide "
            "information that could compromise security. Instead, let me help you "
            "with something else about the LiteMaaS platform that I can assist with."
        )
        assert len(long_refusal) > 200
        assert GuardrailsEngine._is_blocked_output(original, long_refusal) is True

    def test_long_non_refusal_content_not_blocked(self):
        original = "Tell me about models"
        long_content = (
            "Here is a detailed explanation of the available models on the platform. "
            "We support several model families including GPT-4, Claude, and Llama. "
            "Each model has different capabilities, pricing, and rate limits. "
            "You can check your subscription status for any model."
        )
        assert len(long_content) > 200
        assert GuardrailsEngine._is_blocked_output(original, long_content) is False


class TestParseTopicResponse:
    def test_on_topic(self):
        result = GuardrailsEngine._parse_topic_response("on_topic")
        assert result.status == "on_topic"
        assert result.reason == ""

    def test_off_topic_with_reason(self):
        result = GuardrailsEngine._parse_topic_response("off_topic: asks about weather")
        assert result.status == "off_topic"
        assert result.reason == "asks about weather"

    def test_uncertain_with_reason(self):
        result = GuardrailsEngine._parse_topic_response(
            "uncertain: mentions AI models but not specifically LiteMaaS"
        )
        assert result.status == "uncertain"
        assert "AI models" in result.reason

    def test_off_topic_no_reason_gets_default(self):
        result = GuardrailsEngine._parse_topic_response("off_topic")
        assert result.status == "off_topic"
        assert result.reason == "unrelated to LiteMaaS"

    def test_uncertain_no_reason_gets_default(self):
        result = GuardrailsEngine._parse_topic_response("uncertain")
        assert result.status == "uncertain"
        assert result.reason == "topic relevance unclear"

    def test_case_insensitive(self):
        result = GuardrailsEngine._parse_topic_response("Off_Topic: poetry request")
        assert result.status == "off_topic"

    def test_unknown_response_treated_as_on_topic(self):
        result = GuardrailsEngine._parse_topic_response("I think this is fine")
        assert result.status == "on_topic"

    def test_empty_string_treated_as_on_topic(self):
        result = GuardrailsEngine._parse_topic_response("")
        assert result.status == "on_topic"


class TestTopicResult:
    def test_frozen(self):
        result = TopicResult(status="on_topic")
        with pytest.raises(AttributeError):
            result.status = "off_topic"

    def test_default_reason(self):
        result = TopicResult(status="on_topic")
        assert result.reason == ""


@pytest.mark.skipif(not _nemo_available, reason="NeMo Guardrails not available")
class TestGuardrailsEngineCheckInput:
    @pytest.fixture
    def engine(self, mock_settings):
        with (
            patch("nemoguardrails.RailsConfig.from_path"),
            patch("nemoguardrails.LLMRails") as mock_rails_cls,
        ):
            mock_rails = AsyncMock()
            mock_rails_cls.return_value = mock_rails
            engine = GuardrailsEngine(mock_settings)
            engine._rails = mock_rails
            return engine

    async def test_on_topic_safe_message_passes_through(self, engine, mock_user):
        engine._rails.generate_async.return_value = "How can I help you with that?"
        with patch.object(engine, "_check_topic", return_value=TopicResult(status="on_topic")):
            result = await engine.check_input("Why can't I access gpt-4o?", mock_user)
        assert result.blocked is False
        assert result.response == "Why can't I access gpt-4o?"

    async def test_safety_block_wins_over_on_topic(self, engine, mock_user):
        engine._rails.generate_async.return_value = "I'm sorry, I can't respond to that."
        with patch.object(engine, "_check_topic", return_value=TopicResult(status="on_topic")):
            result = await engine.check_input("Tell me how to make a bomb", mock_user)
        assert result.blocked is True

    async def test_safety_block_wins_over_off_topic(self, engine, mock_user):
        engine._rails.generate_async.return_value = "I'm sorry, I can't respond to that."
        with patch.object(
            engine, "_check_topic", return_value=TopicResult(status="off_topic", reason="violent")
        ):
            result = await engine.check_input("Dangerous content", mock_user)
        assert result.blocked is True

    async def test_off_topic_blocks_with_refusal(self, engine, mock_user):
        engine._rails.generate_async.return_value = "Sure, I can help with that"
        with patch.object(
            engine,
            "_check_topic",
            return_value=TopicResult(status="off_topic", reason="asks about weather"),
        ):
            result = await engine.check_input("What's the weather?", mock_user)
        assert result.blocked is True
        assert "litemaas platform assistant" in result.response.lower()

    async def test_uncertain_annotates_message(self, engine, mock_user):
        engine._rails.generate_async.return_value = "I can help you"
        with patch.object(
            engine,
            "_check_topic",
            return_value=TopicResult(status="uncertain", reason="mentions AI models generically"),
        ):
            result = await engine.check_input("Tell me about Llama models", mock_user)
        assert result.blocked is False
        assert "[TOPIC_REVIEW:" in result.response
        assert "mentions AI models generically" in result.response
        assert "Tell me about Llama models" in result.response

    async def test_safety_error_fails_closed(self, engine, mock_user):
        engine._rails.generate_async.side_effect = RuntimeError("NeMo error")
        with patch.object(engine, "_check_topic", return_value=TopicResult(status="on_topic")):
            result = await engine.check_input("Any message", mock_user)
        assert result.blocked is True
        assert "litemaas platform assistant" in result.response.lower()

    async def test_topic_error_fails_open(self, engine, mock_user):
        engine._rails.generate_async.return_value = "I can help you with that"
        with patch.object(engine, "_check_topic", side_effect=RuntimeError("API error")):
            result = await engine.check_input("Some question", mock_user)
        assert result.blocked is False


@pytest.mark.skipif(not _nemo_available, reason="NeMo Guardrails not available")
class TestCheckTopic:
    @pytest.fixture
    def engine(self, mock_settings):
        with (
            patch("nemoguardrails.RailsConfig.from_path"),
            patch("nemoguardrails.LLMRails") as mock_rails_cls,
        ):
            mock_rails = AsyncMock()
            mock_rails_cls.return_value = mock_rails
            engine = GuardrailsEngine(mock_settings)
            engine._rails = mock_rails
            return engine

    def _mock_httpx_response(self, content: str, status_code: int = 200):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = {
            "choices": [{"message": {"content": content}}],
        }
        mock_response.raise_for_status = MagicMock()
        if status_code >= 400:
            mock_response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return mock_response

    async def test_on_topic_response(self, engine):
        mock_resp = self._mock_httpx_response("on_topic")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await engine._check_topic("What models are available?")
        assert result.status == "on_topic"

    async def test_off_topic_response(self, engine):
        mock_resp = self._mock_httpx_response("off_topic: asks about weather")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await engine._check_topic("What's the weather?")
        assert result.status == "off_topic"
        assert result.reason == "asks about weather"

    async def test_uncertain_response(self, engine):
        mock_resp = self._mock_httpx_response("uncertain: mentions AI but not LiteMaaS")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await engine._check_topic("Tell me about Llama models")
        assert result.status == "uncertain"

    async def test_api_error_fails_open(self, engine):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await engine._check_topic("Any message")
        assert result.status == "on_topic"

    async def test_timeout_fails_open(self, engine):
        import httpx as real_httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = real_httpx.TimeoutException("timed out")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await engine._check_topic("Any message")
        assert result.status == "on_topic"


@pytest.mark.skipif(not _nemo_available, reason="NeMo Guardrails not available")
class TestGuardrailsEngineCheckOutput:
    @pytest.fixture
    def engine(self, mock_settings):
        with (
            patch("nemoguardrails.RailsConfig.from_path"),
            patch("nemoguardrails.LLMRails") as mock_rails_cls,
        ):
            mock_rails = AsyncMock()
            mock_rails_cls.return_value = mock_rails
            engine = GuardrailsEngine(mock_settings)
            engine._rails = mock_rails
            return engine

    async def test_check_output_allows_safe_response(self, engine, mock_user):
        safe_response = "Your subscription is active."
        engine._rails.generate_async.return_value = safe_response
        result = await engine.check_output(safe_response, mock_user)
        assert result.blocked is False
        assert result.response == safe_response

    async def test_check_output_returns_original_not_nemo_reformatted(self, engine, mock_user):
        """Ensure the original agent message is returned, not NeMo's reformatted version."""
        original = "Your subscription is **active** and renews on 2026-05-01."
        nemo_reformatted = "Your subscription is active and renews on 2026-05-01."
        engine._rails.generate_async.return_value = nemo_reformatted
        result = await engine.check_output(original, mock_user)
        assert result.blocked is False
        assert result.response == original

    async def test_check_output_blocks_unsafe_response(self, engine, mock_user):
        unsafe_response = "User alice@example.com has access."
        engine._rails.generate_async.return_value = (
            "I apologize, but I'm unable to provide that information. Is there something "
            "else about the LiteMaaS platform I can help you with?"
        )
        result = await engine.check_output(unsafe_response, mock_user)
        assert result.blocked is True
        assert result.response == GuardrailsEngine._SAFE_FALLBACK

    async def test_check_output_fails_closed_on_error(self, engine, mock_user):
        engine._rails.generate_async.side_effect = RuntimeError("NeMo error")
        result = await engine.check_output("Any response", mock_user)
        assert result.blocked is True
        assert result.response == GuardrailsEngine._SAFE_FALLBACK


@pytest.mark.skipif(not _nemo_available, reason="NeMo Guardrails not available")
class TestCheckOutputChunk:
    @pytest.fixture
    def engine(self, mock_settings):
        with (
            patch("nemoguardrails.RailsConfig.from_path"),
            patch("nemoguardrails.LLMRails") as mock_rails_cls,
        ):
            mock_rails = AsyncMock()
            mock_rails_cls.return_value = mock_rails
            engine = GuardrailsEngine(mock_settings)
            engine._rails = mock_rails
            return engine

    async def test_passes_clean_chunk(self, engine, mock_user):
        chunk = "Your subscription is active."
        engine._rails.generate_async.return_value = chunk
        result = await engine.check_output_chunk(chunk, mock_user)
        assert result.blocked is False
        assert result.response == chunk

    async def test_blocks_chunk_with_email_pii(self, engine, mock_user):
        chunk = "Contact alice@example.com for help."
        result = await engine.check_output_chunk(chunk, mock_user)
        assert result.blocked is True
        engine._rails.generate_async.assert_not_called()

    async def test_blocks_chunk_with_api_key(self, engine, mock_user):
        chunk = "Your key is sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234"
        result = await engine.check_output_chunk(chunk, mock_user)
        assert result.blocked is True
        engine._rails.generate_async.assert_not_called()

    async def test_fails_closed_on_nemo_error(self, engine, mock_user):
        chunk = "Some safe text."
        engine._rails.generate_async.side_effect = RuntimeError("NeMo error")
        result = await engine.check_output_chunk(chunk, mock_user)
        assert result.blocked is True
        assert result.response == GuardrailsEngine._SAFE_FALLBACK

    async def test_blocks_pii_in_overlap_context(self, engine, mock_user):
        """I6: PII spanning overlap context + chunk boundary is caught."""
        chunk = "for help."
        overlap = "Contact alice@example.com "
        result = await engine.check_output_chunk(chunk, mock_user, overlap_context=overlap)
        assert result.blocked is True
        engine._rails.generate_async.assert_not_called()

    async def test_includes_overlap_context_in_evaluation(self, engine, mock_user):
        chunk = "and renews on 2026-05-01."
        overlap = "Your subscription is active "
        expected_eval = overlap + chunk
        engine._rails.generate_async.return_value = expected_eval
        result = await engine.check_output_chunk(chunk, mock_user, overlap_context=overlap)
        assert result.blocked is False
        assert result.response == chunk
        call_messages = engine._rails.generate_async.call_args[1]["messages"]
        assert call_messages[1]["content"] == expected_eval
