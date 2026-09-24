from __future__ import annotations

from sqlalchemy import text

from db import JobRecord, get_session
from models import NormalizedJob


def _and_block(term: str) -> str:
    """One term as an FTS5 AND-of-quoted-words block, e.g. "mental health
    nurse" -> ("mental" AND "health" AND "nurse"). Quoting each word
    sidesteps FTS5's special-character syntax (so stray punctuation in a
    search term can't break the query).
    """
    words = [w for w in term.split() if w]
    quoted = [f'"{w}"' for w in words]
    return "(" + " AND ".join(quoted) + ")" if quoted else '("")'


def _fts_match_expr(terms: list[str]) -> str:
    """OR together each term's AND-block, so a job matches if it satisfies
    ANY one of the (possibly several, LLM-expanded) related terms — not just
    the single literal keyword typed in.
    """
    blocks = [_and_block(t) for t in terms if t.strip()]
    return " OR ".join(blocks) if blocks else '("")'


def search_jobs(
    keyword: str,
    location: str = "",
    source: str = "",
    active_only: bool = True,
    limit: int = 50,
    min_salary: float | None = None,
    contract_type: str = "",
    smart: bool = True,
) -> list[NormalizedJob]:
    with get_session() as session:
        if keyword.strip():
            terms = [keyword]
            if smart:
                # Best-effort — expand_keyword() never raises; on any LLM
                # issue it just returns [], leaving this literal-keyword-only.
                from query_expansion import expand_keyword

                terms += expand_keyword(keyword)

            match_expr = _fts_match_expr(terms)
            rows = session.execute(
                text(
                    "SELECT job_id FROM jobs_fts WHERE jobs_fts MATCH :match "
                    "ORDER BY rank LIMIT :limit"
                ),
                {"match": match_expr, "limit": limit * 3},  # over-fetch, filtered below
            ).fetchall()
            job_ids = [r[0] for r in rows]
            if not job_ids:
                return []
            query = session.query(JobRecord).filter(JobRecord.id.in_(job_ids))
        else:
            query = session.query(JobRecord)

        if location.strip():
            query = query.filter(JobRecord.location.ilike(f"%{location}%"))
        if source.strip():
            query = query.filter(JobRecord.source == source)
        if contract_type.strip():
            query = query.filter(JobRecord.contract_type.ilike(f"%{contract_type}%"))
        if min_salary is not None:
            # Excludes jobs with unknown salary (NULL) — an unknown figure
            # isn't evidence it meets the floor, so it shouldn't match.
            query = query.filter(JobRecord.salary_min_numeric.isnot(None)).filter(
                JobRecord.salary_min_numeric >= min_salary
            )
        if active_only:
            query = query.filter(JobRecord.is_active.is_(True))

        records = query.limit(limit).all()
        return [r.to_normalized() for r in records]
