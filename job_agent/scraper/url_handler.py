"""
Handles URL mode: classifies the URL as a listing page or a single job
posting, then routes to the appropriate handler.
"""
from __future__ import annotations

from job_agent.models.job import JobPosting
from job_agent.scraper.ats_detector import detect
from job_agent.scraper.deduplicator import deduplicate_and_save


async def handle_url(url: str) -> list[JobPosting]:
    """
    Entry point for URL mode.
    Returns list of new jobs saved to the DB.
    """
    url_type = await classify_url(url)

    if url_type == "listing":
        jobs = await _scrape_listing(url)
    else:
        jobs = await _scrape_single(url)

    return deduplicate_and_save(jobs)


async def classify_url(url: str) -> str:
    """
    Return 'listing' if the URL points to a job listings page,
    or 'single' if it points to one specific job posting.

    Heuristic: a URL ending in a numeric ID or a long slug after the
    last path segment is likely a single posting.
    Uses an LLM call as fallback for ambiguous cases.
    """
    # TODO: implement heuristic + LLM fallback
    # Simple heuristic for now: if the last path segment is numeric → single
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    last_segment = path.split("/")[-1]
    if last_segment.isdigit():
        return "single"
    return "listing"


async def _scrape_listing(url: str) -> list[JobPosting]:
    """Delegate to ScraperFactory (checks ATS, generates/reuses script)."""
    ats = detect(url)
    if ats:
        from job_agent.scraper.script_runner import run_ats_scraper
        return await run_ats_scraper(ats, url)

    from job_agent.scraper.script_runner import ScraperFactory
    factory = ScraperFactory(url)
    return await factory.run()


async def _scrape_single(url: str) -> list[JobPosting]:
    """Extract one job posting from a detail-page URL."""
    from job_agent.scraper.single_job import extract_single_job
    job = await extract_single_job(url)
    return [job] if job else []
