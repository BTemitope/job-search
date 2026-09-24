from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import config

_last_request_at: dict[str, float] = {}

_COUNTERS_PATH = config.BASE_DIR / "data" / "rate_limit_counters.json"


def _load_counters() -> dict:
    if not _COUNTERS_PATH.exists():
        return {}
    try:
        return json.loads(_COUNTERS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_counters(counters: dict) -> None:
    _COUNTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COUNTERS_PATH.write_text(json.dumps(counters))


def check_daily_cap(source: str, cap: int) -> bool:
    """Reserve one request against a source's daily quota (e.g. Adzuna's
    250/day free-tier limit). Returns False — without reserving anything —
    once the cap for today (UTC) is reached, so callers can stop early
    instead of hammering an API into throttling/suspending the key. Resets
    automatically at UTC midnight.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    counters = _load_counters()
    entry = counters.get(source, {})

    if entry.get("date") != today:
        entry = {"date": today, "count": 0}

    if entry["count"] >= cap:
        counters[source] = entry
        _save_counters(counters)
        return False

    entry["count"] += 1
    counters[source] = entry
    _save_counters(counters)
    return True


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
