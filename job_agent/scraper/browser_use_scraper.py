"""
Browser-use powered scraper — uses an LLM agent that controls a real browser.

The agent navigates the careers page exactly like a human would:
  - reads whatever the page shows
  - clicks "Next" / "Load More" through all pagination
  - collects job listings page by page
  - returns structured JSON

Works on any site regardless of SPA framework, dynamic CSS, or bot detection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from pydantic import BaseModel

from job_agent.models.job import JobPosting


# ── output schema the agent writes into ──────────────────────────────────────

class _JobItem(BaseModel):
    title: str | None = None
    url: str | None = None
    company: str | None = None
    location: str | None = None
    job_type: str | None = None
    posted_date: str | None = None


class _JobListOutput(BaseModel):
    jobs: list[_JobItem]


# ── task prompt ───────────────────────────────────────────────────────────────

_TASK = """\
You are scraping a company careers page to collect all job listings.

TARGET URL: {url}

YOUR STEPS:
1. Open the URL and wait for the page to fully load.
2. Find all job listings currently visible on the page.
   For each job collect:
     - title       : the job title / role name
     - url         : the FULL absolute URL to the individual job posting page
                     (follow any relative href and prepend the domain if needed)
     - company     : the company name (infer from the site domain if not shown)
     - location    : city / country / "Remote" as shown
     - job_type    : e.g. "Full-time", "Contract", "Internship" — null if not shown
     - posted_date : e.g. "Posted 3 days ago" — null if not shown
3. If the page has pagination ("Next", "›", numbered pages) or a "Load More" button:
     - Click it to load the next set of results.
     - Collect jobs from that page too.
     - Repeat until there are no more pages or the button is disabled.
4. When you have collected ALL jobs across ALL pages, return them.

RULES:
- Every job URL must be a full URL starting with http:// or https://.
- Do not open individual job detail pages — collect from the listing page only.
- Do not duplicate jobs you already collected on a previous page.
- If a field is not visible, set it to null.
- Stop as soon as there are no more pages to load.
"""


# ── public entry point ────────────────────────────────────────────────────────

async def scrape_with_browser_use(url: str, max_steps: int = 150) -> list[JobPosting]:
    """
    Run the browser-use agent on a careers listing URL and return JobPostings.
    """
    from browser_use import Agent, BrowserProfile
    from browser_use.llm.openai.chat import ChatOpenAI

    model = _model_from_config()
    llm   = ChatOpenAI(model=model)

    profile = BrowserProfile(headless=False)

    agent = Agent(
        task=_TASK.format(url=url),
        llm=llm,
        browser_profile=profile,
        output_model_schema=_JobListOutput,
        max_failures=5,
        use_vision=True,
    )

    print(f"  [browser-use] starting agent (model={model}, max_steps={max_steps})")
    history = await agent.run(max_steps=max_steps)

    return _parse_history(history, url)


# ── helpers ───────────────────────────────────────────────────────────────────

def _model_from_config() -> str:
    cfg_path = Path("config.yaml")
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text()) or {}
        return raw.get("llm", {}).get("analyst", {}).get("model", "gpt-4o")
    return "gpt-4o"


def _parse_history(history, url: str) -> list[JobPosting]:
    """Extract job postings from agent history, trying structured then raw JSON."""
    jobs_data: list[dict] = []

    # Try structured output first
    try:
        structured = history.get_structured_output(_JobListOutput)
        if structured and structured.jobs:
            jobs_data = [j.model_dump() for j in structured.jobs]
    except Exception:
        pass

    # Fall back to parsing final_result() as JSON text
    if not jobs_data:
        raw = history.final_result()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    jobs_data = parsed
                elif isinstance(parsed, dict):
                    # handle {"jobs": [...]} wrapper
                    for v in parsed.values():
                        if isinstance(v, list) and v:
                            jobs_data = v
                            break
            except (json.JSONDecodeError, TypeError):
                pass

    if not jobs_data:
        print("  [browser-use] agent returned no structured data")
        return []

    print(f"  [browser-use] agent collected {len(jobs_data)} job(s)")

    postings: list[JobPosting] = []
    for d in jobs_data:
        if not isinstance(d, dict):
            continue
        d = {k: v for k, v in d.items() if v is not None}
        if not d.get("title"):
            continue
        # Derive company from URL if missing
        if not d.get("company"):
            from job_agent.scraper.script_runner import _company_from_url
            d["company"] = _company_from_url(d.get("url") or url)
        try:
            postings.append(JobPosting(**d))
        except Exception as e:
            print(f"  [browser-use] skipped job: {e}")

    return postings
