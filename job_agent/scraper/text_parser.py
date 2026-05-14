"""
Parses a raw job description string (pasted text or file contents)
into a structured JobPosting using an LLM.

No scraping needed — the user has already obtained the text.
"""
from __future__ import annotations

from job_agent.models.job import JobPosting


async def parse_raw_text(text: str) -> JobPosting:
    """
    Call the LLM to extract structured fields from raw job description text.
    Returns a JobPosting (url will be empty, id derived from content_hash).
    """
    # TODO: call LLM with PARSE_PROMPT, parse JSON response into JobPosting
    raise NotImplementedError


PARSE_PROMPT = """
Extract a structured job posting from this raw text.

Text:
{text}

Return JSON with these fields (use null for anything not mentioned):
{{
  "title": str,
  "company": str,
  "location": str,
  "job_type": str,
  "description": str,
  "required_skills": [str],
  "nice_to_have": [str],
  "salary_range": str,
  "posted_date": str
}}

Return only valid JSON. No explanation.
"""
