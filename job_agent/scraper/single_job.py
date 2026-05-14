"""
Extracts a structured JobPosting from a single job detail-page URL.

Uses Playwright to load the page, then an LLM to extract structured fields
from the rendered text. Simpler than the ScraperFactory because we only
need to handle one page with no pagination.
"""
from __future__ import annotations

from job_agent.models.job import JobPosting


async def extract_single_job(url: str) -> JobPosting | None:
    """
    Load a single job posting URL and return a structured JobPosting.
    Returns None if extraction fails.
    """
    page_text = await _fetch_page_text(url)
    if not page_text:
        return None
    return await _llm_extract(url, page_text)


async def _fetch_page_text(url: str) -> str:
    """Use Playwright to load the URL and return visible page text."""
    # TODO: implement with playwright.async_api
    raise NotImplementedError


async def _llm_extract(url: str, page_text: str) -> JobPosting:
    """Send page text to LLM and parse into a JobPosting."""
    # TODO: build prompt, call LLM, parse JSON into JobPosting
    raise NotImplementedError


EXTRACT_PROMPT = """
Extract a structured job posting from this web page text.

URL: {url}

Page text:
{page_text}

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
