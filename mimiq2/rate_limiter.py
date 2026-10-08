"""Simple in-memory per-user rate limiter using a sliding window counter."""

import time

from collections import defaultdict, deque

from threading import Lock

_buckets: dict = defaultdict(deque)

_lock = Lock()

LIMITS: dict[str, tuple[int, int]] = ...

def check_rate(user_id: int, action: str) -> bool:
    """Return True if the action is within the allowed rate, False if rate-limited."""
    max_calls, window_s = LIMITS.get(action, LIMITS['default'])
    key = (user_id, action)
    now = time.monotonic()
    with _lock:
        dq = _buckets[key]
        cutoff = now - window_s
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_calls:
            return False
        dq.append(now)
        return True

def cleanup_stale_entries() -> int:
    """Remove bucket entries for users inactive longer than their action window."""
    now = time.monotonic()
    with _lock:
        stale = [key for key, dq in _buckets.items() if not dq or dq[-1] < now - LIMITS.get(key[1], LIMITS['default'])[1]]
        for key in stale:
            del _buckets[key]
    return len(stale)
