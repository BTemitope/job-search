from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import Boolean, Column, Float, String, Text, create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

import config
from models import Criterion, NormalizedJob
from salary import parse_salary_min
from visa_sponsor import classify_role_sponsorship, is_licensed_sponsor

Base = declarative_base()


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    source = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    org_name = Column(String, nullable=False)
    location = Column(String, default="")
    salary_range = Column(String, default="")
    salary_min_numeric = Column(Float, nullable=True)
    visa_sponsor_likely = Column(Boolean, nullable=True)
    role_sponsorship_status = Column(String, default="not_mentioned")
    contract_type = Column(String, default="")
    working_pattern = Column(String, default="")
    posted_date = Column(String, default="")
    closing_date = Column(String, default="")
    url = Column(String, default="")
    reference_number = Column(String, default="")
    raw_description_text = Column(Text, default="")
    person_spec_criteria_json = Column(Text, default="[]")
    raw_json_text = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    first_seen_at = Column(String, nullable=False)
    last_seen_at = Column(String, nullable=False)

    def to_normalized(self) -> NormalizedJob:
        criteria = [Criterion(**c) for c in json.loads(self.person_spec_criteria_json or "[]")]
        return NormalizedJob(
            source=self.source,
            source_id=self.source_id,
            title=self.title,
            org_name=self.org_name,
            location=self.location or "",
            salary_range=self.salary_range or "",
            salary_min_numeric=self.salary_min_numeric,
            visa_sponsor_likely=self.visa_sponsor_likely,
            role_sponsorship_status=self.role_sponsorship_status or "not_mentioned",
            contract_type=self.contract_type or "",
            working_pattern=self.working_pattern or "",
            posted_date=self.posted_date or "",
            closing_date=self.closing_date or "",
            url=self.url or "",
            reference_number=self.reference_number or "",
            raw_description_text=self.raw_description_text or "",
            person_spec_criteria=criteria,
            raw_json=json.loads(self.raw_json_text) if self.raw_json_text else None,
            is_active=bool(self.is_active),
        )


_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: polling.py now runs each source's poll in
        # its own thread (concurrently). Each thread opens its own session/
        # connection via get_session() below — never shares one across
        # threads — so this only lifts sqlite3's overly strict default
        # rejection of that, not an actual concurrency risk; SQLite still
        # serializes real writes at the file level.
        _engine = create_engine(f"sqlite:///{config.DATABASE_PATH}", future=True, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True)
    return _engine


def init_db() -> None:
    engine = _get_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5("
                "job_id UNINDEXED, title, org_name, location, raw_description_text, person_spec_text"
                ")"
            )
        )
        conn.commit()


@contextmanager
def get_session():
    if _SessionLocal is None:
        _get_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_job(session, job: NormalizedJob, seen_at: str) -> None:
    record = session.get(JobRecord, job.id)
    person_spec_json = json.dumps([c.__dict__ for c in job.person_spec_criteria])
    raw_json_text = json.dumps(job.raw_json) if job.raw_json is not None else None

    if record is None:
        record = JobRecord(id=job.id, first_seen_at=seen_at, last_seen_at=seen_at)
        session.add(record)
    else:
        record.last_seen_at = seen_at

    record.source = job.source
    record.source_id = job.source_id
    record.title = job.title
    record.org_name = job.org_name
    record.location = job.location
    record.salary_range = job.salary_range
    # Adzuna/Reed give this directly; NHS Jobs doesn't, so fall back to
    # best-effort regex extraction from the free-text salary_range.
    record.salary_min_numeric = job.salary_min_numeric if job.salary_min_numeric is not None else parse_salary_min(job.salary_range)
    # Applies uniformly across every source, since it's keyed on org_name
    # alone — no connector needs to know about this.
    record.visa_sponsor_likely = is_licensed_sponsor(job.org_name)
    record.role_sponsorship_status = classify_role_sponsorship(job.raw_description_text)
    record.contract_type = job.contract_type
    record.working_pattern = job.working_pattern
    record.posted_date = job.posted_date
    record.closing_date = job.closing_date
    record.url = job.url
    record.reference_number = job.reference_number
    record.raw_description_text = job.raw_description_text
    record.person_spec_criteria_json = person_spec_json
    record.raw_json_text = raw_json_text
    record.is_active = job.is_active

    session.flush()

    person_spec_text = " ".join(c.text for c in job.person_spec_criteria)
    session.execute(
        text("DELETE FROM jobs_fts WHERE job_id = :job_id"),
        {"job_id": job.id},
    )
    session.execute(
        text(
            "INSERT INTO jobs_fts (job_id, title, org_name, location, raw_description_text, person_spec_text) "
            "VALUES (:job_id, :title, :org_name, :location, :description, :person_spec)"
        ),
        {
            "job_id": job.id,
            "title": job.title,
            "org_name": job.org_name,
            "location": job.location,
            "description": job.raw_description_text,
            "person_spec": person_spec_text,
        },
    )
