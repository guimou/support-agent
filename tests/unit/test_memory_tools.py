"""Tests for PII-audited memory write wrappers."""

from unittest.mock import MagicMock, patch

from tools.memory import archival_memory_insert, core_memory_append, core_memory_replace


class TestMemoryToolPiiBlocking:
    def test_core_memory_append_blocks_email(self):
        result = core_memory_append("persona", "User email is alice@example.com")
        assert result.startswith("BLOCKED")
        assert "PII" in result

    def test_core_memory_append_blocks_uuid(self):
        result = core_memory_append("persona", "Session 550e8400-e29b-41d4-a716-446655440000")
        assert result.startswith("BLOCKED")

    def test_core_memory_append_allows_clean_content(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp):
            result = core_memory_append("persona", "User prefers concise answers")
        assert "Successfully" in result
        assert "BLOCKED" not in result

    def test_core_memory_replace_blocks_pii_in_new_content(self):
        result = core_memory_replace(
            "persona",
            "old content",
            "Contact us at support@company.com",
        )
        assert result.startswith("BLOCKED")
        assert "PII" in result

    def test_core_memory_replace_allows_pii_in_old_content(self):
        """PII in old_content (what to remove) should not be blocked."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp):
            result = core_memory_replace(
                "persona",
                "old email was alice@example.com",
                "email has been removed",
            )
        assert "Successfully" in result
        assert "BLOCKED" not in result

    def test_archival_memory_insert_blocks_phone(self):
        result = archival_memory_insert("Call the user at (555) 123-4567 for follow-up")
        assert result.startswith("BLOCKED")

    def test_archival_memory_insert_allows_clean_content(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp):
            result = archival_memory_insert("User prefers technical explanations")
        assert "Successfully" in result
        assert "BLOCKED" not in result
