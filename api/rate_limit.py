"""
hormuz_watch/api/rate_limit.py

Tiered rate limiting: each account tier gets a different requests-per-
window budget, enforced with an in-memory sliding window keyed by user
id. This is process-local — fine for a single-instance deployment (this
project's current stage); a multi-worker/multi-instance deployment would
need a shared store (Redis) instead, since each process would otherwise
track its own independent window.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

TIER_LIMITS = {
    "free": (30, 60),   # 30 requests / 60s
    "pro":  (150, 60),  # 150 requests / 60s
}
DEFAULT_LIMIT = (10, 60)

_lock = threading.Lock()
_requests = defaultdict(deque)


def check_rate_limit(key: str, tier: str):
    limit, window = TIER_LIMITS.get(tier, DEFAULT_LIMIT)
    now = time.time()

    with _lock:
        q = _requests[key]
        while q and now - q[0] > window:
            q.popleft()

        if len(q) >= limit:
            retry_after = window - (now - q[0])
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({limit} requests / {window}s for '{tier}' tier).",
                headers={"Retry-After": str(max(1, int(retry_after) + 1))},
            )

        q.append(now)
