from __future__ import annotations

import re

_SALARY_RE = re.compile(r"£\s?([\d,]+(?:\.\d+)?)\s*(k)?", re.IGNORECASE)


def parse_salary_min(text: str) -> float | None:
    """Best-effort extraction of a minimum ANNUAL salary figure from free
    text (e.g. NHS Jobs' "£39,959 to £48,117 a year"). Returns None on
    anything unparseable (e.g. "Depending on experience") — callers must
    treat a None as "unknown", not "zero" — and also on an hourly/daily rate
    (e.g. "£19.97 an hour"), since a small hourly number would otherwise
    silently pass an annual "min_salary" filter as if it were an annual
    figure the filter never intended to compare against.
    """
    if not text:
        return None

    if re.search(r"\b(an?\s+)?hour|hourly|per\s+hour|daily|per\s+day\b", text, re.IGNORECASE):
        return None

    matches = _SALARY_RE.findall(text)
    if not matches:
        return None

    values = []
    for number, k_suffix in matches:
        try:
            value = float(number.replace(",", ""))
        except ValueError:
            continue
        if k_suffix:
            value *= 1000
        values.append(value)

    return min(values) if values else None
