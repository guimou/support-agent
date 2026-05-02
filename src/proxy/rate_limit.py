"""Per-user rate limiting with sliding window."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """In-memory per-key sliding window rate limiter.

    Thread-safe within a single asyncio event loop (single-worker constraint).
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key.

        Prunes expired timestamps and checks count against limit.
        Returns True if allowed (and records the request), False if rate-limited.
        """
        now = time.monotonic()
        window_start = now - self._window_seconds
        timestamps = self._requests[key]

        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self._max_requests:
            return False

        timestamps.append(now)
        return True

    def remaining(self, key: str) -> int:
        """Return the number of remaining requests in the current window."""
        now = time.monotonic()
        window_start = now - self._window_seconds
        timestamps = self._requests[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        return max(0, self._max_requests - len(timestamps))

    def reset_time(self, key: str) -> float:
        """Return seconds until the oldest request in the window expires."""
        timestamps = self._requests[key]
        if not timestamps:
            return 0.0
        return max(0.0, self._window_seconds - (time.monotonic() - timestamps[0]))
