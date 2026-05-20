"""
Determines which scraper mode to invoke based on the raw user input.

Modes
-----
COMPANY_NAME  →  "Stripe", "OpenAI"  (resolves to a URL via registry/search)
URL           →  any http/https string
RAW_TEXT      →  multi-line job description pasted directly
"""
from __future__ import annotations

from enum import Enum

from job_agent.models.job import JobPosting


class InputMode(str, Enum):
    COMPANY_NAME = "company_name"
    URL          = "url"
    RAW_TEXT     = "raw_text"


def detect_mode(raw: str) -> InputMode:
    """Classify a user-supplied string into an InputMode."""
    stripped = raw.strip()
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return InputMode.URL
    if "\n" in stripped or len(stripped) > 120:
        return InputMode.RAW_TEXT
    return InputMode.COMPANY_NAME


async def route_input(raw: str, force_single: bool = False) -> list[JobPosting]:
    """
    Top-level entry point called by the CLI.
    Detects mode and delegates to the appropriate handler.
    Returns a list of new JobPostings saved to the DB.
    """
    mode = detect_mode(raw)

    if mode == InputMode.COMPANY_NAME:
        from job_agent.scraper.registry import resolve_company_url
        from job_agent.scraper.router import route_input
        url = await resolve_company_url(raw.strip())
        return await route_input(url, force_single=force_single)

    if mode == InputMode.URL:
        from job_agent.scraper.url_handler import handle_url
        return await handle_url(raw.strip(), force_single=force_single)

    if mode == InputMode.RAW_TEXT:
        from job_agent.scraper.text_parser import parse_raw_text
        from job_agent.scraper.deduplicator import deduplicate_and_save
        job = await parse_raw_text(raw.strip())
        return deduplicate_and_save([job])

    return []
