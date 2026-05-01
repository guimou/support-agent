"""SSE streaming helpers: token buffering and chunked evaluation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4


@dataclass
class ChunkWithContext:
    """A chunk of text paired with its overlap context from the previous chunk."""

    text: str
    overlap_context: str


@dataclass
class TokenBuffer:
    """Accumulates streaming text and yields chunks for guardrail evaluation.

    Chunks are approximately `chunk_size` tokens (measured by character count)
    with `overlap` tokens of trailing context carried to the next chunk.
    """

    chunk_size: int = 200
    overlap: int = 50
    _buffer: str = field(default="", repr=False)
    _overlap_context: str = field(default="", repr=False)
    _chunk_count: int = field(default=0, repr=False)

    def add(self, text: str) -> ChunkWithContext | None:
        """Add text to the buffer. Returns a chunk if buffer is full enough."""
        self._buffer += text
        threshold = self.chunk_size * _CHARS_PER_TOKEN
        if len(self._buffer) >= threshold:
            return self._flush()
        return None

    def flush_remaining(self) -> ChunkWithContext | None:
        """Flush any remaining text in the buffer as a final chunk."""
        if self._buffer:
            return self._flush()
        return None

    def _flush(self) -> ChunkWithContext:
        """Extract a chunk from the buffer, preserving overlap context."""
        chunk = self._buffer
        self._buffer = ""
        self._chunk_count += 1
        prev_overlap = self._overlap_context
        overlap_chars = self.overlap * _CHARS_PER_TOKEN
        self._overlap_context = chunk[-overlap_chars:] if len(chunk) > overlap_chars else chunk
        return ChunkWithContext(text=chunk, overlap_context=prev_overlap)
