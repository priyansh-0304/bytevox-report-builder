"""A tiny in-memory sliding-window rate limiter (per process; fine for one server, not for several)."""
import time
from collections import defaultdict, deque


class SlidingWindow:
    """Allows `limit` events per `seconds` for each key (for example, an IP address)."""

    def __init__(self, limit: int, seconds: float):
        self.limit = limit
        self.seconds = seconds
        self._hits = defaultdict(deque)

    def _recent(self, key: str) -> deque:
        q = self._hits[key]
        cutoff = time.monotonic() - self.seconds
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        """True if this key has already used up its allowance. Does not count as a hit."""
        q = self._recent(key)
        if not q:
            self._hits.pop(key, None)   # do not keep an entry for every address we have ever seen
        return len(q) >= self.limit

    def record(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def allow(self, key: str) -> bool:
        """Check and count in one step."""
        if self.blocked(key):
            return False
        self.record(key)
        return True