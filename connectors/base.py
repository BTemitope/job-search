from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from models import JobRef, NormalizedJob, RawPosting, SearchQuery


class BaseConnector(ABC):
    """Shape every job-source connector implements.

    Kept deliberately small: discover() is a cheap listing call, fetch_detail()
    is the (rate-limited) per-posting fetch, normalize() is a pure function
    with no network access so it stays unit-testable, and health_check() lets
    breakage be detected proactively instead of silently returning zero results.
    """

    source_name: str

    @abstractmethod
    def discover(self, query: SearchQuery) -> Iterable[JobRef]:
        ...

    @abstractmethod
    def fetch_detail(self, job_ref: JobRef) -> RawPosting:
        ...

    @abstractmethod
    def normalize(self, raw: RawPosting) -> NormalizedJob:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...
