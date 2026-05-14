from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ApplicationStatus(str, Enum):
    PENDING     = "pending"       # built resume, not yet submitted
    SUBMITTED   = "submitted"
    ACKNOWLEDGED = "acknowledged"
    INTERVIEWING = "interviewing"
    OFFERED     = "offered"
    REJECTED    = "rejected"
    WITHDRAWN   = "withdrawn"


class Application(BaseModel):
    id: int | None = None
    job_id: str
    resume_path: str = ""
    cover_letter: str = ""
    form_data: dict = Field(default_factory=dict)   # field_name → filled value
    status: ApplicationStatus = ApplicationStatus.PENDING
    submitted_at: datetime | None = None
    outcome: str = ""
    notes: str = ""
