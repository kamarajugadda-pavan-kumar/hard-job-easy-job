"""
Loads and caches the user's profile from data/profile/.

Sources (merged in order):
  1. resume.pdf       — extracted via pdfplumber
  2. skills.yaml      — explicit skills list
  3. projects.md      — freeform project descriptions

The LLM normalises everything into a UserProfile model.
Result is cached at data/profile/profile.json.
Regenerate by deleting the cache file or passing force=True.
"""
from __future__ import annotations

import json
from pathlib import Path

from job_agent.models.profile import UserProfile

CACHE_PATH = Path("data/profile/profile.json")


def load_profile(force: bool = False) -> UserProfile:
    """
    Return the cached UserProfile, or extract it fresh if the cache
    doesn't exist or force=True.
    """
    if not force and CACHE_PATH.exists():
        return UserProfile(**json.loads(CACHE_PATH.read_text()))

    raw = _extract_raw()
    profile = _llm_structure(raw)
    CACHE_PATH.write_text(profile.model_dump_json(indent=2))
    return profile


def _extract_raw() -> str:
    """Concatenate all profile source files into one raw string."""
    parts: list[str] = []

    pdf_path = Path("data/profile/resume.pdf")
    if pdf_path.exists():
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            parts.append("\n".join(p.extract_text() or "" for p in pdf.pages))

    skills_path = Path("data/profile/skills.yaml")
    if skills_path.exists():
        parts.append(f"SKILLS:\n{skills_path.read_text()}")

    projects_path = Path("data/profile/projects.md")
    if projects_path.exists():
        parts.append(f"PROJECTS:\n{projects_path.read_text()}")

    return "\n\n---\n\n".join(parts)


def _llm_structure(raw: str) -> UserProfile:
    """Send raw text to LLM, parse structured UserProfile from JSON response."""
    # TODO: call LLM with STRUCTURE_PROMPT, parse into UserProfile
    raise NotImplementedError


STRUCTURE_PROMPT = """
Extract a structured profile from the following resume/CV text.

{raw_text}

Return JSON matching this schema exactly:
{{
  "name": str,
  "email": str,
  "phone": str,
  "location": str,
  "linkedin": str | null,
  "github": str | null,
  "summary": str,
  "skills": [str],
  "experience": [
    {{
      "title": str, "company": str, "start_date": str,
      "end_date": str | null, "years": float,
      "bullets": [str], "tech_stack": [str]
    }}
  ],
  "education": [{{"degree": str, "institution": str, "year": str, "field": str}}],
  "projects": [{{"name": str, "description": str, "tech_stack": [str], "url": str | null}}],
  "certifications": [str],
  "languages": [str]
}}

Return only valid JSON. No explanation.
"""
