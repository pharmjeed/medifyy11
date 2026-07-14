"""حصر المعدل — DOC-05 §١: 429 مع Retry-After، حدود أشد لنقاط AI."""
from __future__ import annotations

import threading
import time

from .config import get_settings
from .errors import MedifyError

AI_PATH_MARKERS = ("/ai-chat", "/reverse-build", "/templates/preview", "/dictate")


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.time()
        with self._lock:
            hits = [h for h in self._hits.get(key, []) if h > now - window]
            if len(hits) >= limit:
                retry_after = max(1, int(hits[0] + window - now))
                raise MedifyError("MDF-4291", headers={"Retry-After": str(retry_after)})
            hits.append(now)
            self._hits[key] = hits


limiter = SlidingWindowLimiter()


def enforce_rate_limit(identity: str, path: str) -> None:
    s = get_settings()
    if any(marker in path for marker in AI_PATH_MARKERS):
        limiter.check(f"ai:{identity}", s.rate_limit_ai)
    limiter.check(f"all:{identity}", s.rate_limit_default)
