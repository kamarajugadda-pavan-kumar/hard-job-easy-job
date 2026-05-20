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
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.firefox.launch(headless=False)
        try:
            page = await browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:125.0) "
                    "Gecko/20100101 Firefox/125.0"
                ),
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(2_000)
            return await page.inner_text("body")
        except Exception as e:
            print(f"  [single_job] fetch failed: {e}")
            return ""
        finally:
            await browser.close()


async def _llm_extract(url: str, page_text: str) -> JobPosting:
    """Send page text to LLM and parse into a JobPosting."""
    import json
    from urllib.parse import urlparse
    from langchain_core.messages import HumanMessage
    from job_agent.llm import get_llm

    prompt = EXTRACT_PROMPT.format(url=url, page_text=page_text[:8000])
    llm = get_llm("analyst")
    response = await llm.ainvoke([HumanMessage(content=prompt)])

    text = response.content if isinstance(response.content, str) else str(response.content)
    # Strip markdown fences if present
    import re
    match = re.search(r"```(?:json)?\n(.*?)```", text, re.DOTALL)
    data = json.loads(match.group(1) if match else text)

    # Ensure company is set
    if not data.get("company"):
        host = urlparse(url).netloc.replace("www.", "")
        name = host.split(".")[-2]
        data["company"] = name.upper() if len(name) <= 4 else name.capitalize()

    data["url"] = url
    data = {k: v for k, v in data.items() if v is not None}
    return JobPosting(**data)


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
