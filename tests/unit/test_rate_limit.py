"""Unit tests for SlidingWindowRateLimiter."""

from unittest.mock import patch

from proxy.rate_limit import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    def test_allows_under_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.is_allowed("user-1") is True

    def test_blocks_at_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

    def test_prunes_expired_timestamps(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10.0)
        base_time = 1000.0
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time):
            assert limiter.is_allowed("user-1") is True
            assert limiter.is_allowed("user-1") is True
            assert limiter.is_allowed("user-1") is False
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time + 11.0):
            assert limiter.is_allowed("user-1") is True

    def test_remaining_returns_correct_count(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        limiter.is_allowed("user-1")
        limiter.is_allowed("user-1")
        assert limiter.remaining("user-1") == 3

    def test_remaining_returns_zero_at_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
        limiter.is_allowed("user-1")
        limiter.is_allowed("user-1")
        assert limiter.remaining("user-1") == 0

    def test_reset_time_returns_zero_with_no_requests(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.reset_time("user-1") == 0.0

    def test_reset_time_returns_time_until_oldest_expires(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        base_time = 1000.0
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time):
            limiter.is_allowed("user-1")
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time + 10.0):
            reset = limiter.reset_time("user-1")
            assert 49.0 <= reset <= 51.0

    def test_independent_keys(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False
        assert limiter.is_allowed("user-2") is True

    def test_max_requests_one(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

    def test_window_slides_correctly(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=5.0)
        base_time = 1000.0
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time):
            assert limiter.is_allowed("user-1") is True
            assert limiter.is_allowed("user-1") is False
        with patch("proxy.rate_limit.time.monotonic", return_value=base_time + 5.1):
            assert limiter.is_allowed("user-1") is True
