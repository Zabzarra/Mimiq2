"""Per-user flood limit for Telegram updates."""

import time

import collections

_USER_RATE: dict[int, collections.deque] = collections.defaultdict(collections.deque)

_RATE_MAX = ...

_RATE_WINDOW = ...

def check_user_rate(user_id: int) -> bool:
    """Return True if the user is within their rate limit, False if exceeded."""
    now = time.monotonic()
    dq = _USER_RATE[user_id]
    while dq and dq[0] < now - _RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _RATE_MAX:
        return False
    dq.append(now)
    return True

def cleanup_stale_rate_entries() -> int:
    """Remove entries for users inactive for longer than the rate window."""
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    stale = [uid for uid, dq in _USER_RATE.items() if not dq or dq[-1] < cutoff]
    for uid in stale:
        del _USER_RATE[uid]
    return len(stale)
