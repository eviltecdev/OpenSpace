"""Rate limiting for MCP server tools."""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger("openspace.mcp_server_limiter")


class RateLimiter:
    """Token bucket rate limiter with idempotent release semantics."""

    def __init__(self, max_concurrent: int = 3, max_per_minute: int = 10):
        self.max_concurrent = max_concurrent
        self.max_per_minute = max_per_minute
        self.active_tasks = 0
        self.request_times = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Acquire a rate limit token.

        Returns True if token acquired, False if rate limit exceeded.
        Caller MUST only call release() if acquire() returned True.
        """
        async with self._lock:
            if self.active_tasks >= self.max_concurrent:
                logger.warning(
                    f"Rate limit: max concurrent ({self.max_concurrent}) exceeded. "
                    f"Current tasks: {self.active_tasks}"
                )
                return False

            now = time.time()
            minute_ago = now - 60
            self.request_times = [t for t in self.request_times if t > minute_ago]

            if len(self.request_times) >= self.max_per_minute:
                logger.warning(
                    f"Rate limit: max per minute ({self.max_per_minute}) exceeded. "
                    f"Current requests in last minute: {len(self.request_times)}"
                )
                return False

            self.active_tasks += 1
            self.request_times.append(now)
            return True

    async def release(self):
        """Release a rate limit token. Safe to call multiple times (idempotent)."""
        async with self._lock:
            if self.active_tasks > 0:
                self.active_tasks -= 1
            else:
                logger.warning(
                    f"Rate limit release called with no active tasks. "
                    f"This indicates acquire/release mismatch."
                )


# Global limiters
execute_task_limiter = RateLimiter(max_concurrent=3, max_per_minute=10)
search_skills_limiter = RateLimiter(max_concurrent=5, max_per_minute=20)
