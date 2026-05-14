"""
Executes a generated scraper script in a subprocess and returns parsed jobs.

Also contains ScraperFactory: the orchestrator that ties together
page_analyst → script_writer → script_runner with a retry loop.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from pydantic import BaseModel

from job_agent.models.job import JobPosting
from job_agent.scraper.page_analyst import PageAnalysis, analyse_page
from job_agent.scraper.script_writer import script_path, write_script


class RunResult(BaseModel):
    success: bool
    jobs: list[dict] = []
    error: str = ""
    stdout: str = ""
    stderr: str = ""


def run_script(path: Path, url: str, timeout: int = 60) -> RunResult:
    """
    Execute a scraper script in a subprocess.
    The script is expected to print a JSON array to stdout.
    """
    result = subprocess.run(
        ["python", str(path), "--url", url, "--output-json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return RunResult(success=False, error=result.stderr, stderr=result.stderr)
    try:
        jobs = json.loads(result.stdout)
        return RunResult(success=True, jobs=jobs, stdout=result.stdout)
    except json.JSONDecodeError as e:
        return RunResult(success=False, error=f"JSON decode failed: {e}", stdout=result.stdout)


async def run_ats_scraper(ats_slug: str, url: str) -> list[JobPosting]:
    """
    Run a pre-built ATS scraper (e.g. data/scrapers/greenhouse.py).
    Falls back to ScraperFactory if the pre-built script doesn't exist.
    """
    ats_path = Path(f"data/scrapers/{ats_slug}.py")
    if not ats_path.exists():
        factory = ScraperFactory(url)
        return await factory.run()

    result = run_script(ats_path, url)
    if result.success:
        return _dicts_to_postings(result.jobs)
    raise RuntimeError(f"Pre-built ATS scraper failed: {result.error}")


class ScraperFactory:
    """
    Orchestrates: analyse_page → write_script → run_script, with retry loop.
    """

    def __init__(self, url: str, max_attempts: int = 3):
        self.url          = url
        self.max_attempts = max_attempts

    async def run(self) -> list[JobPosting]:
        analysis, screenshot, html = await analyse_page(self.url)
        previous_script = ""
        previous_error  = ""

        for attempt in range(1, self.max_attempts + 1):
            print(f"[{attempt}/{self.max_attempts}] Writing scraper script...")
            path = await write_script(
                analysis, screenshot, html,
                previous_script=previous_script,
                previous_error=previous_error,
                version=attempt,
            )

            print(f"[{attempt}/{self.max_attempts}] Running scraper...")
            result = run_script(path, self.url)

            if result.success:
                print(f"  Found {len(result.jobs)} jobs.")
                return _dicts_to_postings(result.jobs)

            print(f"  Failed: {result.error.splitlines()[0]}")
            previous_script = path.read_text()
            previous_error  = result.error

        self._dump_debug(previous_script, previous_error)
        raise RuntimeError(
            f"ScraperFactory: all {self.max_attempts} attempts failed for {self.url}.\n"
            f"Debug info saved to data/scrapers/debug/"
        )

    def _dump_debug(self, last_script: str, last_error: str) -> None:
        from datetime import datetime
        debug_dir  = Path("data/scrapers/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        slug       = self.url.replace("https://", "").replace("/", "_")[:40]
        ts         = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        debug_file = debug_dir / f"{slug}_{ts}.json"
        debug_file.write_text(json.dumps({
            "url":         self.url,
            "last_script": last_script,
            "last_error":  last_error,
        }, indent=2))


def _dicts_to_postings(raw: list[dict]) -> list[JobPosting]:
    postings = []
    for d in raw:
        try:
            postings.append(JobPosting(**d))
        except Exception:
            pass
    return postings
