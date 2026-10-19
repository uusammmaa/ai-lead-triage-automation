"""API key auth and a per-key sliding-window rate limiter."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from .config import Settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class RateLimiter:
    """In-memory sliding window. Fine for one instance; swap for Redis when scaling out."""

    def __init__(self, limit_per_minute: int, window_seconds: float = 60.0):
        self.limit = limit_per_minute
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = int(self.window - (now - hits[0])) + 1
                return False, 0, retry_after
            hits.append(now)
            return True, self.limit - len(hits), 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def key_fingerprint(api_key: str) -> str:
    """Short hash used as the rate-limit bucket and in logs, so raw keys never get logged."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def require_api_key(request: Request, api_key: str | None = Depends(api_key_header)) -> str:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
    if not api_key or not any(hmac.compare_digest(api_key.encode(), k.encode()) for k in settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key_fingerprint(api_key)


def rate_limit(request: Request, key_id: str = Depends(require_api_key)) -> str:
    limiter: RateLimiter = request.app.state.rate_limiter
    allowed, remaining, retry_after = limiter.check(key_id)
    request.state.rate_remaining = remaining
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    return key_id
