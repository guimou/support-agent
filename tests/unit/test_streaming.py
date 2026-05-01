"""Unit tests for TokenBuffer."""

from proxy.streaming import _CHARS_PER_TOKEN, ChunkWithContext, TokenBuffer


class TestTokenBuffer:
    def test_add_returns_none_below_threshold(self):
        buf = TokenBuffer(chunk_size=200)
        result = buf.add("short text")
        assert result is None

    def test_add_returns_chunk_at_threshold(self):
        buf = TokenBuffer(chunk_size=10)  # 10 * 4 = 40 chars threshold
        result = buf.add("x" * 40)
        assert result is not None
        assert isinstance(result, ChunkWithContext)
        assert result.text == "x" * 40

    def test_first_chunk_has_empty_overlap(self):
        buf = TokenBuffer(chunk_size=10)
        result = buf.add("a" * 40)
        assert result is not None
        assert result.overlap_context == ""

    def test_second_chunk_has_overlap_from_first(self):
        buf = TokenBuffer(chunk_size=10, overlap=5)
        first = buf.add("A" * 40)
        assert first is not None
        second = buf.add("B" * 40)
        assert second is not None
        assert second.overlap_context == "A" * 20

    def test_overlap_context_is_from_previous_chunk(self):
        buf = TokenBuffer(chunk_size=10, overlap=5)
        first = buf.add("1" * 40)
        assert first is not None
        second = buf.add("2" * 40)
        assert second is not None
        third = buf.add("3" * 40)
        assert third is not None
        assert third.overlap_context == "2" * 20

    def test_flush_remaining_returns_remaining(self):
        buf = TokenBuffer(chunk_size=200)
        buf.add("some partial text")
        result = buf.flush_remaining()
        assert result is not None
        assert result.text == "some partial text"

    def test_flush_remaining_returns_none_when_empty(self):
        buf = TokenBuffer()
        result = buf.flush_remaining()
        assert result is None

    def test_multiple_adds_accumulate(self):
        buf = TokenBuffer(chunk_size=10)
        assert buf.add("12345") is None
        assert buf.add("12345") is None
        assert buf.add("12345") is None
        result = buf.add("1" * 25)
        assert result is not None
        assert result.text == "12345" * 3 + "1" * 25

    def test_custom_chunk_size(self):
        buf = TokenBuffer(chunk_size=5)
        result = buf.add("x" * 20)
        assert result is not None

    def test_custom_overlap(self):
        buf = TokenBuffer(chunk_size=10, overlap=2)
        first = buf.add("A" * 40)
        assert first is not None
        second = buf.add("B" * 40)
        assert second is not None
        assert second.overlap_context == "A" * 8

    def test_overlap_context_length(self):
        buf = TokenBuffer(chunk_size=10, overlap=5)
        first = buf.add("x" * 40)
        assert first is not None
        second = buf.add("y" * 40)
        assert second is not None
        assert len(second.overlap_context) == 5 * _CHARS_PER_TOKEN

    def test_overlap_when_chunk_shorter_than_overlap(self):
        buf = TokenBuffer(chunk_size=5, overlap=100)
        first = buf.add("x" * 20)
        assert first is not None
        second = buf.add("y" * 20)
        assert second is not None
        assert second.overlap_context == "x" * 20

    def test_flush_remaining_after_full_chunk(self):
        buf = TokenBuffer(chunk_size=10, overlap=5)
        buf.add("A" * 40)
        buf.add("remaining")
        result = buf.flush_remaining()
        assert result is not None
        assert result.text == "remaining"
        assert result.overlap_context == "A" * 20
