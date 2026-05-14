from __future__ import annotations

from pydantic import BaseModel


class Experience(BaseModel):
    title: str
    company: str
    start_date: str
    end_date: str | None = None          # None means current
    years: float = 0.0
    bullets: list[str] = []
    tech_stack: list[str] = []


class Project(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = []
    url: str | None = None


class Education(BaseModel):
    degree: str
    institution: str
    year: str | None = None
    field: str | None = None


class UserProfile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str | None = None
    github: str | None = None
    summary: str = ""
    skills: list[str] = []
    experience: list[Experience] = []
    education: list[Education] = []
    projects: list[Project] = []
    certifications: list[str] = []
    languages: list[str] = []

    def skills_text(self) -> str:
        return ", ".join(self.skills)

    def experience_text(self) -> str:
        parts = []
        for exp in self.experience:
            bullets = "\n  - ".join(exp.bullets)
            parts.append(f"{exp.title} at {exp.company}\n  - {bullets}")
        return "\n\n".join(parts)

    def projects_text(self) -> str:
        parts = []
        for p in self.projects:
            stack = ", ".join(p.tech_stack)
            parts.append(f"{p.name} ({stack}): {p.description}")
        return "\n".join(parts)
