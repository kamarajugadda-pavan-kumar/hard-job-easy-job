"""
Handles URL mode: classifies the URL as a listing page or a single job
posting, then routes to the appropriate handler.
"""
from __future__ import annotations

from job_agent.models.job import JobPosting
from job_agent.scraper.ats_detector import detect
from job_agent.scraper.deduplicator import deduplicate_and_save


async def handle_url(url: str, force_single: bool = False) -> list[JobPosting]:
    """
    Entry point for URL mode.
    Returns list of new jobs saved to the DB.
    """
    if force_single:
        jobs = await _scrape_single(url)
    else:
        jobs = await _scrape_listing(url)

    return deduplicate_and_save(jobs)


async def _scrape_listing(url: str) -> list[JobPosting]:
    """
    Route a listing URL to the right scraper:
      1. Known ATS (Workday, Greenhouse, …) → fast pre-built httpx scraper
      2. Everything else → ScraperFactory (LLM script generation + human assist)
    """
    ats = detect(url)
    if ats:
        from job_agent.scraper.script_runner import run_ats_scraper
        return await run_ats_scraper(ats, url)

    from job_agent.scraper.script_runner import ScraperFactory
    return await ScraperFactory(url).run()


async def _scrape_single(url: str) -> list[JobPosting]:
    """Extract one job posting from a detail-page URL."""
    from job_agent.scraper.single_job import extract_single_job
    job = await extract_single_job(url)
    return [job] if job else []
