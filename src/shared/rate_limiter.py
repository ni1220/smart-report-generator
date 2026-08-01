"""
Bedrock Rate Limiter.

Competition Requirement: Amazon Bedrock requests must be limited to
less than 1 request per second (RPS/TPS).

This module provides a thread-safe rate limiter that ensures all
Bedrock API calls comply with this constraint.
"""

import logging
import time
import threading

logger = logging.getLogger(__name__)


class BedrockRateLimiter:
    """
    Thread-safe rate limiter for Amazon Bedrock API calls.

    Enforces a minimum interval between consecutive calls to ensure
    compliance with competition rules (< 1 RPS).

    Usage:
        rate_limiter = BedrockRateLimiter()
        rate_limiter.wait()  # Call before each Bedrock request
        response = bedrock_client.converse(...)
    """

    def __init__(self, min_interval: float = 1.1):
        """
        Initialize rate limiter.

        Args:
            min_interval: Minimum seconds between calls.
                          Default 1.1s provides 0.1s safety margin.
        """
        self._lock = threading.Lock()
        self._last_call_time: float = 0.0
        self._min_interval = min_interval
        self._call_count = 0

    def wait(self) -> float:
        """
        Wait until it's safe to make the next Bedrock call.

        Returns:
            Actual wait time in seconds (0 if no wait needed).
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time
            wait_time = 0.0

            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                logger.debug(
                    f"Rate limiter: waiting {wait_time:.2f}s before next Bedrock call"
                )
                time.sleep(wait_time)

            self._last_call_time = time.time()
            self._call_count += 1

            return wait_time

    @property
    def call_count(self) -> int:
        """Total number of calls that passed through the limiter."""
        return self._call_count

    def reset(self):
        """Reset the limiter state (useful for testing)."""
        with self._lock:
            self._last_call_time = 0.0
            self._call_count = 0


# Global singleton instance
_global_limiter: BedrockRateLimiter | None = None
_global_lock = threading.Lock()


def get_rate_limiter() -> BedrockRateLimiter:
    """Get the global BedrockRateLimiter singleton."""
    global _global_limiter
    if _global_limiter is None:
        with _global_lock:
            if _global_limiter is None:
                _global_limiter = BedrockRateLimiter(min_interval=1.1)
    return _global_limiter
