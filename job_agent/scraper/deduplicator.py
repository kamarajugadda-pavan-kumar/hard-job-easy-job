"""
Checks incoming JobPostings against the DB and saves only truly new ones.

Deduplication priority:
  1. URL exact match          → skip (strongest signal)
  2. content_hash match       → skip (same JD reposted without a URL)
  3. company + title match    → update existing record if no URL yet
  4. Truly new                → insert
"""
from __future__ import annotations

from job_agent.models.job import JobPosting
from job_agent.storage.db import (
    content_hash_exists,
    insert_job,
    url_exists,
)


def deduplicate_and_save(jobs: list[JobPosting]) -> list[JobPosting]:
    """
    Filter out duplicates and persist the remainder.
    Returns only the jobs that were newly inserted.
    """
    new_jobs: list[JobPosting] = []

    for job in jobs:
        if job.url and url_exists(job.url):
            continue
        if content_hash_exists(job.content_hash):
            continue
        insert_job(job)
        new_jobs.append(job)

    return new_jobs
