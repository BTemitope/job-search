from __future__ import annotations

import random
import time

_last_request_at: dict[str, float] = {}


def wait_turn(source: str, min_interval_seconds: float) -> None:
    """Block until at least min_interval_seconds (+ small jitter) have passed
    since the last request tagged with this source name. Centralized here so
    connectors don't each reimplement their own pacing.
    """
    now = time.monotonic()
    last = _last_request_at.get(source)
    if last is not None:
        elapsed = now - last
        wait_for = min_interval_seconds - elapsed
        if wait_for > 0:
            time.sleep(wait_for + random.uniform(0, 0.5))
    _last_request_at[source] = time.monotonic()
