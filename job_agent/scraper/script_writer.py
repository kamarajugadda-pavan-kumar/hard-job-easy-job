"""
Takes a PageAnalysis and asks the LLM to write a Python scraper script
that conforms to the standard interface:

    async def scrape(base_url: str, filters: dict | None = None,
                     max_pages: int = 10) -> list[dict]:
        ...

The generated script is saved to data/scrapers/{domain_slug}.py.
On retry, the previous script + error traceback are included so the LLM
can fix the specific failure.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from job_agent.scraper.page_analyst import PageAnalysis

SCRAPERS_DIR = Path("data/scrapers")

SCRIPT_INTERFACE = '''
async def scrape(
    base_url: str,
    filters: dict | None = None,
    max_pages: int = 10,
) -> list[dict]:
    """
    Returns a list of dicts, each with these keys (use None for missing fields):
        title, url, company, location, description, posted_date, job_type
    Writes the result as JSON to stdout before returning.
    """
'''


def domain_slug(url: str) -> str:
    """'https://stripe.com/jobs' → 'stripe_com'"""
    host = urlparse(url).netloc.replace(".", "_").replace("-", "_")
    return re.sub(r"_+", "_", host).strip("_")


def script_path(url: str) -> Path:
    return SCRAPERS_DIR / f"{domain_slug(url)}.py"


async def write_script(
    analysis: PageAnalysis,
    screenshot: bytes,
    html_excerpt: str,
    previous_script: str = "",
    previous_error: str = "",
) -> Path:
    """
    Calls the LLM to generate (or fix) a scraper script.
    Saves it to data/scrapers/ and returns the path.
    """
    import base64

    from langchain_core.messages import HumanMessage

    from job_agent.llm import get_llm

    retry_section = (
        RETRY_SECTION.format(
            previous_script=previous_script,
            previous_error=previous_error,
        )
        if previous_script
        else ""
    )

    prompt = WRITE_PROMPT.format(
        url=analysis.url,
        analysis_json=analysis.model_dump_json(indent=2),
        html_excerpt=html_excerpt,
        retry_section=retry_section,
    )

    image_b64 = base64.b64encode(screenshot).decode()
    msg = HumanMessage(content=[
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        },
        {"type": "text", "text": prompt},
    ])

    llm = get_llm("script_writer")
    response = await llm.ainvoke([msg])
    code = _extract_code(response.content)

    path = script_path(analysis.url)
    SCRAPERS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    return path


def _extract_code(content: str | list) -> str:
    """Strip markdown fences if the LLM wrapped the code despite instructions."""
    if isinstance(content, list):
        # LangChain multimodal response — join text parts
        text = "\n".join(
            part["text"] if isinstance(part, dict) else part
            for part in content
            if isinstance(part, str) or (isinstance(part, dict) and part.get("type") == "text")
        )
    else:
        text = content

    text = text.strip()
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


WRITE_PROMPT = """
You are writing a robust Python web scraper for a heavily JavaScript-driven job listings page.
Assume the page uses a React/Angular/Vue frontend where content renders AFTER the initial HTML load.

═══════════════════════════════════════
TARGET URL:      {url}
PAGE ANALYSIS:   {analysis_json}
HTML EXCERPT:    {html_excerpt}
[Screenshot attached for visual reference]
═══════════════════════════════════════

{retry_section}

━━━ REQUIRED FUNCTION SIGNATURE ━━━
Define this exact function:

    async def scrape(base_url: str, filters: dict | None = None, max_pages: int = 10) -> list[dict]:

Each returned dict MUST have these keys (set to None if not found):
    title, url, company, location, description, posted_date, job_type

━━━ PLAYWRIGHT RULES (follow all of these) ━━━

1. NAVIGATION — always do this after page.goto():
   - await page.wait_for_load_state("networkidle")
   - Then ALSO wait for a known job-content selector:
       await page.wait_for_selector("<job_card_or_list_selector>", timeout=15000)
   Never query the DOM immediately after goto() — React hydration happens after networkidle.

2. SELECTOR STRATEGY — never hardcode a single selector. Use a priority list:
   - Try each candidate with page.query_selector_all() and use the first that returns results.
   - Infer candidates from the HTML excerpt and screenshot (look for repeated li/div/article patterns).
   - If no candidates work, fall back to: page.query_selector_all('[class*="job"], [class*="position"], [class*="listing"], article, li')

3. LAZY LOADING — always scroll before scraping:
   await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
   await page.wait_for_timeout(1500)
   Then scroll back up if needed and re-query.

4. SHADOW DOM / IFRAMES — if query_selector_all returns 0 results on the main frame:
   - Check for iframes: frames = page.frames
   - Try the same selectors on each frame.

5. PAGINATION — after every page turn:
   - Wait for new job cards to appear before scraping, do NOT just wait a fixed time.
   - Use: await page.wait_for_selector("<card_selector>", state="attached", timeout=10000)
   - Detect end-of-pagination by checking if the next button is disabled/hidden or job count stops growing.

6. BOT PROTECTION — always set a realistic browser context:
   - viewport: {{"width": 1280, "height": 900}}
   - user_agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
   - Add await page.wait_for_timeout(800) between paginated requests.

7. DOM VALIDATION — before scraping, assert you have results:
   - If len(cards) == 0 after trying all selectors, print a debug snapshot:
       print("[DEBUG] page title:", await page.title(), file=__import__('sys').stderr)
       print("[DEBUG] body excerpt:", (await page.content())[:2000], file=__import__('sys').stderr)
   - Then raise RuntimeError("No job cards found — selectors need updating")

8. FIELD EXTRACTION — be defensive on every field:
   - Always use try/except or conditional checks per field; one missing field must not crash the whole card.
   - Resolve relative URLs: use urllib.parse.urljoin(base_url, href)

━━━ SCRIPT STRUCTURE ━━━
- Imports at top (playwright, json, asyncio, sys, urllib.parse, etc.)
- The scrape() function
- An async main() that calls scrape() and does: print(json.dumps(result, ensure_ascii=False))
- if __name__ == "__main__": asyncio.run(main())

━━━ OUTPUT ━━━
Return ONLY valid Python code. No explanation, no markdown fences, no comments beyond the minimum.
"""

RETRY_SECTION = """
━━━ PREVIOUS ATTEMPT FAILED — FIX THIS ━━━

Script that failed:
{previous_script}

Error / traceback:
{previous_error}

Instructions:
- Fix the specific error above — do not rewrite from scratch unless the approach is fundamentally wrong.
- If selectors returned 0 results, try different selector candidates based on the HTML excerpt.
- If a timeout occurred, increase the timeout or add a wait_for_selector() before the failing line.
- If a field extraction crashed, wrap it in try/except and default to None.
"""
