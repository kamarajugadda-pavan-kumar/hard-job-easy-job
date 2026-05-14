from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class JobStatus(str, Enum):
    DISCOVERED   = "discovered"
    MATCHED      = "matched"
    SKIPPED      = "skipped"
    RESUME_READY = "resume_ready"
    APPLIED      = "applied"
    REJECTED     = "rejected"
    INTERVIEW    = "interview"


class JobPosting(BaseModel):
    id: str = Field(default="")                  # sha256(url or company+title+desc[:100])
    url: str = ""
    company: str
    title: str
    location: str = ""
    description: str = ""
    required_skills: list[str] = []
    nice_to_have: list[str] = []
    job_type: str | None = None                  # full-time, contract, etc.
    salary_range: str | None = None
    posted_date: str | None = None
    match_score: float = 0.0
    match_reasoning: str = ""
    match_gaps: list[str] = []
    match_strengths: list[str] = []
    status: JobStatus = JobStatus.DISCOVERED
    scraped_at: datetime = Field(default_factory=datetime.now)
    applied_at: datetime | None = None
    resume_path: str | None = None
    notes: str = ""
    content_hash: str = Field(default="")        # for deduplication

    @model_validator(mode="after")
    def compute_derived_fields(self) -> JobPosting:
        if not self.content_hash:
            raw = f"{self.company}{self.title}{self.description[:500]}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()
        if not self.id:
            if self.url:
                self.id = hashlib.sha256(self.url.encode()).hexdigest()[:16]
            else:
                self.id = self.content_hash[:16]
        return self
