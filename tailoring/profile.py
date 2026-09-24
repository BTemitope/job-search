from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL_KEYS = ("contact", "professional_summary", "work_history")


class ProfileError(ValueError):
    pass


@dataclass
class WorkHistoryEntry:
    employer: str
    title: str
    start_date: str
    end_date: str
    location: str = ""
    achievements: list[str] = field(default_factory=list)
    values_evidence: list[dict] = field(default_factory=list)


@dataclass
class Profile:
    contact: dict
    professional_summary: str
    work_history: list[WorkHistoryEntry]
    education: list[dict] = field(default_factory=list)
    professional_registrations: list[dict] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    training_cpd: list[str] = field(default_factory=list)
    referees: list[dict] = field(default_factory=list)

    def to_prompt_dict(self) -> dict:
        """Structured representation sent to the LLM — plain dicts, no
        Python-specific types, so it serializes cleanly into the prompt.
        """
        return {
            "contact": self.contact,
            "professional_summary": self.professional_summary,
            "work_history": [
                {
                    "employer": w.employer,
                    "title": w.title,
                    "start_date": w.start_date,
                    "end_date": w.end_date,
                    "location": w.location,
                    "achievements": w.achievements,
                    "values_evidence": w.values_evidence,
                }
                for w in self.work_history
            ],
            "education": self.education,
            "professional_registrations": self.professional_registrations,
            "skills": self.skills,
            "training_cpd": self.training_cpd,
        }


def load_profile(path: Path | str) -> Profile:
    path = Path(path)
    if not path.exists():
        raise ProfileError(
            f"Profile not found at {path}. Copy profile.example.yaml to {path} and fill in your real details."
        )

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if not data.get(k)]
    if missing:
        raise ProfileError(f"Profile at {path} is missing required field(s): {', '.join(missing)}")

    work_history = [
        WorkHistoryEntry(
            employer=w.get("employer", ""),
            title=w.get("title", ""),
            start_date=w.get("start_date", ""),
            end_date=w.get("end_date", ""),
            location=w.get("location", ""),
            achievements=w.get("achievements", []) or [],
            values_evidence=w.get("values_evidence", []) or [],
        )
        for w in data["work_history"]
    ]

    return Profile(
        contact=data["contact"],
        professional_summary=data["professional_summary"],
        work_history=work_history,
        education=data.get("education", []) or [],
        professional_registrations=data.get("professional_registrations", []) or [],
        skills=data.get("skills", []) or [],
        training_cpd=data.get("training_cpd", []) or [],
        referees=data.get("referees", []) or [],
    )
