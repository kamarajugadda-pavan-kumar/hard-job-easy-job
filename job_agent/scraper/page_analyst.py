"""
Opens a URL with Playwright, captures a screenshot + HTML excerpt,
then asks the LLM to analyse the page structure.

Output is a PageAnalysis dataclass that the ScriptWriter uses to
generate a targeted scraper.
"""
from __future__ import annotations

from pydantic import BaseModel


class PageAnalysis(BaseModel):
    url: str
    page_type: str                        # "listing" | "single_job" | "unknown"
    requires_javascript: bool = True
    job_card_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    location_selector: str | None = None
    pagination_type: str = "none"         # "numbered" | "load_more_button" | "infinite_scroll" | "none"
    pagination_selector: str | None = None
    filter_controls: list[str] = []
    total_jobs_visible: int = 0
    notes: str = ""


async def analyse_page(url: str) -> tuple[PageAnalysis, bytes, str]:
    """
    Opens the URL, captures screenshot + HTML, calls LLM to analyse.

    Returns
    -------
    analysis   : PageAnalysis
    screenshot : raw PNG bytes  (passed to ScriptWriter for visual context)
    html_excerpt : first 5000 chars of page HTML
    """
    screenshot, html = await _capture_page(url)
    analysis = await _llm_analyse(url, screenshot, html)
    return analysis, screenshot, html[:5000]


async def _capture_page(url: str) -> tuple[bytes, str]:
    """Use Playwright to load the page and return (screenshot_bytes, full_html)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            # Extra wait for JS-heavy pages that render after networkidle
            await page.wait_for_timeout(1_500)
            screenshot = await page.screenshot(full_page=True, type="png")
            html = await page.content()
            return screenshot, html
        finally:
            await browser.close()


async def _llm_analyse(url: str, screenshot: bytes, html: str) -> PageAnalysis:
    """Send screenshot + HTML to the LLM and return a structured PageAnalysis."""
    import base64

    from langchain_core.messages import HumanMessage

    from job_agent.llm import get_llm

    prompt = ANALYST_PROMPT.format(url=url, html=html[:5000])
    image_b64 = base64.b64encode(screenshot).decode()

    msg = HumanMessage(content=[
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        },
        {"type": "text", "text": prompt},
    ])

    llm = get_llm("analyst").with_structured_output(PageAnalysis)
    raw = await llm.ainvoke([msg])
    result = PageAnalysis.model_validate(raw if isinstance(raw, dict) else raw.model_dump())
    result.url = url
    return result


ANALYST_PROMPT = """
You are analysing a company job listings page to help write a web scraper.

URL: {url}
HTML excerpt (first 5000 chars):
{html}

[A screenshot of the page is also attached.]

Identify and return JSON conforming to this schema:
{{
  "page_type": "listing" | "single_job" | "unknown",
  "requires_javascript": true | false,
  "job_card_selector": "<CSS selector for each job card>",
  "title_selector": "<CSS selector for title inside card>",
  "link_selector": "<CSS selector for the job URL inside card>",
  "location_selector": "<CSS selector for location, or null>",
  "pagination_type": "numbered" | "load_more_button" | "infinite_scroll" | "none",
  "pagination_selector": "<CSS selector for next-page control, or null>",
  "filter_controls": ["location", "team", ...],
  "total_jobs_visible": <integer estimate>,
  "notes": "<any quirks or special handling needed>"
}}
Return only valid JSON. No explanation.
"""
