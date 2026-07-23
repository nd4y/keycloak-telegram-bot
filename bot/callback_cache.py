from __future__ import annotations

import itertools
import time
from typing import Any


class CallbackCache:
    """Maps short tokens to arbitrary values (group ids, (group_id, user_id) pairs)
    so Telegram inline keyboards stay under the 64-byte callback_data limit
    without cramming raw Keycloak UUIDs into it."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._counter = itertools.count()
        self._ttl_seconds = ttl_seconds

    def put(self, value: Any) -> str:
        self._evict_expired()
        token = str(next(self._counter))
        self._data[token] = (time.time(), value)
        return token

    def get(self, token: str) -> Any | None:
        entry = self._data.get(token)
        if entry is None:
            return None
        return entry[1]

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [key for key, (ts, _) in self._data.items() if now - ts > self._ttl_seconds]
        for key in expired:
            del self._data[key]
